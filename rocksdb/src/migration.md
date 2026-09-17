# Migrations

Every rung on the [pathway](pathway.md) that touches an existing node's
database needs an answer to the same question: someone upgrades a running
node, and it has the old database on disk. S9 through S17 answer it five
different ways, and I kept solving it ad hoc until S10 forced the issue —
so this page writes the framework down once, worked out against S10's
actual backfill and against whether S15's engine swap could use it too.

## The framework

One table, next to `database_version` (which stays scoped to the v1/v2
schema flag — I'm not overloading it):

```sql
CREATE TABLE IF NOT EXISTS migrations(id TEXT PRIMARY KEY, state TEXT, progress BLOB)
```

Created the same way every other table in this schema is: `CREATE TABLE IF
NOT EXISTS`, called from whichever store's own `create()` needs it, no new
central "opens all stores" call site. Every migration declares one kind:

- **instant** — DDL only, inline at open. S9's `chain_index` table is
  already this, implicitly. The framework doesn't change what it does,
  just gives it a row (`state = done` right after the DDL) so there's one
  place to see what's happened to a given database file instead of
  inferring it from `sqlite_master`.
- **background** — resumable, the node serves while it runs, readers fall
  back to the old structure until `state = done`. S10 below is the first
  of these.
- **required** — must be `done` before the node serves. Resumable and
  cheap: run inline at startup with a progress log. Big: refuse to start,
  "run `chia db migrate`."
- **background + cutover** — background until a small enough remainder
  that finishing needs a brief stop. S15, maybe — see below.

`chia db migrate` runs every pending migration to completion: same
batch/resume code as the background runner, just no throttle and no
pause-for-sync. It's the escape hatch — an operator who wants a
`required` migration's precondition satisfied today, not whenever the
background pass gets there, runs this once. It is deliberately not the
default post-upgrade UX: `chia db upgrade` (the v1→v2 tool, hours
offline, twice the disk) is what "run a migration command" already means
to users, and a lazy background fill doesn't deserve to spend that
goodwill by forcing itself into the foreground.

No dependency graph — a linear list. S9 through S13 are already strictly
ordered on the [pathway](pathway.md); nothing here needs more structure
than that.

Precedent already in the tree, worth naming: the height-to-hash cache
already does a resumable-ish backward walk from the peak whenever its
on-disk file goes stale, rebuilding whatever's missing before serving.
S10 is that same walk, except it persists across restarts instead of
starting over every time.

## Worked example: S10, the `chain_index` backfill

S9 added a `height -> header_hash` table, dual-written going forward from
whichever block happens to be the peak when a node upgrades
([Atomicity invariants](invariants.md)). Existing history below that point
starts out missing. S10 fills it in: a `background` migration, walking
`prev_hash` from the oldest filled height downward, in batches, persisting
a low-water mark so a restart resumes instead of restarting.

The invariant: the table is correct and contiguous on `[low, peak]`, empty
below `low`. Each batch reads blocks by chasing `prev_hash` backward
(cheap point reads, safe to do without the write lock — historical block
rows are never mutated, only orphaned), then commits a batch of rows plus
the new `low` in one transaction. A crash mid-batch loses nothing: SQLite
either commits the whole batch and the pointer move, or neither. A reorg
deeper than the already-filled range is the one real interaction with live
writes, and it turns out to need one extra line where the node already
handles rollbacks: clamp the low-water mark down to the fork point,
exactly mirroring what rollback already does to the table itself. Readers
that only need a single height can start using the table immediately for
anything at or above the low-water mark; the full height-map load switches
over only once the fill completes, since a partial-source hybrid loader
isn't worth the complexity for a one-time startup cost.

## Could S15 be background too?

S15's plan today is `chia db upgrade`'s shape: an offline, one-pass
conversion from the SQLite snapshot to RocksDB
([Target design](target.md), [Benchmarks](benchmarks.md) for the replay
timings this is compared against — half a day even on the fast engine).
Worth asking whether it could run in the background instead, the way S10
does. Sketch: bulk-build the RocksDB store from SQLite in the background,
catch up whatever landed during the build directly from `coin_record` (no
generator re-execution — the same linear-scan-by-height trick the
benchmark extraction already uses), and finish at the next restart once
the remaining delta is small. Verdict: **yes, with fixes.**

**Don't pin one read snapshot for the whole build.** A single, hours-long
snapshot pins SQLite's WAL from checkpointing for its whole duration and
ties up one of a small pool of read connections — real cost on the
small-disk, weak-hardware boxes this migration exists to help. Instead,
split `[0, peak]` into phases (a hundred-odd height ranges) and give each
its own short-lived snapshot: stream both height-sorted queries the tool
already needs (creations by `confirmed_index`, removals by `spent_index`)
restricted to that phase's range, write the batch, record the phase index
as the resume point, close the snapshot. This isn't new machinery — the
two streams already have to be consumed in height-grouped chunks to
assemble one undo record per height in O(1) memory, so phasing just
checkpoints boundaries the tool was going to pass through anyway. It pays
for itself three ways: resumability becomes the phase index, exactly
S10's watermark shape one level up; a reorg only invalidates phases whose
range reaches above the fork height, not the whole build; and the final
catch-up delta shrinks to a clean rule — rows with `spent_index` past the
*first* phase's snapshot height, or `confirmed_index` past the *last*
phase's — bounded by spends during the build's wall-clock duration, not
by the size of the coin set.

Two more things worth naming:

- The delta needs block hash and timestamp per height too, not just
  `coin_record` — a second, still-cheap table join, not a hole in the
  no-generator-execution claim, just an incomplete accounting of which
  tables are involved.
- "Bounded by `MAX_REORG_DEPTH`" isn't true yet — that constant doesn't
  exist as an enforced limit in the node today ([Decision log](decisions.md)
  has it as a still-pending lean-mode parameter). A reorg past every
  phase built so far is rare, not bounded; the tool needs to handle a
  from-scratch restart as a real case, even if in practice it never
  happens ([Decision log](decisions.md)'s reorg archeology: 145 orphans
  in all of mainnet history, essentially all single-block).

### Sharding the drain instead of building alongside

The sketch above still keeps a full SQLite copy around for the whole
build. Could it drain — delete rows out of SQLite as they're copied over —
and skip the 2× disk entirely? Two issues.

**Routing.** Coin lookups key by `coin_id` / `puzzle_hash`, not height, so
draining can't be routed by height the way the build above is. Writes
can't split by "which store holds this coin" either: a single block both
creates and spends coins, and if creates went to RocksDB while spends of
undrained coins went to SQLite, one block's write would need to touch both
stores atomically — recreating the cross-store transaction
[Atomicity invariants](invariants.md) just eliminated. So the only
consistent shape is an overlay: from the *first* moment of migration,
every write goes to RocksDB only, and SQLite becomes a read-only body
being drained in the background, never written again. That moves the
write cutover to the *start*, closer to S9's dual-write shape than to
"build alongside, then flip." Reads check RocksDB first, fall back to
SQLite for anything not yet drained. Reorgs into pre-cutover heights need
the *old* rollback path (SQLite's `coin_record` scan — RocksDB has no
undo log for blocks it never processed), so cutover should happen at a
height already confirmed enough that reaching back past it is
astronomically unlikely, not just eventually so.

**SQLite doesn't give space back.** No `auto_vacuum` is set anywhere in
the schema, so deletes free pages to an internal freelist but the file
never shrinks without `VACUUM` — and `VACUUM` itself needs scratch space
≈ the *current live* content, while the old, still-full-size file exists
until the swap. Work the math with `ρ` = destination/source size for the
same data (not 1): draining fully with no `VACUUM` at all, then deleting
the empty file, peaks at `1+ρ`. One `VACUUM` at the right point (roughly
where the not-yet-drained SQLite fraction and the drain's own progress
balance out) does better. Plug in real numbers instead of assuming equal
sizes: [Benchmarks](benchmarks.md)'s full-mainnet run measured
`sqlite-consensus` at 99.5 GB against `rocks` at 68.3 GB and `rocks-lean`
at 54.2 GB for the *same* history — `ρ ≈ 0.69` / `0.55`. So "2×" was
already an overestimate: no `VACUUM` at all peaks around `1.5-1.7×`, and
one well-timed `VACUUM` brings that down to roughly `1.2-1.3×`. But
`VACUUM` is file-granular, not table-granular — `coin_record` shares a
file with the archive (`full_blocks`, which stays SQLite forever, per
S17), so a `VACUUM` rewrites that too, every time, scaling with the whole
database's size (215 GB and growing) rather than just `coin_record`'s
share — closer in cost to `chia db upgrade`'s own offline rewrite than to
a quick operation. `VACUUM INTO` bounds the exclusive-lock window to the
final swap instead of the whole rebuild, if a mid-drain `VACUUM` is used
at all. Recommendation: **skip it unless disk is genuinely tight** — the
`1.5-1.7×` peak self-resolves the moment the drain finishes and the empty
file gets deleted, no exclusive-lock maintenance window required. Make a
mid-drain `VACUUM` an operator flag, not part of the default path. On two
volumes, none of this applies — put the destination on the other one.

### Cutover

The write-target switch to RocksDB is the one atomic, restart-boundary
event, and it happens at the *start* of the overlay design above, not the
end — a live hot-swap partway through would reintroduce the
[db_v3 lesson](decisions.md)'s bug class (splitting the atomic unit across
two stores, even briefly). There's no second cutover needed at
completion: reads already prefer RocksDB throughout, and finishing the
drain just deletes an empty SQLite remnant. `chia db migrate --cutover`
still names the foreground escape hatch — "run every phase now,
unthrottled" — matching S10's `chia db migrate`.

## Kind, by step

| Step | What migrates | Kind |
|---|---|---|
| S9 | `chain_index` table (DDL) | instant |
| S10 | `chain_index` historical fill | background |
| S11 | drop `in_main_chain` writes | required, gated on S10 done |
| S12 | `DBWrapper2` becomes store-internal | n/a — types only |
| S13 | height map becomes a bounded cache | n/a — in-RAM only |
| S14 | generator lookup's fork-chain branch dropped | n/a — height-gated |
| S15 | RocksDB backend | required today; background + cutover above |
| S16 | lean mode / bounded undo window | background (compaction-filter GC) |
| S17 | ExplorerStore split | background (backfill tool, rebuildable) |

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
does. Sketch: snapshot the SQLite database at the current peak, bulk-build
the RocksDB store from it in the background, catch up whatever landed
since the snapshot directly from `coin_record` (no generator
re-execution — the same linear-scan-by-height trick the benchmark
extraction already uses), and finish at the next restart once the
remaining delta is small.

Three things the sketch glosses over:

- A single, hours-long read snapshot pins SQLite's WAL from checkpointing
  for its whole duration, and ties up one of a small pool of read
  connections — real cost on the small-disk, weak-hardware boxes this
  whole migration exists to help. Fix: re-snapshot per chunk instead of
  holding one giant transaction open, the same way S10 commits per batch
  instead of one pass.
- The delta needs block hash and timestamp per height too, not just
  `coin_record` — a second, still-cheap table join, not a hole in the
  no-generator-execution claim, just an incomplete accounting of which
  tables are involved.
- "Bounded by `MAX_REORG_DEPTH`" isn't true yet — that constant doesn't
  exist as an enforced limit in the node today ([Decision log](decisions.md)
  has it as a still-pending lean-mode parameter). A reorg past the
  snapshot point is rare, not bounded; the tool needs to handle a
  from-scratch restart as a real case. A reorg that stays within the
  delta already applied doesn't need that, though — the target design's
  own rewind method handles it same as any other rollback.

Cutover stays a restart-boundary event either way, not a live hot-swap —
that's the [db_v3 lesson](decisions.md): splitting the atomic unit across
two stores, even briefly, is the bug class that killed the earlier
attempt. Verdict: yes, with those three fixes folded in. `chia db migrate
--cutover` would be the explicit foreground alternative, same escape
hatch as S10's.

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

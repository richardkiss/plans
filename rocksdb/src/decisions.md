**[agent draft — I haven't reviewed this text yet]**

# Decision log

Dated decisions with the evidence behind them. Newest last, so the page
reads as a narrative.

## 2026-07-14 — Binding: rocksdict, not a revived rocks_pyo3

I had a bespoke pyo3 binding (`rocks_pyo3`, ~212 lines of Rust) from earlier
experiments. It worked as a spike vehicle, but it's missing snapshots
(required by `CoinStoreSnapshot`), column families, and GIL release — every
RocksDB call would block the asyncio event loop — and its iterator erases
lifetimes with an unsafe transmute. Call it 2–4 weeks to make shippable,
plus CI/wheel infrastructure, plus maintaining it forever.

`rocksdict` (PyPI, MIT, production/stable) already ships Snapshot,
ColumnFamily, WriteBatch, ReadOptions, SstFileWriter, and wheels for all
three platforms. Its known limitations — no merge operators, no custom
comparators — don't matter for this schema (big-endian key encoding gives
ordering). And a dependency on a maintained MIT package is an easier
upstream sell than my own binding.

Decision: rocksdict. `rocks_pyo3` stays archived as a fallback if rocksdict
ever proves inadequate.

## 2026-07-14 — Reject the two-DB split (the db_v3 lesson)

The db_v3 experiment bolted RocksDB onto the side: coins in RocksDB, block
records + peak + `in_main_chain` still in SQLite. It actually synced mainnet
— and it demonstrated the fatal flaw. `_reconsider_peak`'s atomic
transaction now spanned two databases with no coordination; a crash
mid-reorg corrupts state.

Decision: coins, undo log, and peak live in one store, updated in one atomic
WriteBatch. No RocksDB backend PR before the peak/block-record migration
lands — anything earlier repeats db_v3's flaw.

## 2026-07-14 — Benchmark includes reads, not write-only replay

Real validation multi-gets the removals before applying a block. A
write-only benchmark flatters both engines and misses the index-read costs
entirely — and on spinning disks, reads are where B-tree and LSM diverge
most.

Decision: the replay harness does multi-get removals, then the write batch,
matching the real `new_block` shape.

## 2026-07-15 — Delete spent coins (rocks-lean), justified by reorg archeology

Deleting spent coins instead of flagging them shrinks the live keyspace to
the UTXO set. But it raises a correctness question: how often do reorged
(rolled-back) transactions *not* get re-included, leaving coins that have to
be resurrected from undo history long after the fact?

I measured it on all of mainnet history. The mainnet DB retains orphaned
blocks (`in_main_chain=0`): 145 orphans out of 8,582,005 blocks (0.0017%).
I ran every orphaned transaction block's generator and compared against the
main chain:

- 3,997 orphaned spends; 3,995 later spent on the main chain identically,
  0 never spent (the remaining 2 spent coins that never existed on main —
  children of orphan-only creations).
- 6,417 orphaned created coins; 6,411 identically re-created on main.

So reorged transactions get re-included essentially verbatim; reorg litter
is ~zero across all of mainnet history. I suspected "not much havoc" going
in, but it was nice to see zeros. Combined with `rocks-lean` winning every
benchmark axis (speed, size, working set), delete-spent-coins is the right
production design.

Decision: rocks-lean is the target semantics. Spent-coin lookups become the
ExplorerStore's job.

> **Superseded 2026-11-03** (entry below): lean mode is deferred to S17,
> gated on fork-relative reads and on routing consensus's own per-height
> history readers.

## 2026-07-15 — Keep timestamps on coins, for now

Coin timestamps are consulted at spend time (`ASSERT_SECONDS_RELATIVE`
time-lock checks). They're derivable from the block's undo record — but that
requires the undo record to still exist, which collides with pruning undo
records beyond reorg depth.

Decision: keep the timestamp field (8 of 89 bytes per record) for now. The
clean future fix is a separate append-only `height -> timestamp` map (~12 B
per transaction block, ~100 MB for all of mainnet, never needs atomicity).
A post-migration option, not on the critical path.

> **Partly superseded 2026-11-03:** a `height -> timestamp` map isn't
> append-only through a reorg, so it has to be written inside the
> transition, not on the side.

## 2026-09-17 — Generator lookup survives HF2; it moves, doesn't die

Earlier pages said HF2 removes generators from the consensus path. Wrong:
HF2 only stops *new* blocks from using backrefs (`validate_tx_generator`
rejects v0 blocks at/above the fork height and v1 below it); every existing
block below the fork height keeps its `transactions_generator_ref_list`
forever, so `get_generator` / `get_generators_at` never stop being called.

What actually changes: a ref can only point below the referring block, and
no block at or above HF2_HEIGHT has one, so every ref'd height is fixed once
the peak passes HF2_HEIGHT + `MAX_REORG_DEPTH` — no reorg can reach it. Past
that point the lookup is reorg-immune, so it doesn't need to live inside the
consensus store's atomic write scope. It moves to the archive as a plain
height-keyed read instead.

Decision: the API doesn't get deleted at S14, it moves — off the consensus
store, onto the archive, with the fork-chain branch of the lookup dropped
once the reorg-immunity bound holds. No `ChainView`/pin form needed for it;
a constant "main chain, frozen below HF2" context is all post-HF2 callers
ever see.

> **Superseded 2026-11-03** (entry below): the fork-chain branch stays.
> `MAX_REORG_DEPTH` isn't enforced anywhere, and a ref resolves against
> its own block's chain, so the lookup stays branch-aware and moves to the
> archive by hash.

## 2026-11-03 — Independent review: contract first, lean mode later

I had the plan reviewed from scratch by another model, against the code.
What changed:

- **Lean mode isn't safe yet.** The 07-15 archeology below shows that
  reorged transactions come back. It doesn't cover validation. A block on a
  competing fork is validated against the current store *before* any
  reorg, and it can legitimately spend a coin the main chain spent after
  the fork point. With spent coins deleted, that block is rejected
  (`block_body_validation.py:486-525`). Fix: a fork-relative read built from
  the undo records above the fork, which have to hold full coin records.
  Lean mode is now S17, gated on that read.
- **The atomic unit is the whole transition**, not one block: rewind plus
  every replacement block (including blocks without transactions) plus
  chain index plus peak, with read-your-writes. The four-method spike API
  didn't express that. S10 builds the interface on SQLite first.
- **A SQLite chain index ships only with a reader.** Today the
  height → hash mapping exists as `in_main_chain` flags (the authority), the
  `height-to-hash` file (a lazily flushed cache) and RAM. Adding a table
  nobody reads makes four copies. If S13 doesn't need it, S15 builds the
  chain index during conversion.
- **No HF2 wait.** Historical generator refs resolve against their own
  block's chain forever. HF2 isn't finality, and a storage constant
  shouldn't quietly become one.
- **Offline conversion by default.** The drain design is set aside as
  unsafe ([Migrations](migration.md)).
- **The ExplorerStore lands before lean mode**, so spent-history queries
  and singleton lineage have a home before the default node drops them.
- **Consensus reads coin history too.** On newer main, the MMR rebuild
  calls `get_coin_commitments_root` for every post-HF2 height, and header
  filters read per-height additions and removals. Lean mode has to keep
  these answerable or persist what they derive.
- **Three questions are open for me to decide:** what serves puzzle-hash
  and lineage queries on a RocksDB node (ship S16 with S15, or a
  restricted validator first); how the archive stays ahead of consensus
  (sync it first, or a coverage checkpoint); and the SQLite checkpoint
  layout (same file frozen, or split files). See
  [Target design](target.md) and [Migrations](migration.md).

## 2026-11-05 — Archive durability: repair at startup

Coins live in RocksDB and blocks in SQLite, and either can lose its newest
writes on power loss. I'm not adding an fsync before each consensus commit.
fsync isn't especially reliable, and rewind has to work anyway. Instead,
startup walks the consensus peak back until the archive has every block the
chain index names, then rewinds to there
([Target design](target.md#the-archive-and-recovery)). The opposite case, a
block archived but not applied, is handled by the reconsider path in the
[S10 contract](s10-contract.md#retry).

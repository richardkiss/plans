# Decision log

Dated decisions with the evidence behind them. Newest last (this page reads
as a narrative).

## 2026-07-14 — Binding: rocksdict, not a revived rocks_pyo3

A bespoke pyo3 binding (`rocks_pyo3`, ~212 lines of Rust) existed from
earlier experiments. It worked as a spike vehicle but was missing snapshots
(required by `CoinStoreSnapshot`), column families, and GIL release (every
RocksDB call would block the asyncio event loop), and its iterator erased
lifetimes with an unsafe transmute. Estimated 2–4 weeks to make shippable,
plus CI/wheel infrastructure, plus permanent maintenance.

`rocksdict` (PyPI, MIT, production/stable) already ships Snapshot,
ColumnFamily, WriteBatch, ReadOptions, SstFileWriter, and wheels for all
three platforms. Its known limitations — no merge operators, no custom
comparators — are not needed by our schema (big-endian key encoding gives
ordering). A dependency on a maintained MIT package is also an easier
upstream sell than a bespoke binding.

**Decision:** adopt rocksdict; archive rocks_pyo3 as a fallback if rocksdict
ever proves inadequate.

## 2026-07-14 — Reject the two-DB split (the db_v3 lesson)

The db_v3 experiment bolted RocksDB onto the side: coins in RocksDB, block
records + peak + `in_main_chain` still in SQLite. It actually synced mainnet
— and demonstrated the fatal flaw: `_reconsider_peak`'s atomic transaction
now spanned two databases with no coordination. A crash mid-reorg corrupts
state.

**Decision:** coins, undo log, and peak live in one store and are updated in
one atomic WriteBatch. No RocksDB backend PR before the peak/block-record
migration lands, or it would repeat db_v3's flaw.

## 2026-07-14 — Benchmark includes reads, not write-only replay

Real validation multi-gets the removals before applying a block. A
write-only benchmark flatters both engines and completely misses index-read
costs — which, on spinning disks, is where B-tree and LSM diverge most.

**Decision:** the replay harness does multi-get removals then the write
batch, matching the real `new_block` shape.

## 2026-07-15 — Delete spent coins (rocks-lean), justified by reorg archeology

Deleting spent coins instead of flagging them shrinks the live keyspace to
the UTXO set, but raises a correctness question: how often do reorged
(rolled-back) transactions *not* get re-included — leaving coins that must
be resurrected from undo history long after the fact?

We measured it on all of mainnet history. The mainnet DB retains orphaned
blocks (`in_main_chain=0`): **145 orphans out of 8,582,005 blocks
(0.0017%)**. Running every orphaned transaction block's generator and
comparing against the main chain:

- 3,997 orphaned spends; **3,995 later spent on main chain identically, 0
  never spent** (the remaining 2 spent coins that never existed on main —
  children of orphan-only creations).
- 6,417 orphaned created coins; 6,411 identically re-created on main.

Reorged transactions are re-included essentially verbatim; reorg litter is
~zero across all of mainnet history. Combined with rocks-lean winning every
benchmark axis (speed, size, working set), delete-spent-coins is the right
production design.

**Decision:** rocks-lean is the target semantics. Spent-coin lookups become
the ExplorerStore's job.

## 2026-07-15 — Keep timestamps on coins, for now

Coin timestamps are consulted at spend time (`ASSERT_SECONDS_RELATIVE`
time-lock checks). They're derivable from the block's undo record — but that
requires the undo record to still exist, which collides with pruning undo
records beyond reorg depth.

**Decision:** keep the timestamp field (8 of 89 bytes per record) for now.
The clean future fix is a separate append-only `height -> timestamp` map
(~12 B per transaction block, ~100 MB for all of mainnet, never needs
atomicity). Post-migration option, not on the critical path.

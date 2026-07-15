# Target design

The production target is the `rocks-lean` variant from the benchmark: a
RocksDB-backed consensus coin store that keeps only the UTXO set live, with
everything needed for reorgs in a per-block undo log, and one atomic write
per block.

## Store shape

Spent coins are deleted, not flagged. When a coin is spent, its key is
removed from the live coin keyspace; the full spent `CoinRecord` goes into
that block's undo record, so a rewind can resurrect it exactly. The live
keyspace is the UTXO set plus a recent undo window — smaller working set,
better bloom filters and cache behavior, which is what serves the
spinning-disk goal. (Why deleting is safe on real mainnet history: see the
reorg archeology in the [decision log](decisions.md).)

The undo log: `b<height>` maps to a block record with the block hash,
timestamp, created coins, and the *full records* of spent coins. Undo
records double as the source for `get_coins_added/removed_at_height` and can
be pruned beyond reorg depth.

Peak lives in the same store: `p -> (height, header_hash)`.

## One atomic WriteBatch per block

Coins (creates + deletes), the block's undo record, and the peak update go
in *one* RocksDB WriteBatch. This is the load-bearing property: a crash at
any point leaves the store at a consistent block boundary.

I learned this the hard way. The earlier db_v3 experiment put coins in
RocksDB while block records and peak stayed in SQLite, and a crash mid-reorg
could corrupt state across the two databases. No design that splits the
atomic unit across stores — see the [decision log](decisions.md).

Rewinds follow the same discipline: the entire rewind (resurrect spent
coins, delete created coins, drop undo records above the target, move peak)
is one WriteBatch, not one batch per block walked.

## Minimal post-HF2 API

After hard fork 2, generator backrefs to prior blocks are gone, generators
leave the consensus path, and the atomic unit shrinks to coin set + peak.
The store surface becomes:

- `process_spends(new_coins, spent_coins, block_index, block_hash,
  timestamp)` — atomically create additions, delete removals, write the undo
  record, update peak. Returns the spent `CoinRecord`s and raises on
  missing/already-spent (it has to read them for the undo log anyway;
  merging read and write gives storage-level double-spend detection for
  free).
- `rewind_to_block_number(n)` — atomically undo everything above height *n*.
- `get_coin_records(coin_ids)` — batched reads (multi-get), via a snapshot
  for consistent views (mempool, pre-commit validation).
- `peak()` — current `(height, header_hash)`.

The benchmark implemented all four backends against exactly this surface,
so I have some evidence the interface is sufficient.

## Explorer queries move out

Puzzle-hash queries, coin states, parent lookups, hints — everything that
serves RPCs and the wallet protocol — moves to a separate ExplorerStore,
maintained outside the consensus path (and optional for a lean validator).
The consensus store answers only by coin ID, height, and peak.

## Binding: rocksdict

The Python binding is [rocksdict](https://pypi.org/project/rocksdict/)
(PyPI, MIT, production/stable): it ships Snapshot, ColumnFamily, WriteBatch,
ReadOptions, and prebuilt wheels for Linux/macOS/Windows. Why not revive my
own pyo3 binding: see the [decision log](decisions.md).

## Notes and open questions

Timestamps on coins stay for now (spend-time time-lock checks read them).
They're derivable from the block's undo record, but that collides with
pruning undo records beyond reorg depth. The clean future fix is a separate
append-only `height -> timestamp` map (~100 MB for all of mainnet, never
needs atomicity). Deferred; it saves 8 of 89 bytes per record.

One real open question: `get_unspent_lineage_info_for_puzzle_hash` (used by
the mempool for singleton fast-forward) is a puzzle-hash query, and it has
no home in a pure coin-ID KV store. Maybe a mempool-local index, maybe the
ExplorerStore. I don't know yet, and it has to be answered before the
RocksDB backend can fully replace the SQLite store in a default (non-lean)
node.

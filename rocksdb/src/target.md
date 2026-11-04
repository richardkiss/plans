**[agent draft — I haven't reviewed this text yet]**

# Target design

*(Revised 2026-11-03 after an independent review. The earlier version said
the four-method spike API was enough. It isn't: validation of competing
forks, whole-reorg atomicity and archive recovery were all missing. The
[decision log](decisions.md) has the entry.)*

The production target is a RocksDB-backed consensus store: the coin set, a
per-block undo log, the chain index and the peak, all advanced by one atomic
write per chain transition. Whether it keeps spent coins (`rocks`) or
deletes them (`rocks-lean`) is a later step, gated on fork validation, below.

## What the consensus store holds

- **Coins** keyed by coin ID.
- **Undo records**: `b<height>` → block hash, timestamp, created coin IDs,
  and the *full records* of the coins that block spent. A rewind resurrects
  coins from these, and they double as the source for
  `get_coins_added/removed_at_height`.
- **Chain index**: one key per height → header hash, for every main-chain
  height, transaction block or not. This is the only durable answer to
  "which block is at height N". Today that answer is stored three times:
  `in_main_chain` flags on every `full_blocks` row, BlockHeightMap's
  `height-to-hash` file, and the RAM copy loaded from it. The flags are the
  authority; the file is a lazily flushed cache, checked against the flags at
  startup. The chain index replaces the flags and the file. RAM keeps a cache
  of it.
- **Peak**: `p` → `(height, header_hash)`, the commit record for the whole
  store.
- **Metadata**: schema version, network id, lean/full flag, earliest
  retained undo height.

Sub-epoch summaries are sparse and come from block records. They stay
available through the archive by hash, or through a small sparse index
written in the same transition. They aren't a second height → hash table.

## One atomic transition, not one write per block

Today one SQLite transaction covers a whole reorg: the block blob insert,
the coin rewind, every replacement block's coin changes (blocks without
transactions skip the coin call entirely), the `in_main_chain` updates and
the peak (`blockchain.py:442-447`, `:539`, `:570-624`). The target keeps
that unit. It doesn't split it per block:

- `apply_transition(fork_height, blocks)`: rewind to `fork_height`, then
  apply each block in `blocks` in order. This covers coins, undo record,
  chain-index entry (for every height, including blocks without
  transactions) and final peak, all in **one** WriteBatch.
- Reads inside the transition see its own earlier writes. A coin created in
  block 101 of the replacement branch and spent in 102 has to be found, and
  so does a coin the rewind just resurrected. RocksDB's plain `get` doesn't
  see an unwritten WriteBatch, so the backend needs an indexed batch or an
  in-memory overlay. SQLite gets this for free today because
  `reader_no_transaction()` routes the writer task's reads to the write
  connection (`db_wrapper.py:482-493`).
- A failed or cancelled transition leaves nothing behind.

Durability is unchanged from the spike's posture: the peak key is the commit
record, so there's no per-block fsync. Power loss drops an unsynced WAL tail
and the store comes back exactly as of some height H. Keep the WAL on, flush
it on clean shutdown, and optionally sync every N blocks.

## Fork validation needs historical coin state

This is the requirement the old target missed. Body validation of a block
on a competing fork runs *before* any reorg (`blockchain.py:400-447`). It
looks coins up in the current store and accepts a coin that the main chain
spent after the fork point (`block_body_validation.py:486-525`). Example:
coin C is created at 90, the chains fork at 100, the main chain spends C at
103, and the fork's block 101 also spends C. That spend is valid on the
fork. With spent coins deleted, the lookup finds nothing, C isn't in the
fork's own additions, and the block is rejected with `UNKNOWN_UNSPENT`.

So the store needs a **fork-relative read**: coin state as of the fork
point, plus the fork's own overlay (which `ForkInfo` already carries).
With full spent records in the undo log, this can be built cheaply. The
coins the main chain spent above the fork are exactly the removals in
`b<fork+1> … b<peak>`. That makes "undo records hold full coin records" a
hard format requirement, not an optimization.

Until the fork-relative read exists and is tested (competing spends,
creations on either branch, ephemeral coins), the backend keeps spent
coins. Lean mode waits.

## The archive and recovery

Full block blobs stay in SQLite, addressed by header hash. Consensus and
archive are now two databases, and application write order across two
independently buffered databases is not durable order. Power loss can
leave a durable peak whose block blob was lost. Pick one, and test it:

- publish the archive write durably (synced) before the consensus commit, or
- on startup, check that the blob for every height above the last synced
  point exists, and rewind the consensus store until it does.

Today's startup needs the peak's block record (`blockchain.py:174-196`), and
`add_block` returns `ALREADY_HAVE_BLOCK` for a record already present
(`:382-391`). So "re-fetch it from the network" is not automatic recovery.
It needs code.

## Historical generator lookup stays branch-aware

HF2 stops new blocks from using generator refs. Old blocks keep theirs
forever, and syncing from genesis or validating a historical fork still
resolves them. A ref resolves against *that block's* chain, not the node's
current peak. The current fork-aware path (`blockchain.py:1077-1106`) stays.
The archive serves it as: resolve height → hash against the chain in
question, then fetch the immutable blob by hash. That separation doesn't
need to wait for HF2.

`MAX_REORG_DEPTH` doesn't exist in the code. An undo-retention window is a
storage policy, not a finality rule. Before any undo is pruned, a reorg
deeper than the window needs defined behavior (rebuild or resync). Silently
rejecting a valid heavier chain is a consensus change.

## Explorer queries move out

Puzzle-hash queries, coin states, parent lookups, hints: everything that
serves RPCs and the wallet protocol moves to a separate ExplorerStore,
maintained outside the consensus path. It publishes its own peak, so
consumers can see how far behind it is, and it can be rebuilt from the
archive. It must exist *before* lean mode removes spent history from the
default node, along with a home for singleton lineage (today's query joins
the spent parent, `coin_store.py:656-679`).

## Binding: rocksdict

[rocksdict](https://pypi.org/project/rocksdict/) (PyPI, MIT): Snapshot,
ColumnFamily, WriteBatch, ReadOptions, prebuilt wheels for
Linux/macOS/Windows. Check that it exposes an indexed batch, or plan the
overlay in Python. Why not revive my own pyo3 binding: see the
[decision log](decisions.md).

## Open questions

- Timestamps on coins stay for now (spend-time time-lock checks read them).
  A separate `height → timestamp` map would save 8 of 89 bytes per record,
  but it isn't append-only through a reorg, so it belongs inside the
  transition too.
- Singleton fast-forward (`get_unspent_lineage_info_for_puzzle_hash`) is a
  puzzle-hash query with retained parent ancestry. It needs a home before
  lean mode: a mempool-local index or the ExplorerStore.
- The BlockchainMMRManager is another chain-derived structure. It needs its
  own persisted-node design. Caching only its root can't support append,
  pop or proofs.

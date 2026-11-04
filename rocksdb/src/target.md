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
- **Undo records**: `b<height>` → block hash, timestamp, and the *full
  records* of the coins that block created and spent. A rewind deletes the
  created coins and resurrects the spent ones (spends first, so a coin
  created and spent in the same block stays gone). The full created
  records cost space, but without them a spent created coin can't be
  returned for its height after its own coin key is gone.
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

- `apply_transition(expected_peak, fork_height, blocks) -> TransitionResult`:
  - `expected_peak` is the `(height, header_hash)` the caller validated
    against. The call fails, writing nothing, if the store's peak differs.
    Callers also hold the blockchain's priority mutex, as today.
  - `fork_height` is the height to rewind to, with `-1` for "before genesis",
    the sentinel `ForkInfo` uses today.
  - `blocks` is the replacement branch in height order. Each entry is a
    validated change set, the data `_reconsider_peak` builds from `ForkInfo`
    today (`blockchain.py:570-603`): header hash, height, prev hash,
    timestamp, whether it's a transaction block, reward coins, other
    additions (with `same_as_parent`), and removal IDs. The store checks
    that each entry's prev hash is the hash at the height below it.
  - The simulator's rewind passes an empty `blocks` list.
  - `TransitionResult` carries what `StateChangeSummary` needs downstream:
    the rolled-back coin records and the new coin records.
  - Everything goes in **one** WriteBatch: coins, undo records, a
    chain-index entry for every height (including blocks without
    transactions), and the final peak.
- Reads inside the transition see its own earlier writes. A coin created in
  block 101 of the replacement branch and spent in 102 has to be found, and
  so does a coin the rewind just resurrected. RocksDB's plain `get` doesn't
  see an unwritten WriteBatch, so the backend needs an indexed batch or an
  in-memory overlay. SQLite gets this for free today because
  `reader_no_transaction()` routes the writer task's reads to the write
  connection (`db_wrapper.py:482-493`).
- **Commit point.** Writing the batch is the linearization point. A
  failure or cancellation *before* it leaves the store unchanged. The write
  itself is shielded from cancellation, the same way `DBWrapper2` shields
  its rollback and release today (`db_wrapper.py:340-355`). A caller
  cancelled *after* the commit gets a committed transition, not an abort.
  If the outcome is unknown (an I/O error mid-write), reopen and read the
  peak before retrying.
- **Publication.** After commit, the in-RAM state is updated with no
  awaits in between, as `blockchain.py:449-486` does today: peak height,
  the height map and SES cache, and the MMR. If publication fails, they're
  reloaded from the store. Tests cover cancellation before commit, during
  commit, and after commit before the result is delivered.

Durability is unchanged from the spike's posture: the peak key is the commit
record, so there's no per-block fsync. Power loss drops an unsynced WAL tail
and the *consensus store* comes back exactly as of some height H. For the
full node that also needs the archive recovery below. Keep the WAL on, flush
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
point. The validator then applies the fork's own overlay, which `ForkInfo`
already carries, exactly as it does today.

- **Pinned.** The view is opened on one snapshot and names both the
  canonical peak hash and the fork-point hash, and the store checks that
  the fork point is that peak's ancestor. A height alone can't name the
  ancestor once a concurrent reorg moves the peak. If the peak moves, the
  validator retries.
- **What it returns.** For coin C in the main chain's undo records
  `b<fork+1> … b<peak>`:
  - created above the fork → C doesn't exist in the view, even if it was
    later spent there;
  - created at or below the fork, spent above it → C is unspent in the view;
  - anything else → C as stored.

  `block_body_validation.py:491-531` already makes the same
  created-before/after-fork distinction. The rule moves into the view, and
  the validator keeps its `ForkInfo` logic.
- **History unavailable.** If the fork point is below the retained undo
  floor, the view returns a distinct "history unavailable" result, never
  "coin missing". The floor is published durably in the metadata, and
  pruning never goes past a floor that an open view is using.
- **Cost.** Scanning every undo record between fork and peak on each
  validation isn't obviously cheap. Build the reversal set once per fork,
  next to `ForkInfo`, and extend it as the peak moves. Measure it on the
  spike with real reorgs before calling it cheap.

That makes "undo records hold full coin records" a hard format requirement,
not an optimization.

Until the fork-relative read exists and is tested (competing spends,
creations on either branch, ephemeral coins), the backend keeps spent
coins. Lean mode waits.

## Historical coin data that consensus reads

Explorer queries aren't the only readers of past coin state. On newer main
(the S9 branch):

- `Blockchain.create` rebuilds the MMR at startup by calling
  `coin_store.get_coin_commitments_root(height)` for every post-HF2 height
  (`blockchain.py:190-199`, `coin_store.py:342-366`). Each call needs that
  height's created coins and removal IDs.
- Header-filter construction reads per-height additions and removals
  (`blockchain.py:979-991`).

So lean mode has to keep per-height history answerable for consensus, not
only for the ExplorerStore. Within the retained window, the undo records
answer these. Beyond it, either persist the MMR state (nodes and frontier)
plus each height's commitment root, or rebuild from the archive at a
measured cost. Every height-history caller is routed before S17.

## The archive and recovery

Full block blobs stay in SQLite, addressed by header hash. Consensus and
archive are now two databases, and application write order across two
independently buffered databases is not durable order. Power loss can
leave a durable peak whose block blob or block record was lost.

> **Open question A (Richard to decide): how the archive stays ahead of
> consensus.**
> 1. *Sync the archive write before the consensus commit.* Simple, but it
>    costs one fsync per block on the archive.
> 2. *Coverage checkpoint.* Record a durable, hash-identified archive
>    checkpoint (a peak hash, not a height, since a replacement branch can
>    add dependencies below a previously synced height). On startup, before
>    any cache loads, rewind consensus until every block and block record
>    it references is in the archive. Undo retention has to reach back to
>    that checkpoint.

Either way, after a rewind the archive can still hold blocks above the
recovered peak. `add_block` returns `ALREADY_HAVE_BLOCK` for a record that's
already present (`blockchain.py:382-391`), so re-fetching those blocks
won't bring the peak forward. Recovery needs a startup path that
reconsiders archived blocks above the peak as candidates, and today's
startup also needs the peak's block record (`:174-196`).

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
archive. Today these queries run on the same SQLite tables (`coin_store.py:656-679`
joins the spent parent for singleton lineage, and the mempool calls it). A
RocksDB store keyed only by coin ID can't answer them.

> **Open question B (Richard to decide): what serves these queries when
> S15 switches a node to RocksDB.**
> 1. *Ship S16 with S15*, so a RocksDB node is a full node from day one.
> 2. *S15 is a restricted validator mode*, with no wallet RPCs and no fast
>    forward, until S16 lands.
>
> Either way, S16 needs a catch-up and reorg-replay contract. Consumers
> that need an exact peak (like the mempool) have to be able to wait for
> it or get a clear "behind" answer.

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
  puzzle-hash query with retained parent ancestry. It needs a home by S15
  (see open question B): a mempool-local index or the ExplorerStore.
- The BlockchainMMRManager needs its own persisted-node design (see
  "Historical coin data" above). Caching only its root can't support
  append, pop or proofs.

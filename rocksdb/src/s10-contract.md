**[agent draft — I haven't reviewed this text yet]**

# S10 transition contract

S10 adds one operation to the consensus store, `apply_transition`, and
moves `_reconsider_peak` and the simulator's `revert_block_height` onto it.
This page is the contract, written so the PR can be checked against it.
Line numbers are against main at `6c193275d`.

## Scope: SQLite, existing tables, same transaction

S10 changes no schema and adds no tables.

- **Coins:** `coin_record`, through today's `rollback_to_block` and
  `new_block` logic.
- **Chain selection:** the `in_main_chain` flags, through today's `rollback`
  and `set_in_chain`.
- **Peak:** `current_peak`, through today's `set_peak`.
- **Undo:** none. SQLite derives rollback from `confirmed_index` and
  `spent_index`, as it does now. Undo records and chain-index keys are the
  RocksDB backend's format (S15). They aren't S10's.

The archive write stays inside the same SQLite transaction. `add_block`
still opens `block_store.transaction()` (`blockchain.py:442`), calls
`add_full_block`, and then calls `apply_transition`, which joins that
transaction. So a failed transition also rolls back the block blob, and a
retry works exactly as it does today. Moving the archive write out of the
transaction is S15's job, together with the retry path that needs (see
"Retry" below). Because of that, S12 (no `DBWrapper2` above the stores)
waits for S15, not for S10.

## Types

```python
@dataclass(frozen=True)
class BlockChange:
    header_hash: bytes32
    height: uint32
    prev_hash: bytes32
    timestamp: uint64 | None          # None for blocks without transactions
    is_transaction_block: bool
    reward_coins: list[Coin]
    additions: list[tuple[bytes32, Coin, bool]]   # (coin_id, coin, same_as_parent), as new_block takes today
    removals: list[bytes32]

@dataclass(frozen=True)
class TransitionResult:
    fork_height: int                          # as passed in
    peak: tuple[uint32, bytes32] | None       # the committed peak; None only for an empty store
    rolled_back: dict[bytes32, CoinRecord]    # same semantics as rollback_to_block today
```

`rolled_back` keeps today's encoding (`coin_store.py:566-601`): a coin
created above the fork comes back with confirmed height 0 and timestamp 0
(it was deleted), and a coin spent above the fork comes back unspent with
its original confirmed height.

## Signature and checks

```python
async def apply_transition(
    expected_peak: tuple[uint32, bytes32] | None,
    fork_height: int,
    blocks: list[BlockChange],
) -> TransitionResult
```

Each check below raises before anything is written:

- `expected_peak` must equal the stored peak. `None` means an empty store.
- `-1 <= fork_height <= expected_peak.height`. `-1` means before genesis,
  the sentinel `ForkInfo` uses today.
- `blocks[i].height == fork_height + 1 + i`, with no gaps.
- `blocks[0].prev_hash` is the main-chain hash at `fork_height`. For
  `fork_height == -1` it's the genesis challenge. Each later block's
  `prev_hash` is the previous entry's `header_hash`.
- Every block in `blocks` already has a `full_blocks` row. `set_in_chain`
  already enforces this.

An empty `blocks` list is a pure rewind, which is what the simulator uses.
The new peak is then the main-chain block at `fork_height`. With
`fork_height == -1` the store ends up empty and the peak is `None`. That
case is allowed, for tests.

## What the caller keeps

The store returns only what it computes. `_reconsider_peak` still builds
`StateChangeSummary` (`blockchain.py:75-83`, `:626-637`) from what it
already holds:

- the peak `BlockRecord`, and every replacement `BlockRecord` with its SES
  data (needed to update the height map);
- `(coin_id, puzzle_hash)` removals and `(Coin, hint)` additions, from
  `ForkInfo`. Hints never go into the store;
- the reward coins;
- on newer trees, each block's coin-commitment root for the MMR
  (`blockchain.py:488-500` on the S9 branch).

These live until publication finishes, including for an empty-branch
rewind.

## Commit, publication, cancellation

- **Serialization.** The caller holds the blockchain's priority mutex from
  before `apply_transition` until publication is finished. No other
  transition can run in between.
- **Commit point.** The SQLite `COMMIT` of the outer transaction. Before
  it, any failure or cancellation rolls everything back, blob included.
- **Cancellation can't split commit and publication.** From the start of
  `COMMIT` through publication, a cancellation is held and re-raised only
  after publication completes. That's the same suppress-through-cleanup
  pattern `DBWrapper2` uses for rollback and release
  (`db_wrapper.py:340-355`), not a detached shielded task. The caller sees
  either "nothing happened" or "committed and published, then cancelled".
- **Publication** is synchronous, with no awaits: the height map
  (rollback, then each new height with its SES), the MMR, then
  `_peak_height` last, as `blockchain.py:456-474` does today. Readers on the
  event loop see either all of the old state or all of the new state.
- **Publication failure is fail-stop.** If publication raises after
  `COMMIT`, the node logs and shuts down, and the next start reloads RAM
  from the store. Today's `except` block restores the old `_peak_height`
  even after a commit (`blockchain.py:476-486`). That's the behavior S10
  replaces, not something to copy.
- **Ambiguous commit** (an I/O error during `COMMIT`): also fail-stop.
  Startup reads the peak. Automatic retry without restarting comes later,
  if it's ever needed.

## Retry

In S10 the blob and the transition commit together, so after a failure
the block isn't archived, and resubmitting it works as it does today.

When S15 moves the archive write ahead of the consensus commit, a block
can be archived but not applied. `add_block` then returns
`ALREADY_HAVE_BLOCK` (`blockchain.py:382-390`) and never reconsiders it.
Archive existence can't tell "applied" from "needs applying" from "orphan".
S15 must add a reconsider path that runs both when `add_block` sees a known
block and at startup: if the block's weight beats the current peak and the
block isn't on the main chain, reconsider it as a peak candidate.

## Tests

- A reorg whose replacement branch spends coins created earlier in the same
  branch, and coins the rewind just resurrected.
- Blocks without transactions inside a replacement branch.
- Genesis: an empty store, `fork_height == -1`, one block.
- Simulator rewind with an empty branch, including rewinding to `-1`.
- Each precondition failing, with nothing written.
- Cancellation before `COMMIT`, during `COMMIT`, and after `COMMIT` before
  the result is delivered. Check the database, the RAM state, and whether
  the `StateChangeSummary` notification went out.
- A publication failure, giving fail-stop and correct state after restart.
- Resubmitting a block after an injected pre-commit failure.

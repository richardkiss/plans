# Pathway

Baby steps. Each step is a small, reviewable PR with acceptance criteria and
a rollback story. Nothing lands that isn't independently valuable, and the
expensive steps are sequenced after hard fork 2 (HF2) where that makes them
cheaper.

## Step 1 — Phase 1 protocols (in progress)

Pure type work, no DB changes. On the `store-split` branch:

- Rebase onto current main (the branch is ~492 commits behind; the diff is
  small and mostly additive).
- Slim `CoinStoreProtocol` to the consensus surface (5 methods) and create
  `BlockStoreProtocol` for what `Blockchain` actually uses; type-narrow
  `Blockchain` to both; delete the `chia.consensus -> chia.full_node` tach
  exception. (Already done on the branch.)
- **Add `snapshot()` / `CoinStoreSnapshot`** — the key abstraction, not yet
  implemented. SQLite implementation = read transaction; RocksDB will
  implement it as a Snapshot; tests get a frozen dict.
- Tests for the protocol surface.
- Open a PR superseding the stale #20566 (ConsensusStore) and #20443
  (db_v3).

*Acceptance:* `tach check` passes with the exception removed; existing tests
pass; snapshot semantics covered by new tests.
*Rollback:* pure types — revert the PR, nothing else moves.

## Step 2 (optional quick win) — drop explorer indexes from the consensus store

The benchmark's `sqlite-consensus` variant: removing the puzzle_hash and
coin_parent indexes from the consensus path buys ~1.5–2x on SQLite with no
engine change. Only worth doing as its own step if explorer queries have
somewhere else to go (ExplorerStore) or behind a lean-validator flag.
Independent of everything below; a cheap fallback if the RocksDB work
stalls.

*Acceptance:* sync throughput improves on a reference box; RPC/wallet
queries still answered (from the explorer side).
*Rollback:* re-create the indexes; data loss is impossible (indexes are
derived).

## Wait point — HF2 lands (external dependency)

HF2 removes generator backrefs, which takes generators out of the consensus
path entirely. That shrinks the atomic unit to **coin set + peak** and makes
the minimal API in [Target design](target.md) valid. Steps 3–5 are
deliberately sequenced after HF2 because:

- Pre-HF2, `BlockStoreProtocol` must carry generator access
  (`get_generator` / `get_generators_at`) and `add_full_block` stays fused —
  machinery HF2 deletes. Building migration infrastructure around it would
  be over-investment in code with a known expiry date.
- Post-HF2, "give me block N" ambiguity during reorgs disappears from
  generator handling, and block records become repair-at-startup rather than
  part of the atomic transaction.

HF2 is active priority 1 upstream, so this is a wait on a moving train, not
a parked dependency.

## Step 3 (post-HF2) — peak + block-record migration

Move peak tracking from `BlockStore` into the coin store's atomic unit;
`_reconsider_peak` becomes one transaction against one store. Block records
and `in_main_chain` become derivable/repair-at-startup. This fixes the
transaction-boundary design *while still on SQLite*, so it's testable
against the existing engine before any RocksDB code exists.

*Acceptance:* crash-consistency test at a reorg boundary; peak and coin set
can never disagree.
*Rollback:* revert to the BlockStore peak; the SQLite schema keeps both
paths workable during transition.

## Step 4 (post-HF2) — RocksDB backend behind the landed protocols

Implement `CoinStoreProtocol` (including snapshot) on RocksDB via rocksdict,
reusing the db_v3 key schema and its fsck consistency checker as prior art —
but with coins, undo records, and peak in **one** RocksDB from day one.
Initially spent-coins-kept (`rocks` variant) for a smaller diff against
known-good semantics. Behind a config flag; SQLite remains the default.

*Acceptance:* full mainnet sync completes; fsck passes; reorg tests pass;
benchmark confirms the spike's curve on a real node.
*Rollback:* config flag back to SQLite; the SQLite store is untouched.

## Step 5 (post-HF2) — rocks-lean semantics

Flip to delete-spent-coins with full records in the undo log, prunable
beyond reorg depth. Requires the singleton fast-forward open question
([Target design](target.md)) to be resolved, since spent-coin lookups leave
the consensus store.

*Acceptance:* same as step 4 plus resurrection correctness under deep-reorg
tests; explorer/mempool queries have a working home.
*Rollback:* the `rocks` (spent-kept) backend from step 4 remains available.

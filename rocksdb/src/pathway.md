**[agent draft — I haven't reviewed this text yet]**

# Pathway

Baby steps. Each one is a small, reviewable PR; the system is fully
consistent after every step, and each carries a visible payoff on its own —
a tach exception deleted, raw SQL removed, a latent bug closed. Nothing
lands that isn't independently valuable.

*(Rewritten 2026-07-27 from the original five-step outline. Revised again
2026-11-03 after an independent review: Stage 3 now starts with the
consensus transition API instead of a schema ladder; a SQLite chain index
ships only together with a reader that needs it; the HF2 wait point is gone;
the ExplorerStore (now S16) comes before lean mode (now S17); and the
default backend migration is offline. Stages 0-2 are unchanged.)*

## Stage 0 — write the invariants down first (done)

**S0 — [Atomicity invariants](invariants.md)**, published 2026-07-23. The
audit of every write-transaction site in the node: exactly one cross-store
write transaction exists, and the target design dissolves it. Two earlier
attempts in this direction (#19799, #19949) stalled in review on exactly
this question, so this time the answer is published before any code that
depends on it. Migration PRs cite the page instead of re-arguing atomicity
in-thread.

## Stage 1 — hygiene and the tach exception (done)

Five PRs, no behavior change, each independently worth having. All five
merged 2026-07-27/28.

- **S1 — #21165.** The node's only raw-SQL read above the store layer (a
  `hints` query in `full_node_api`) becomes a `HintStore` method. No SQL
  above the stores.
- **S2 — #21166.** Compactification's direct `db_wrapper.writer()` call
  moves behind a `BlockStore` method. After this, no caller above the
  stores reaches for the shared transaction layer except `add_block`.
- **S3 — #21167.** `BlockHeightMapProtocol`, unused since it landed a year
  ago (#19798), deleted. Dead protocols are review liabilities.
- **S4 — #21168.** `CoinStoreProtocol` slimmed from 15 methods to the 6
  consensus actually uses. The non-consensus methods stay on the concrete
  `CoinStore`, which RPC and wallet code imports anyway. (The slimming
  promised in #19741, thirteen months late.)
- **S5 — #21169.** `BlockStoreProtocol` covering what `Blockchain` actually
  uses; `Blockchain` type-narrowed against it; the
  `chia.consensus -> chia.full_node` tach exception deleted. Same content
  as #19799 — this time with the atomicity answer (S0) published in
  advance, and `transaction()` typed as a real context manager instead of
  `Any`.

*Rollback:* pure types and method moves — each reverts independently.

## Stage 2 — read views (in progress)

Purely additive: new read APIs, no writer changes. Worth being precise
about what these add. Today the node opens a consistent read transaction in
exactly one place; every other read is an unsynchronized point read, and
the peer/RPC handlers cope with reorgs mid-read by hand (see
[invariants](invariants.md)). Consistent reads are being *added*, not
preserved.

- **S6 — #21180 (merged 2026-09-16).** `snapshot()` on `CoinStore`: an async context
  manager yielding a consistent view — peak plus batch coin reads that are
  guaranteed to agree. SQLite implements it as a read transaction; RocksDB
  will use a Snapshot; tests get a frozen dict.
- **S7 — [#21179](https://github.com/Chia-Network/chia-blockchain/pull/21179) (in review).** `ChainView`: chain-index reads pinned to one
  block, so "the block at height N" stops silently depending on whatever
  the peak happens to be. First consumer is weight-proof creation, whose
  height walks interleave ~14 chain-index reads with database awaits and
  were unprotected against mid-walk reorgs — a proof could silently mix
  blocks from two chains. It now pins once per walk and aborts loudly if
  the pinned block is reorged away.
- **S8 — not started.** Migrate the peer/RPC handlers off the hand-rolled
  re-check idiom (read, then verify `height_to_hash(h)` still matches,
  bail if not — ~8 sites) onto pinned views, deleting the repeated
  reorg-detection boilerplate.

One more thing Stage 2 owes S13: `ChainView`'s pin check is atomic today
only because it reads the synchronous in-RAM map. A bounded cache with
async misses breaks that argument. S13 needs async, batched views over a
snapshot first, so that an old pin that falls out of the window isn't
mistaken for a stale one.

*Acceptance:* new tests for snapshot/view semantics; zero behavior change
for existing callers.
*Rollback:* additive — revert.

## Stage 3 — the consensus transition, on SQLite

The atomicity contract ([invariants](invariants.md)) is the hard part of the
whole migration. It's testable against the existing engine before any
RocksDB code exists. So the *logical* boundary comes first, over today's
tables. Moving tables comes later, and only where a reader needs the new
layout.

- **S9 — [#21455](https://github.com/Chia-Network/chia-blockchain/pull/21455)
  (draft, parked).** A `chain_index(height → header_hash)` table,
  dual-written with `in_main_chain` in the same transaction. Correct by
  construction, but it has no readers, and on an upgraded node it only
  covers heights from the upgrade on. It ships only together with S11's
  fill, a consumer, and S11's schema gate. Otherwise it's a fourth copy of
  the same data.
- **S10. The transition API over the existing tables.**
  `apply_transition(expected_peak, fork_height, blocks)` on the consensus
  store: rewind plus every replacement block's coin changes, flags and
  peak, inside one transaction, with read-your-writes. Blocks without
  transactions are included. No schema change: it maps onto today's
  `coin_record`, flags and `current_peak`, and the block-blob write stays
  in the same SQLite transaction. The types, checks, commit point, how RAM
  state is published, cancellation and tests are on
  [S10 transition contract](s10-contract.md). `_reconsider_peak` and the simulator's `revert_block_height`
  both call it, so no caller above the stores sequences five store calls
  inside a transaction any more. Payoff: the contract becomes an interface
  with tests (exceptions, cancellation, a branch that depends on its own
  earlier blocks), and the RocksDB backend later implements the same
  interface. `CoinStoreProtocol` is renamed `ConsensusStore` here, where the
  name becomes true.
- **S11. The chain index becomes the authority (only if a reader earns
  it).** The readers that could earn it are S13's bounded height map and
  faster startup. If neither is happening, skip this step: S15 builds the
  chain index during conversion. If it happens:
  - *Fill* existing history by copying `in_main_chain` rows in height
    batches, one snapshot per batch. Check continuity in memory with
    `prev_hash`, including across batch boundaries, the way BlockHeightMap
    already loads windows (`block_height_map.py:190-235`). Commit each batch
    with the low-water mark, rechecking `low` at commit time
    ([Migrations](migration.md#s11-filling-the-chain-index-in-the-node)). The flags are the source because they
    commit atomically with the peak and the coins. The `height-to-hash` file
    is a lazily flushed cache, and startup only checks it back to the
    nearest sub-epoch summary, so damage further back can survive. It can
    speed things up, but only if verified. A per-block `prev_hash` walk is
    the repair fallback, not the default: it costs ~8.6M awaited lookups.
  - *Move every flag reader* to the chain index: the BlockHeightMap
    rebuild, `get_full_blocks_at` / `get_generators_at`, the record and
    block range reads, the startup record cache, the compaction queries and
    counts, and `chia db validate` (`block_store.py:316-598`,
    `db_validate_func.py:149-170`).
  - *Retire* the `height-to-hash` file, and stop writing `in_main_chain`.
  - *Downgrade policy.* S9 and S11 ship in the same release, behind one
    schema version bump that older binaries refuse to open. A binary that
    ignores `chain_index` would otherwise leave it stale while later code
    trusts it. That makes the release one-way, so it carries the same
    "back up first" note as `chia db upgrade`.
- **S12.** `DBWrapper2` becomes store-internal. After S10, `add_block`
  still opens the outer transaction so the blob write and the transition
  commit together. That goes away when S15 separates the archive write
  (with its retry path), so S12 lands with S15. It's a consequence, not its
  own project.
- **S13.** `BlockHeightMap` becomes a bounded cache (~10k heights). This is
  memory work, and it can be done on its own once S11 and Stage 2's async
  views exist. Re-audit first: the [audit](blockheightmap-audit.md) has
  corrections (the MMR's full-history walk is reachable from header
  validation, and a bound relative to the block being validated isn't a
  bound relative to the peak during a deep fork). Decide
  `BlockchainMMRManager`'s persistence (nodes and frontier on disk) in the
  same PR.

*Acceptance (per rung):* crash and cancellation tests at reorg boundaries;
peak, chain index and coin set never disagree.
*Rollback:* S10 and S12 revert cleanly. The S9 + S11 release is one-way,
behind its schema gate.

## Stage 4 — backends

There is no HF2 wait point any more. HF2 removes generator refs from *new*
blocks, but historical blocks keep theirs, and a ref resolves against that
block's own chain. So the branch-aware lookup stays. Separating it from the
consensus store doesn't need the fork.

- **S14.** The archive is addressed by hash. Historical generator lookups
  resolve height → hash against the chain being validated, then fetch the
  blob by hash. The fork-aware path stays.
- **S15. The RocksDB backend, spent coins kept.** Before it's built, fix
  the spike: its SQLite backend commits undo and peak outside the coin
  transaction, and its lean rewind resurrects ephemeral coins
  ([Benchmarks](benchmarks.md#caveats-found-in-review)). Then measure the
  real goal (HDD, small RAM, full-node replay with fork validation). The
  backend ships with:
  - offline, resumable conversion into a new destination, validated
    (coins, every height, peak, archive coverage, undo) before a durable
    backend-selection manifest switches the node over;
  - fsck and a rollback tool;
  - a disk preflight that budgets source + destination + WAL + compaction
    space;
  - the original SQLite file kept as a named checkpoint with a documented
    way back.

  Config-selected; SQLite stays the default at first.
  [Migrations](migration.md) has the conversion design. What serves
  puzzle-hash queries and singleton lineage on a RocksDB node is
  [open question B](target.md#explorer-queries-move-out): ship S16 with
  S15, or make S15 a restricted validator mode until S16 lands.
- **S16. ExplorerStore.** Puzzle-hash and parent indexes and hints move to
  a separate, deletable database with its own published peak and a rebuild
  path from the archive. Singleton lineage gets a home here or in the
  mempool. It needs a catch-up and reorg-replay contract, and a way for
  consumers that need an exact peak to wait or get a "behind" answer.
- **S17. Lean mode.** Spent coins are deleted, with full records kept in
  the undo log. Gated on the fork-relative read
  ([Target design](target.md#fork-validation-needs-historical-coin-state))
  being built and tested, and on every per-height history reader in
  consensus (the MMR rebuild, header filters) being routed
  ([Target design](target.md#historical-coin-data-that-consensus-reads)). Undo pruning is gated separately, on defined and
  exercised behavior for a reorg deeper than the retained window.

*Acceptance:* full mainnet sync on the new backend; fsck passes; reorg and
competing-fork tests pass; the spike's curve is confirmed on a real node.
*Rollback:* switch back through the manifest to the SQLite checkpoint and
replay forward. Once lean mode has pruned history, it can't be rolled back
by flipping config. Going back means a rebuild.

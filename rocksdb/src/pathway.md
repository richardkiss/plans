# Pathway

Baby steps. Each one is a small, reviewable PR; the system is fully
consistent after every step, and each carries a visible payoff on its own —
a tach exception deleted, raw SQL removed, a latent bug closed. Nothing
lands that isn't independently valuable.

*(Rewritten 2026-07-27. The original five-step outline on this page turned
into the staged ladder below once the work started landing as real PRs.
The biggest structural change: the peak/chain-index migration now happens
**before** HF2, on SQLite — only the physical split and the new backends
wait for the fork.)*

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
approved 2026-07-27; merged except #21166, which is waiting on the merge
pipeline.

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

- **S6 — #21180 (draft).** `snapshot()` on `CoinStore`: an async context
  manager yielding a consistent view — peak plus batch coin reads that are
  guaranteed to agree. SQLite implements it as a read transaction; RocksDB
  will use a Snapshot; tests get a frozen dict.
- **S7 — #21179 (draft).** `ChainView`: chain-index reads pinned to one
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

*Acceptance:* new tests for snapshot/view semantics; zero behavior change
for existing callers.
*Rollback:* additive — revert.

## Stage 3 — peak + chain index become consensus state (dual-write ladder)

The heart of the migration, still entirely on SQLite: the
transaction-boundary fix is testable against the existing engine before any
RocksDB code exists. Each rung keeps the old and new structures consistent
in the *same* transaction, so every intermediate commit is a working node,
and the old structure stays maintained until a later rung retires it.

- **S9.** A new `height → header_hash` chain-index table, written inside
  the existing `add_block` transaction. No readers yet; consistent by
  construction.
- **S10.** Switch readers — the height map's load path, `height_to_hash`
  resolution, S7's views — to the chain index.
- **S11.** Move peak and chain-index writes into the coin store's write
  scope: `new_block` / `rollback_to_block` update coins, chain index, and
  peak atomically. **This is the step that dissolves the node's one
  cross-store transaction** ([invariants](invariants.md)). The block-blob
  write moves ahead of the consensus commit — a crash in between leaves an
  orphaned blob, harmless and re-fetchable. `CoinStoreProtocol` is renamed
  `ConsensusStore` here, where the name becomes true.
- **S12.** `DBWrapper2` becomes store-internal. After S11 nothing above the
  stores opens transactions, so the per-store context managers are the only
  surface. It lives on quietly inside the SQLite implementations — removed
  from the interface not because it's bad, but because it's unreferenced.
- **S13.** `BlockHeightMap` re-scoped, not removed: it becomes the
  store-owned in-RAM cache of the chain index, bounded to a ~10k-height
  window near the validation frontier (~400 KB, constant forever) instead
  of the full 275 MB that grows with the chain. An audit of every
  synchronous caller says the bound is safe — the deepest look-back on a
  sync path is provably ≤ 5,121 blocks below the block being validated;
  everything that reads deeper is already async and moves to
  snapshot/view reads. (The audit will get its own page.)

*Acceptance (per rung):* crash-consistency at reorg boundaries; peak, chain
index, and coin set can never disagree.
*Rollback:* each rung is a dual-write — revert the rung, the previous
structure is still there and still correct.

## Wait point — HF2 lands (external dependency)

HF2 removes generator backrefs, which takes generators out of the consensus
path entirely. Pre-HF2, the consensus surface has to carry
`get_generator` / `get_generators_at` — machinery HF2 deletes — and I don't
want to build backend infrastructure around code with a known expiry date.
HF2 is active priority 1 upstream, so this is waiting on a moving train,
not a parked dependency.

## Stage 4 (post-HF2) — physical split and backends

- **S14.** Drop `get_generator` / `get_generators_at` from the consensus
  surface once inter-block references are disallowed.
- **S15.** The RocksDB backend, config-selected; SQLite stays the default
  initially. Ships in the same phase, not after: an fsck/rollback tool
  (data-integrity tooling arrives *with* the backend), a metadata key
  family (schema version, network id, lean/full flag, earliest undo
  height), the slimmed coin record, per-height chain-index keys. The
  migration tool is a one-pass read of a single SQLite snapshot as two
  height-sorted streams.
- **S16.** Lean mode — delete spent coins, keep full records in the undo
  log — plus a bounded undo window GC'd by a compaction filter. Needs the
  singleton fast-forward question ([Target design](target.md)) answered
  first, and a blessed `MAX_REORG_DEPTH` constant.
- **S17.** The explorer split: puzzle-hash/parent indexes and hints move to
  a separate, *deletable* database with a backfill tool — deletable means
  rebuildable, and rebuilding is also the migration path. Engine decided by
  its own benchmark; SQLite is genuinely fine at secondary-index queries.
  The archive (full block blobs) stays SQLite either way.

*Acceptance:* full mainnet sync on the new backend; fsck passes; reorg
tests pass; the spike's curve confirmed on a real node.
*Rollback:* config flag back to SQLite; the SQLite store is untouched. Lean
mode rolls back to the spent-kept backend.

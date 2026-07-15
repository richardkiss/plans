# Status

Living page. Dated entries, newest first.

## 2026-07-15 — Spike complete; Phase 1 in progress

- **Benchmark spike complete.** Four backends replayed to height 1M on
  representative weak hardware (HDD, 15 GB RAM). Headline: ~40x engine gap,
  widening; rocks-lean wins every axis. Full results and caveats in
  [Benchmarks](benchmarks.md). Spike repo is local
  (`~/projects/coin-store-spike`), not yet published.
- **Reorg archeology complete.** All-of-mainnet orphan analysis supports
  delete-spent-coins; see the [decision log](decisions.md).
- **Phase 1 (protocols) in progress.** The `store-split` worktree has the
  protocol slimming and type-narrowing done, but is ~492 commits behind
  main, and `snapshot()` / `CoinStoreSnapshot` — the key abstraction — is
  **not yet implemented**. No PR opened yet; stale upstream PRs #20566 and
  #20443 are still open and meant to be superseded.
- **HF2** (the external dependency gating steps 3–5 of the
  [pathway](pathway.md)) is active priority 1 upstream.

## 2026-07-14 — Direction set

- Goal confirmed: land RocksDB upstream (phased, reviewable), not just a
  local performance proof.
- Binding decision made (rocksdict); two-DB split rejected; benchmark spike
  spec'd and launched. See the [decision log](decisions.md).

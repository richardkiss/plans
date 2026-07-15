# Status

Living page. Dated entries, newest first.

## 2026-07-15 — Spike complete; Phase 1 in progress

- Full-mainnet benchmark underway. Extraction of all 8.5M blocks (~408M
  coins) is running now; the ~2-day four-backend replay follows. This will
  replace the "stops at height 1M" caveat with measured numbers.
- Correction: [host-1](bench-host.md) is NVMe-backed, not HDD as first
  believed (the VM reports its disk as rotational). Benchmark caveats
  updated; the spinning-disk story needs a real-HDD run.
- Benchmark spike complete. Four backends replayed to height 1M on
  [host-1](bench-host.md) (NVMe-backed VM, 15 GB RAM).
  Headline: ~40x engine gap, widening; `rocks-lean` wins every axis. Full
  results and caveats in [Benchmarks](benchmarks.md). The harness is in this
  repo
  ([`rocksdb/spike/`](https://github.com/richardkiss/plans/tree/main/rocksdb/spike))
  and runs in one line via `uvx`.
- Reorg archeology complete. All-of-mainnet orphan analysis supports
  delete-spent-coins; see the [decision log](decisions.md).
- Phase 1 (protocols) in progress. The `store-split` worktree has the
  protocol slimming and type-narrowing done, but it's ~492 commits behind
  main, and `snapshot()` / `CoinStoreSnapshot` — the key abstraction — is
  *not* implemented yet. No PR opened; the stale upstream PRs #20566 and
  #20443 are still open and meant to be superseded.
- HF2 (the external dependency gating steps 3–5 of the
  [pathway](pathway.md)) is active priority 1 upstream.

## 2026-07-14 — Direction set

- Goal confirmed: land RocksDB upstream (phased, reviewable), not just a
  local performance proof.
- Binding decision made (rocksdict); two-DB split rejected; benchmark spike
  spec'd and launched. See the [decision log](decisions.md).

# Status

Living page. Dated entries, newest first.

## 2026-07-21 — Full-mainnet replay complete

- The full-history replay (heights 0–8.58M, 408.55M coins) finished for
  three backends: `rocks` 14.8 h, `rocks-lean` 12.9 h, `sqlite-consensus`
  101.1 h. Full-chain gap is ~7–8x on wall time, ~10x in the dust
  segments. Results, plots, and caveats in [Benchmarks](benchmarks.md).
- `sqlite-full` was skipped deliberately — extrapolation put it over a
  week, and `sqlite-consensus` already bounds SQLite's best case.
- MultiGet batching of spent-coin lookups measured against a sequential
  baseline: 1.16x wall-clock to height 4.9M. Real but modest.
- Next experiment: multi-block WriteBatch (`SPIKE_BATCH_BLOCKS=N`) —
  apply N blocks as one atomic batch. Amortizes per-block overhead, feeds
  MultiGet bigger key sets, and cross-block ephemeral coins (created and
  spent inside the window) never touch the DB. Undo info stays per-block,
  so rewind granularity is unchanged. Rocks backends re-run starting now.

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

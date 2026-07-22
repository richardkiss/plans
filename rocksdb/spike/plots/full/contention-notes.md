# External load during full-mainnet replay runs (host-1)

Host-1 is a Proxmox VM; other containers on the same physical host can
contend for CPU. Disk bandwidth contention believed low in all cases
(per Richard). Log of known contention windows, for interpreting CSVs:

- **2026-07-15 ~23:52–00:08 (approx)** — batched `rocks` run, early
  heights (~0–1.5M): a high-CPU process in another container was running
  (Richard, 00:08). Early-segment comparisons vs the sequential baseline
  understate the batching speedup.
- **2026-07-16 23:35, ongoing** — text-model inference in another
  container (Richard, 23:35). Active during `rocks-lean` from at least
  height ~3.9M (58% of extract) onward; unknown exact start. CPU
  contention possible; disk bandwidth impact should be small.
  Affects: tail of rocks-lean, and possibly the sqlite runs that follow
  (will update when the inference stops).

Sequential-baseline files (pre-batching partial rocks run, cancelled at
height 4.9M): `sequential-baseline/`.

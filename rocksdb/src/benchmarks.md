# Benchmarks

I extracted every transaction block's coin deltas from a synced mainnet
database, then replayed all of mainnet history through a uniform
per-block API against each backend, measuring throughput as the database
grows.

## Method

1. **Extract.** One linear scan of the `coin_record` table in a synced
   215 GB mainnet SQLite DB (every row carries `confirmed_index` and
   `spent_index`, so no blockchain walk is needed), bucketed by height into
   a stream of per-block deltas: timestamp, created coins, spent coins.
   Serialized as length-prefixed binary, zstd-compressed — 22 GB for the
   full chain.
2. **Replay.** Each backend implements the same minimal API
   (`process_spends` / `rewind_to_block` / `get_coin_records` / `peak`).
   Replay applies each block: multi-get the removals first (as real
   validation does), then apply creations, spends, undo record, and peak in
   one batch. Write-only replay would flatter both engines and miss the
   index-read costs, so reads are in the loop on purpose.
3. **Measure.** Wall time, blocks/sec, and on-disk size logged every 10k
   heights.

The input is all of mainnet — height 8,581,859: 3.09M transaction
blocks, 408.55M coins created, 163.51M spent.

## Backends

| Backend | Description |
|---|---|
| `sqlite-full` | Production schema, all four indexes |
| `sqlite-consensus` | Same schema minus the explorer indexes (puzzle_hash, coin_parent) |
| `rocks` | RocksDB; spent coins kept and flagged (db_v3-style schema, peak in the same WriteBatch) |
| `rocks-lean` | RocksDB; spent coins *deleted*, full spent records preserved in a per-block undo log |

## Results

Full mainnet history, heights 0 through 8,581,859. I didn't run
`sqlite-full` to full height: a 1M-capped run measured it ~1.5x slower
than `sqlite-consensus` (14,786 s vs 9,930 s), so the full run would have
taken over a week, and it wouldn't show anything `sqlite-consensus`
doesn't.

| Backend | Total time | Avg blk/s | Dust segment blk/s | End-of-run blk/s | Final size | Live records |
|---|---|---|---|---|---|---|
| sqlite-consensus | 363,954 s (101.1 h) | 23.6 | 4.7 | ~15 | 99.5 GB | 408.55M |
| rocks | 53,277 s (14.8 h) | 161 | 46 | ~69 | 68.3 GB | 408.55M |
| rocks-lean | 46,619 s (12.9 h) | 184 | 48 | ~93 | 54.2 GB | 245.04M |

"Dust segment" is the mean over heights 1.6–2.1M, the first dust-storm
region, where blocks carry thousands of tiny coins.

![Full-history throughput vs block height](assets/throughput-full.png)

![Full-history database size growth](assets/db_size-full.png)

## What the curves say

Over the whole chain the gap is ~7–8x on total wall time (6.8x vs `rocks`,
7.8x vs `rocks-lean`); the instantaneous gap runs far higher in the easy
segments (~40x at height 1M). The gap is biggest in the dust segments
(~1.6–2.1M and ~4.6–5.1M), where SQLite drops to 1–5 blk/s and RocksDB
holds 25–50. In wall-clock terms: full replay is a half-day on RocksDB
and four days plus on SQLite.

The win is the engine — LSM writes and bloom-filtered reads vs B-tree
maintenance and scattered page reads — not the schema. Dropping the
explorer indexes only bought SQLite ~1.5x in the 1M-capped run, and both
of those indexes key on effectively random 32-byte hashes, the worst case
for a B-tree's page cache. That's what justifies an engine migration
rather than just a schema diet.

`rocks-lean` wins on every axis: fastest, smallest on disk, and its
working set is the UTXO set (245M records) rather than every coin ever
created (409M). One surprise: its on-disk size *dropped* during replay at
times — deleting spent coins lets compaction reclaim space, something the
flag-in-place schemas never do.

For perspective: even degraded SQLite (~15 blk/s) beats mainnet's real
block production rate (0.31 blk/s). The payoff here is initial-sync speed
and headroom on weak hardware, not survival.

### Batched vs sequential spent-coin lookups

The `rocks` run also tested a change: batch the spent-coin lookups through
RocksDB MultiGet instead of one `db.get` per coin. I have a sequential
baseline to height 4.9M (that run died on a file descriptor limit, since
fixed). To the same height, batched took 23,711 s against sequential's
27,494 s — 1.16x. The per-interval medians are closer to 1.02–1.04x, and
CPU contention from another VM muddies the early segments (logged in
[`plots/full/contention-notes.md`](https://github.com/richardkiss/plans/tree/main/rocksdb/spike/plots/full)).
Real but modest — batching did not explain the block-time variance I hoped
it would.

### Multi-block WriteBatch: doesn't pay

Next I tried applying 100 blocks per atomic WriteBatch
(`SPIKE_BATCH_BLOCKS=100`): one commit and one MultiGet per window, and
coins created and spent inside the window never touch the DB at all in
`rocks-lean`. Undo info stays per-block, so rewind granularity is
unchanged. I expected this to shine in the dust segments. It didn't:

| Backend | Unbatched | Batched (N=100) | Delta |
|---|---|---|---|
| rocks | 53,277 s | 57,693 s | 8% slower |
| rocks-lean | 46,619 s | 48,004 s | 3% slower |

Final heights, sizes, and coin counts match exactly. The segment breakdown
is the opposite of what I expected: batching is a small win on early small
blocks (+1–6%) and a loss in the dust segments (−8 to −16%), on both
backends. My reading: dust blocks are already huge, so per-block
WriteBatches were already big enough to amortize the overhead; grouping
100 of them just builds giant batches and lookup windows that cost more
than the saved commits. Batching per-key lookups (MultiGet, above) pays;
batching already-large transactions does not. The batched-run CSVs are in
`plots/full/` as `*-batch100.csv`, and the mode stays in the harness
behind `SPIKE_BATCH_BLOCKS` if you want to try other window sizes.

The full-run CSVs, enrichment output, and the sequential baseline live in
[`rocksdb/spike/plots/full/`](https://github.com/richardkiss/plans/tree/main/rocksdb/spike/plots/full).

## Reproducing

The complete harness lives in this site's repo, under
[`rocksdb/spike/`](https://github.com/richardkiss/plans/tree/main/rocksdb/spike):
`extract.py`, `coin_store.py` (all four backends), `replay.py`, unit tests,
and the per-run CSVs behind the plots. Everything runs with
[uv](https://docs.astral.sh/uv/) straight from GitHub — each command below
downloads the code, builds a venv, and runs, in one line.

Unit tests (all four backends; no mainnet DB needed, ~seconds):

```bash
uvx --from "git+https://github.com/richardkiss/plans#subdirectory=rocksdb/spike" spike-test
```

Full benchmark (needs a synced mainnet `blockchain_v2_mainnet.sqlite`,
~215 GB, read-only; default location `~/.chia/mainnet/db/`, override with
`CHIA_MAINNET_DB`):

```bash
SPIKE="git+https://github.com/richardkiss/plans#subdirectory=rocksdb/spike"
uvx --from "$SPIKE" spike-extract 1000000   # -> extract.dat.zst (~1.5 GB with the 1M cap)
uvx --from "$SPIKE" spike-replay            # all four backends; ~7.5 h on the reference host
```

Capped at 1M, the whole thing runs overnight. The full-history numbers
mean dropping the cap: a 22 GB extract, ~100 GB peak DB size, and about
five days of replay (`SPIKE_BACKENDS=rocks,rocks-lean` if you only want
the half-day RocksDB legs).

`spike-replay` writes throughput CSVs and plots to `plots/` and a summary
to `report.md`. Each backend's DB is deleted before the next one starts.

The published numbers come from **host-1** — a VM with NVMe-backed storage
and 15 GB RAM. Full specs and notes for comparing runs across machines:
[Benchmark hosts](bench-host.md). I plan to try a slower box later; runs on
other machines should be tagged with their host name.

## Caveats

Read these before quoting the numbers.

- **The host is NVMe-backed, not a spinning disk.** NVMe's cheap random
  reads flatter SQLite, so the gap on a real HDD should be *larger* — but
  that's extrapolation until a real-HDD run exists. Details:
  [Benchmark hosts](bench-host.md).
- **`sqlite-full` has no full-history run.** The production schema was
  measured only in the 1M-capped run, at ~1.5x slower than
  `sqlite-consensus`. For a full-history estimate, apply that ratio.
- **Other jobs shared the CPU during parts of the run.** This host is a
  VM; a text-model inference job in another container overlapped the tail
  of `rocks-lean` and part of the SQLite run, and another job overlapped
  the early batched-`rocks` segment. Disk bandwidth impact should be
  small. Windows are logged in
  [`plots/full/contention-notes.md`](https://github.com/richardkiss/plans/tree/main/rocksdb/spike/plots/full),
  so don't lean on fine-grained cross-run comparisons (especially the
  batched-vs-sequential early segments). The headline gaps are far larger
  than anything contention could explain.
- **Storage layer only.** Real sync also pays signature verification and
  CLVM execution. This isolates the coin-store cost; it does *not* predict
  end-to-end sync speedup.
- **Neither engine fsyncs per block, on purpose.** RocksDB runs its
  default WAL with sync=false; SQLite runs WAL + synchronous=NORMAL. The
  comparison is fair, and for the target design no-fsync is correct by
  construction: the peak update rides in the same atomic WriteBatch as
  the coins, so the peak key *is* the commit record, and a crash recovers
  to a clean "as of height H" state (see [Target design](target.md)). No
  strict-durability variant was measured; it isn't the design point.
- **The DBs are much bigger than RAM** (54–100 GB vs 15 GB), so the
  numbers include real cache-miss behavior. There's no measurement on a
  badly RAM-starved box (say, a 2 GB cgroup); I'd expect that to hurt
  SQLite more.
- **Rewind under replay was not exercised** in the timed runs; rollback
  correctness is covered by unit tests only.

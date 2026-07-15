# coin-store-spike

Benchmark harness comparing four coin-store backends (SQLite full schema,
SQLite consensus-only, RocksDB, RocksDB-lean) by replaying real Chia mainnet
coin history. Results and analysis:
[richardkiss.github.io/plans/rocksdb/benchmarks.html](https://richardkiss.github.io/plans/rocksdb/benchmarks.html).

Everything runs via [uv](https://docs.astral.sh/uv/) straight from GitHub —
no clone or venv setup needed:

```bash
SPIKE="git+https://github.com/richardkiss/plans#subdirectory=rocksdb/spike"

# unit tests (no mainnet DB needed, ~seconds)
uvx --from "$SPIKE" spike-test

# extract per-block coin deltas from a synced mainnet DB (~1.5 GB output)
# reads ~/.chia/mainnet/db/blockchain_v2_mainnet.sqlite (override: CHIA_MAINNET_DB)
uvx --from "$SPIKE" spike-extract 1000000   # optional height cap

# replay all four backends against extract.dat.zst in the cwd (hours)
uvx --from "$SPIKE" spike-replay
```

`spike-replay` writes throughput CSVs and plots to `plots/`, and a summary
report to `report.md` (override with `SPIKE_REPORT_FILE`). Progress can be
mirrored to a heartbeat file via `SPIKE_HEARTBEAT_FILE`.

Mind the disk budget: the four databases peak at ~8 GB each; they are
deleted after each backend finishes.

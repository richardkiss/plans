# Problem

Chia's full node keeps its coin set (the UTXO-like state that consensus
validates against) in SQLite, in a single `coin_record` table with four
indexes. Two of those indexes — puzzle hash and parent coin — exist for
wallet and explorer queries, not for consensus. Every block the node
processes pays the B-tree maintenance cost for all of them.

## The store degrades superlinearly

As the database grows, SQLite's per-block cost climbs. In a replay benchmark
of real mainnet history (details in [Benchmarks](benchmarks.md)), the
production schema slowed from ~727 blk/s at height 10k to ~8 blk/s
approaching height 1M — a **4.3x degradation over the measured window**,
still steepening, and the benchmark only covers 17.5% of current mainnet
history. B-tree index maintenance costs grow with tree depth; there is no
reason to expect the curve to flatten.

## Explorer indexes live in the consensus path

The puzzle-hash and parent-coin indexes serve RPC and wallet-protocol
queries. They are pure overhead for block validation, yet they are
maintained inside the same transaction that advances the chain. Dropping
them helps (about 1.5–2x in the benchmark) but does not fix the shape of
the curve — the degradation is mostly the engine, not the schema.

## What "too slow" actually means

Mainnet produces about **0.31 blocks per second**. Even a badly degraded
SQLite store keeps up with that at steady state. The pain is elsewhere:

- **Initial sync**: at single-digit blocks per second, syncing from genesis
  takes weeks on modest hardware, and gets worse every year as the chain
  grows.
- **Weak hardware**: the goal is that slow machines and spinning disks stay
  in sync *comfortably*, with headroom — not that a well-provisioned SSD box
  scrapes by. On an HDD, scattered B-tree point reads during validation are
  exactly the worst case.

## Goal

A consensus coin store whose per-block cost stays roughly flat as the chain
grows, that is friendly to spinning disks and small RAM, and that carries no
explorer baggage in the consensus path. The evidence that a RocksDB-backed
store achieves this is in [Benchmarks](benchmarks.md); the design is in
[Target design](target.md).

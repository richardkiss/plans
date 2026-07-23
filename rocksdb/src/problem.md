# Problem

Chia's full node keeps the coin set — the UTXO-like state that consensus
validates against — in SQLite, in one `coin_record` table with four indexes.
Two of those (puzzle hash and parent coin) exist for wallet and explorer
queries, not for consensus. Every block pays the B-tree maintenance cost for
all four anyway.

## The store degrades superlinearly

SQLite's per-block cost climbs as the database grows. Replaying all of
mainnet history (details in [Benchmarks](benchmarks.md)), SQLite — even
with the explorer indexes already dropped — slowed from thousands of
blocks per second in the early chain to ~15 at the tip, and to 1–5 in the
dust-storm segments. The full replay took 101 hours against RocksDB's 13
to 15. B-tree index maintenance grows with tree depth; the measured curve
never flattens.

## Explorer indexes live in the consensus path

The puzzle-hash and parent-coin indexes serve RPC and wallet-protocol
queries. Block validation never reads them, but it maintains them inside the
same transaction that advances the chain. Dropping them helps (about 1.5–2x
in the benchmark) but doesn't fix the shape of the curve — the problem is
mostly the engine, not the schema.

## What "too slow" actually means

Mainnet produces about 0.31 blocks per second. Even badly degraded SQLite
keeps up with that at steady state. The pain is elsewhere.

Initial sync: at single-digit blocks per second, syncing from genesis takes
weeks on modest hardware, and it gets worse every year as the chain grows.

Weak hardware: I want slow machines and spinning disks to stay in sync
*comfortably*, with headroom — not for a well-provisioned SSD box to scrape
by. On an HDD, the scattered B-tree point reads during validation are close
to the worst case.

## Goal

A consensus coin store whose per-block cost stays roughly flat as the chain
grows, that's friendly to spinning disks and small RAM, and that carries no
explorer baggage in the consensus path. The evidence that a RocksDB-backed
store gets there is in [Benchmarks](benchmarks.md); the design is in
[Target design](target.md).

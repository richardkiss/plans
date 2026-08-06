# Status

Living page. Dated entries, newest first.

## 2026-08-05 — Design and pathway published; nothing implemented

- Pre-implementation. The design session and the code audit are done; the
  audit is pinned to `chia-blockchain` @ `a8b1b58554` and `chia_rs` @
  `a77cec97` ([code-surface map](code-map.md)). No code has been written.
- Next step: R1, the read-only mainnet resolver prototype. It needs no
  node changes and produces the numbers
  [Measurements](measurements.md) is waiting for — including whether
  in-node fast forward is load-bearing on mainnet at all today.
- Three findings from the audit qualify the original design
  ([Evidence](evidence.md)): the FF-downgrade rule is not deletable until
  node-FF itself is removed (F1); the timelock-equality rules also block
  compositions (F2); the all-FF-bundle rule carries an anti-replay
  property the annex spec must preserve (F3).
- This plan answers the open question in the
  [RocksDB plan's target design](../rocksdb/target.html):
  `get_unspent_lineage_info_for_puzzle_hash` gets deleted (N3c), not
  rehomed.

# Decision log

Dated decisions with the reasoning behind them, then the questions that
are still open. Everything below came out of one design session plus a
code audit, both 2026-08-05.

## 2026-08-05 — Generic over privileged

The node stops knowing about singletons entirely. No blessed puzzle
pattern gets in-node machinery; anything a singleton needs beyond plain
mempool admission is user-space. This was the original objection to
in-node FF, and GFF resolves it in the strongest form. Settled.

## 2026-08-05 — Throughput over latency

The goal for a busy singleton is cycling more than once per block via
chained compositions from a resolver's backlog — not minimizing the
latency of one pending spend. In-node FF's latency advantage is irrelevant
to that goal, and the node is the wrong place for backlog and aggregation
policy. Settled.

## 2026-08-05 — Resolver incentives: the deployer, no protocol payment

The contract deployer wants their singleton's throughput maximized —
they're the natural resolver operator. The role stays permissionless
because the annex is gossiped rather than served from known endpoints.
No fee redirection, no protocol-level payment. Settled.

## 2026-08-05 — The annex is necessary, not optional

Born-stale spends die with `DOUBLE_SPEND` at first contact today unless
node-FF rescues them (`mempool_manager.py:244-245`). Remove node-FF
without a propagation path for conflicting spends and those spends are
simply dead. The annex is that path, and it's the *only* one post-GFF. It
also stays cheap: it's an evolution of the existing `ConflictTxCache`
plus a relay-policy change, not a new subsystem. Settled.

(Naming: "annex", chosen over "contention pool". The rename of
`ConflictTxCache` waits until N1b, when relay makes the name true.)

## 2026-08-05 — `can_replace` gets restated in economic terms

Replacement decisions key on fee and cost deltas with an opportunity-cost
term, not on per-item fee-rate comparison — see
[Target design](target.md) for the rule. The FF-downgrade rule is deleted
at N3 (not amended, and not deleted earlier — F1). The design test for
every mempool heuristic: compatible iff it never treats a spend's coin ID
as its identity. Settled as direction; the exact formulation is P1's
design note.

## Open questions

Marked open because they are.

- **Annex parameters**: N (the recent-spend window), per-coin k, the
  global cost cap, relay priority. Need simulation or testnet, and the
  interaction with the lean store's undo window
  ([RocksDB plan](../rocksdb/pathway.html), S16).
- **`marginal_FPC` estimation** at the block boundary for P1 — and what
  replaces the timelock-equality tests (F2), if anything. Design work,
  with arvidn.
- **N1b rate-limit and DoS review** — annex items are by definition
  conflicting; today's rate limits assume mempool-admissible traffic.
  Needs arvidn.
- **History of the FF-downgrade rule** — my F1 threat reconstruction is
  from code; the original PR discussion should be checked before the P1
  design note asserts it.
- **External consumers of the FF flags** from
  `get_conditions_from_spendbundle` (wallet SDKs, dexes) — check before
  N4's optional hygiene strip.
- **Resolver bridging adequacy at low old-node fractions** — gossip
  subgraph connectivity during the transition. Needs network topology
  simulation, not code reading.
- **Interim wallet UX** — auto-resend re-signs nothing; a wallet-side
  re-sign-on-`DOUBLE_SPEND` improvement is worth having but not required
  by the pathway's gating.

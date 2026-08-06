# Target design

Three pieces: an end-state node that knows nothing about singletons, an
annex pool that propagates conflicting spends, and user-space resolvers
that do the rebasing. Plus one policy change that stands on its own: a
`can_replace` rule stated in economic terms.

## End-state node

No eligibility flags consumed, no lineage tracking, no rebase-at-build, no
new-peak refresh, no puzzle-hash lookup in the consensus store. A spend of
an already-moved singleton is just a double spend. The mempool's only
singleton-adjacent behavior is the annex, and the annex isn't
singleton-specific — it holds *any* conflicting spend that meets
admission.

The design test that got us here: a mempool rule is GFF-compatible iff it
never treats a spend's coin ID as its identity. Rules keyed on economic
content — fees, costs, value spent — survive rebasing; rules keyed on coin
IDs or eligibility flags break, and each turned out to be deletable or
restatable ([code-surface map](code-map.md)).

## The annex

A second, bounded pool holding spend bundles that conflict with the
mempool or with recently-spent coins. Gossiped — possibly at lower
priority — so conflicting spends reliably reach resolvers without any
known endpoint. That's what keeps the resolver role permissionless.

The node already holds these spends locally in `ConflictTxCache`
(`pending_tx_cache.py:13`) but never relays them (only SUCCESS
transactions are broadcast, `full_node.py:2841-2844`). The annex is mostly
a relay policy plus admission rules on an existing structure.

Admission — the DoS defense:

- Every removal in the bundle must be currently unspent OR spent within
  the last N blocks. That's exactly what a lean node with a bounded undo
  window can answer, and it gives automatic TTL — entries age out with the
  window.
- Per-conflicting-coin top-k by declared fee rate, replacing today's FIFO
  eviction (`pending_tx_cache.py:35-38`).
- A global cost cap.

Declared fees are an ordering heuristic, not a payment; spam is priced by
signature construction. The parameters — N, k, the cost cap, relay
priority — are open ([decision log](decisions.md)).

The annex is necessary, not optional. "Born-stale" spends — submitted
after the singleton already moved on-chain — die today with `DOUBLE_SPEND`
at first contact unless node-FF rescues them
(`mempool_manager.py:244-245`). Post-GFF, only the annex propagates them.

## Resolvers

A resolver watches gossip and the annex, rebases stale singleton spends
onto the latest on-chain version (keyless — see [Evidence](evidence.md)),
composes chained chunks, and rebroadcasts. The resolver keeps the deep
backlog; the mempool holds only the active chunk per singleton.

Incentive: the contract deployer wants their singleton's throughput
maximized. They're the natural operator; no protocol payment needed. The
role stays permissionless — anyone can run one — because the annex is
gossiped, not served from a known endpoint.

Composition mechanics: one composition is one atomic mempool item, so the
resolver sizes chunks to block space. Within a chunk, chain order doesn't
affect the fee rate (the bundle is atomic) — "aggregate by highest fee
rate" means *selecting* the top-fee spends into the current chunk, not
ordering them. One accepted wart: replacing a high-fee-rate lone incumbent
with a composition dilutes the average (that's just arithmetic); the
resolver defers that material to the next block.

## `can_replace`, restated economically

Two rules in today's replacement logic block compositions outright
([Evidence](evidence.md), F1 and the fee-rate gate): the fee-rate
comparison rejects any extension with below-average material even when
total fees rise, and the FF-downgrade rule blocks every chained
replacement regardless of fees. The agreed direction:

```text
fee_new - fee_old > marginal_FPC * max(0, cost_new - cost_old) + MIN_INCREASE
```

with `marginal_FPC = 0` when the mempool doesn't fill a block — Chia's
normal regime, where this degenerates to a total-fee rule. The superset
rule and the absolute anti-churn increment survive as-is. How to estimate
`marginal_FPC` at the block boundary, and what happens to the
timelock-equality tests (F2), are open — that's the P1 design note's job.

This change is defensible without GFF: the current gate rejects
economically rational replacements for plain transactions too.

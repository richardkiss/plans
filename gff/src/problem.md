# Problem

Chia's full node knows about singletons. The mempool computes a
fast-forward eligibility flag for every spend, looks up singleton lineage
on admission, rebases stale spends at block-build time, and refreshes
pending items on every new peak. All of this exists so that a pending
spend of a singleton survives the singleton moving on-chain underneath it.

Generalized fast forward (GFF) removes all of it. Fast-forward becomes a
user-space job — permissionless *resolvers* that rebase stale spends and
rebroadcast them — plus one node-side addition: an *annex*, a second,
bounded pool that relays the conflicting spends resolvers need to see. No
fork; all mempool policy.

Three reasons to do this.

## A blessed puzzle pattern

The node's consensus-adjacent code is keyed to one puzzle shape. Singletons
get eligibility flags, lineage tracking, and rebase machinery that no other
puzzle gets. That was my original objection to in-node fast forward, and
GFF resolves it in the strongest form: the end-state node knows nothing
about singletons — no eligibility, no lineage, no FF.

## It blocks the lean coin store

`get_unspent_lineage_info_for_puzzle_hash` is the only puzzle-hash-keyed
query the mempool makes against the consensus coin store. In the
[RocksDB migration plan](../rocksdb/target.html), that query is the one
open question — it has no home in a pure coin-ID KV store and threatens to
force a lineage index onto the consensus store. GFF deletes the query
([pathway](pathway.md), N3c), and the pressure disappears.

## It optimizes the wrong thing

In-node FF keeps *one* pending spend alive per singleton — a latency
optimization. The actual goal for busy singletons is throughput: cycling a
singleton more than once per block by chaining spends into compositions
(e.g. 15 spends cached, a block takes 5, re-aggregate the remaining 10).
The node can't do that job well — it would need a deep per-singleton
backlog and aggregation policy inside the mempool. A resolver keeps the
backlog and sizes chunks to block space; the mempool holds one active
chunk per singleton. In-node FF's local latency advantage is irrelevant to
this.

## Goal

A node with no singleton knowledge; a bounded annex pool that propagates
conflicting spends so resolvers reliably see them; resolvers anyone can
run, with the rebase primitives kept as library surface in `chia_rs`. The
argument that third parties can rebase without keys is in
[Evidence](evidence.md); the design is in [Target design](target.md); the
staging — including why removal must come *last* — is in
[Pathway](pathway.md).

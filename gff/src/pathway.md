# Pathway

Same discipline as the [RocksDB pathway](../rocksdb/pathway.html): every
step is one reviewable unit, the system is fully working after each, each
carries a standalone payoff, and the removal step ships *last*, gated on
the machinery that replaces it. Three stages: **R** (resolver, zero node
changes), **P** (standalone policy), **N** (node changes). Six node-side
PRs in total: P1, N1a, N1b, N3a, N3b, N3c.

## Stage R — resolver first, zero node changes (start now)

**R1 — read-only resolver prototype against mainnet.** Watch tx gossip or
poll a local node's mempool RPC, detect FF-eligible spends
(`supports_fast_forward` is already exported — `wheel/src/api.rs:415,805`),
track singleton movement, and measure what
[Measurements](measurements.md) lists. Prereqs: none. Blast radius: zero.
Rollback: stop the process.

**R2 — active resolver, rebase-only.** Same tool, now resubmitting rebased
bundles (`fast_forward_singleton`, `wheel/src/api.rs:448,806`; keyless per
`eligible_coin_spends.py:271`). No chaining, no node changes. Verified
against current admission code:

- On nodes still holding the original item: the rebased bundle's
  *companion* spends hard-conflict, the superset rule rejects it
  (`mempool_manager.py:1093-1096`), it lands in the conflict cache.
  Harmless — the original is still there and gets rebased at build time.
- On nodes that dropped the original (born-stale case): it's a plain valid
  bundle and is accepted. **This makes the resolver the compatibility
  bridge for the whole mixed-version window** — it converts spends alive
  only in old-node mempools into fresh bundles new nodes accept.

R2 proves keyless rebasing on live traffic and resolver operating cost. It
cannot prove chaining (blocked by F1 and the fee-rate gate) or annex
behavior.

## Stage P — standalone policy (ordinary release, defensible without GFF)

**PR 1 of 6: P1 — `can_replace` restated in economic terms.** Replace the
fee-rate gate (`mempool_manager.py:1106-1113`) with the fee/cost-delta
rule from [Target design](target.md). Keep the superset rule and
`MEMPOOL_MIN_FEE_INCREASE`. The same design note decides the fate of the
timelock-equality tests (F2) — my proposal: keep them for now, they're a
separate anti-pinning measure; revisit when compositions are real.

- Standalone payoff: today's gate rejects economically rational
  replacements for *plain* transactions — any aggregation extending an
  incumbent with below-average material is refused even though total fees
  rise. Defensible with concrete examples, no GFF required.
- Who notices: wallets doing fee bumps, positively. Mempools diverge
  across versions during rollout — already normal (cf. the 2.4.3
  cost-tolerance shim, `full_node.py:2819-2827`).
- Rollback: pure node-local policy; revert in a point release.
- Do NOT bundle the FF-downgrade rule change here (F1 —
  [Evidence](evidence.md)).

**P2 — explicitly not doing it.** A narrow amendment of the FF-downgrade
rule to permit chaining pre-annex is possible (key it per singleton puzzle
hash instead of per coin ID), but it's subtle, and chaining without annex
re-injection re-opens F1's pinning economics. Chaining arrives with
Stage N. Recorded as a decision, not a phase.

## Stage N — node changes (ordered; each gated on the previous)

**PR 2 of 6: N1a — annex admission, node-local, no relay yet.** Evolve
`ConflictTxCache` in place (`pending_tx_cache.py:13-47`; wired at
`mempool_manager.py:349,582-586,1012-1013`): every removal currently
unspent or spent within the last N blocks; per-conflicting-coin top-k by
declared fee rate (replacing FIFO eviction, `pending_tx_cache.py:35-38`);
global cost cap. **No rename in this PR** — it's still a local retry
cache, and the name should stay true. Standalone payoff: a smarter retry
cache with bounded, principled eviction. No protocol change. Rollback:
revert.

**PR 3 of 6: N1b — annex relay.** The relay-policy question, informed by
code:

- *Piggyback* on the existing `NewTransaction` announce/request flow. Old
  nodes interoperate for free: announcements carry (id, cost, fee)
  (`full_node.py:2858-2862`); old nodes fetch if the fee clears
  (`full_node_api.py:242`); a born-stale bundle they fetch gets FF-rescued
  into their mempool; a hard-conflicting one lands in their conflict cache,
  silently and harmlessly. No ban risk — bans fire only on zero cost or
  cost/fee mismatch (`full_node_api.py:216-240`). One required change:
  `request_transaction` serves only from the mempool
  (`full_node_api.py:292-294`) and must also look up the annex.
- *New message types* must be capability-gated; precedent exists
  (`shared_protocol.py:30-49`).
- Recommendation: piggyback for announce/fetch, a capability bit only if
  annex-specific messages (bulk sync) prove necessary. Rate-limit
  implications need arvidn — annex items are by definition conflicting,
  and today's rate limits assume mempool-admissible traffic.

**The rename lands here**: once the pool is relayed, "annex" becomes true
and `ConflictTxCache` takes the new name in the same PR.

Rollback: revert the release — relay behavior is node-local policy, and
the N1a cache remains either way.

**N2 — resolvers commonly run.** An operational milestone, not a PR. The
reference resolver (R2 hardened, chaining enabled once N1 and P1 are live)
is published; deployers operate their own per the incentive argument.
**Gate for N3: R1's metrics show resolver coverage of observed FF
traffic.** Not calendar time — measured coverage.

**N3 — remove node-FF.** Ships only after N1b and N2. Born-stale spends
die without node-FF unless the annex propagates them, so sequencing is the
whole game here. Three PRs, each leaving a working node:

- **PR 4 of 6: N3a** — stop setting `latest_singleton_lineage` (delete
  `mempool_manager.py:652-662,676`). Everything downstream keys off that
  field, so FF behavior ends network-visibly here: born-stale spends →
  `DOUBLE_SPEND` → annex; FF items evict on singleton movement → annex.
- **PR 5 of 6: N3b** — delete the now-dead code: `check_removals` FF
  branches (`244-245,252-276`), the all-FF-bundle rule (`679-683`), the
  `can_replace` FF set and downgrade rule (`1081,1097-1098,1146-1150` —
  F1 satisfied: it dies *with* node-FF, not before), the new-peak refresh
  (`845-959` plus `LineageInfoCache` at `63-78`), FF indexing in
  `mempool.py` (`472-478,492-494`), `SingletonFastForward` and its
  block-build call sites (`eligible_coin_spends.py:22-106,170-287`;
  `mempool.py:586,624,695,723`), and the plumbing.
- **PR 6 of 6: N3c** — delete
  `CoinStore.get_unspent_lineage_info_for_puzzle_hash`
  (`coin_store.py:650-674`), its protocol method
  (`coin_store_protocol.py:136-139`), and the
  `coin_record_ph_ff_unspent_idx` partial index (plus the
  `spent_index = -1` unspent-marking convention it rides on, if nothing
  else uses it). **This is the step that unblocks the lean coin store** —
  the only puzzle-hash-keyed consensus query the mempool makes, gone. It
  should land before S16 in the [RocksDB pathway](../rocksdb/pathway.html).

Blast radius: `get_mempool_items_by_coin_name` shifts behavior (FF items
are currently indexed under the *latest* singleton coin ID,
`mempool.py:472-478`); `test_singleton_fast_forward.py` and the FF
portions of `test_mempool_manager.py` / `spend_sim.py:172` get deleted or
repointed at the resolver. Rollback: revert the release — no data
migration anywhere in N3a/b, and N3c's index drop is re-creatable
(`CREATE INDEX IF NOT EXISTS`).

**N4 — chia_rs: move, don't delete.** `fast_forward_singleton`
(`fast_forward.rs:59-150`), `supports_fast_forward`, and the
`ELIGIBLE_FOR_FF` computation are exactly the resolver's toolkit — they
stay in `chia_rs` as library surface. Node-side, the flag just stops being
consumed. Optional later hygiene: strip the FF bits from `MempoolVisitor`
(`spendbundle_conditions.rs:118,139`) once no external consumer wants
them — consensus never used them (`run_block_generator.rs:132,302` uses
`EmptyVisitor`). Fuzzers and tools stay with the library.

## Sequencing

R1 → R2 anytime, now. P1 anytime, now. All independent of each other.
Then: N1a → N1b → (N2 gate) → N3a → N3b → N3c → N4. P1 is a prerequisite
for useful chaining (N2), not for N1.

## Mixed-version behavior

"Old" = pre-N3 (node-FF live). "New" = post-N3.

| Event | Old node | New node, pre-N1 | New node, post-N1 (annex) | Net effect |
|---|---|---|---|---|
| Fresh FF spend, singleton unspent | mempool, relayed | mempool, relayed (it's a normal spend) | same | no difference until the singleton moves |
| Singleton moves while spend pending | item rebased in place, kept | item evicted; gone | item evicted → annex, relayed | confirmation falls on old farmers + resolvers; degrades with old-farmer share only if resolvers are absent |
| Born-stale submission | accepted via FF rescue, relayed as a normal tx | `DOUBLE_SPEND`, dropped, **not relayed** | annexed, relayed | pre-N1, these propagate only across the old-node subgraph — new nodes are holes in the gossip mesh for them |
| Resolver's rebased resubmission (R2) | companion-spend conflict → superset rejects → conflict cache (harmless; original retained) | accepted as a plain bundle | accepted | the resolver bridges old-only spends into new nodes — the designed rescue path, both directions |
| Annex announce via piggyback (N1b) | ordinary `NewTransaction`; fetches if fee clears; born-stale → FF-rescued; hard conflict → its conflict cache; no bans | n/a | annex-to-annex relay | piggyback is fully old-compatible — the strongest argument against new message types for the base flow |
| Two FF spends, same singleton | coexist, chained at build | second is a plain conflict → conflict cache | second → annex | today's chaining throughput needs old builders; post-GFF it's the resolver's job |

Interim UX: wallet auto-resend exists but resends the original *stale*
bundle (`wallet_node.py:449,515-547`), so it only helps where node-FF or
the annex catches it. Wallets hold keys and could re-sign on a
`DOUBLE_SPEND` ack — worth doing, but not required if N1b and N2 precede
N3, which this pathway enforces.

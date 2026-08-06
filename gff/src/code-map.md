# Code-surface map

Every FF-touching surface, verified live at the pinned tips —
`chia-blockchain` @ `a8b1b58554ec7e0aeeae92173ba8427204350d4e`,
`chia_rs` @ `a77cec97025566a5162465f66f2c6f9cea4e29a7`. **None of it is
dead code today**; everything below is live, which is why removal has to
be staged rather than swept.

Classification: **[now]** — changeable in an ordinary release today;
**[annex]** — only after annex relay exists (N1b); **[resolver]** — only
after resolvers are commonly run (N2); **[keep]** — moves to the resolver
library, not deleted. Phase labels refer to the [pathway](pathway.md).

## chia-blockchain @ a8b1b58

| Surface | Location | Class |
|---|---|---|
| Fee-rate (FPC) replacement gate | `mempool_manager.py:1106-1113` | [now] restate economically (P1) |
| Min-fee-increase, superset, timelock-equality rules | `mempool_manager.py:1093-1096,1115-1144` | [now] keep; timelock rule needs a P1 decision (F2) |
| FF-downgrade rule | `mempool_manager.py:1146-1150` | [annex+resolver] dies with N3b, **not** deletable earlier (F1) |
| Dedup-downgrade rule | `mempool_manager.py:1152-1154` | untouched by GFF (dedup stays) |
| Born-stale DOUBLE_SPEND exemption | `mempool_manager.py:244-245` | [annex+resolver] N3b |
| FF/dedup conflict classification | `mempool_manager.py:252-288` | FF branches N3b |
| Lineage lookup on add + `latest_singleton_lineage` | `mempool_manager.py:652-676` | [annex+resolver] N3a — the single switch everything keys off |
| All-FF-bundle rejection | `mempool_manager.py:679-683` | N3b; anti-replay property must survive in the annex spec (F3) |
| New-peak FF refresh (`deferred_ff_items`, `spends_to_update`, `LineageInfoCache`) | `mempool_manager.py:63-78,845-959` | N3b |
| `ConflictTxCache` | `pending_tx_cache.py:13-47`; wired `mempool_manager.py:349,582-586,1012-1013` | [now→annex] becomes the annex (N1a) |
| FF index under latest coin ID + bulk reindex | `mempool.py:472-478,492-494` | N3b |
| `SingletonFastForward` rebase-at-build | `eligible_coin_spends.py:170-287` (helpers `22-106`); call sites `mempool.py:586,624,695,723` | N3b (logic reborn inside the resolver) |
| Signature reuse in rebase (the keyless proof) | `eligible_coin_spends.py:271` | evidence; moves with the resolver |
| `get_unspent_lineage_info_for_puzzle_hash` | `coin_store.py:650-674`; protocol `coin_store_protocol.py:136-139`; wiring `full_node.py:285` | N3c — kills the lineage-index pressure |
| `coin_record_ph_ff_unspent_idx` partial index + `spent_index=-1` convention | `coin_store.py:32-34,74-92,124-128` | N3c |
| Relay policy (SUCCESS-only broadcast) | `full_node.py:2841-2844,2854-2864` | [annex] N1b changes this for annex items |
| `request_transaction` mempool-only lookup | `full_node_api.py:292-294` | [annex] N1b extends to annex |
| Tx announce ban rules (cost=0, cost/fee mismatch) | `full_node_api.py:216-240` | constraint on N1b piggyback — verified compatible |
| Capability gating precedent | `shared_protocol.py:30-49` | template if annex-specific messages prove necessary |
| Wallet auto-resend | `wallet_node.py:449,515-547` | interim UX; resends the *stale* bundle — only helps via old-node FF or the annex |
| Tests / sim | `test_singleton_fast_forward.py`, `test_mempool_manager.py`, `spend_sim.py:172` | N3 cleanup; some repoint at the resolver |

## chia_rs @ a77cec9

| Surface | Location | Class |
|---|---|---|
| `ELIGIBLE_FOR_FF` flag + rationale comment | `conditions.rs:48-62` | [keep] resolver library |
| Eligibility visitor (odd amount, condition clears, output check) | `conditions.rs:88-193` | [keep]; node stops consuming at N3 |
| Bundle-level clears (`ASSERT_CONCURRENT_SPEND`, ephemeral chaining) | `conditions.rs:195-244` | [keep] — the F1 attack lever and the chained-replacement blocker |
| `fast_forward_singleton` rebase | `fast_forward.rs:59-150` | [keep] — the resolver's core primitive |
| Python exports | `wheel/src/api.rs:415,448,805-806`; stubs `chia_rs.pyi:24-25` | [keep] |
| `MempoolVisitor` wiring (mempool-only; consensus uses `EmptyVisitor`) | `spendbundle_conditions.rs:118,139`; `run_block_generator.rs:132,302` | proves FF flags were never consensus; optional strip post-N3 |
| Fuzzers / tools / tests | `fuzz_targets/fast-forward.rs`, `chia-tools/src/bin/fast-forward-spend.rs`, `gen-corpus.rs`, `tests/test_fast_forward.py` | [keep] with the library |

A citation-drift note: the original design discussion cited line numbers
against a different tip. Everything was re-verified against the pinned
commits above; those are the numbers used throughout this book.

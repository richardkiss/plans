# Evidence

Everything here is from reading code, pinned to two tips:
`chia-blockchain` @ `a8b1b58554` (delta vs. origin/main touches no FF
logic) and `chia_rs` @ `a77cec97`. Line numbers below are against those
commits. The full inventory is in the [code-surface map](code-map.md);
what's *not* known yet — mainnet traffic reality — is in
[Measurements](measurements.md).

## How fast forward works today

The eligibility flag is computed in `chia_rs`: a spend is `ELIGIBLE_FOR_FF`
only if it's a singleton-shaped spend (odd amount, odd `CREATE_COIN`
output) that avoids every condition committing to its exact coin — no
`ASSERT_MY_COIN_ID`, no parent-committing `AGG_SIG`s, no timelocks, no
announcements (`conditions.rs:48-62`, visitor at `88-193`).

The node consumes that flag in four places:

1. **On admission**, the mempool looks up the singleton's latest unspent
   version by puzzle hash and stores it as `latest_singleton_lineage` on
   the item (`mempool_manager.py:652-676`). This is the single switch
   everything downstream keys off — `supports_fast_forward` is derived
   from it (`mempool_item.py:36-38`).
2. **Born-stale rescue**: a spend of a singleton that already moved
   on-chain would be `DOUBLE_SPEND`; FF spends are exempted
   (`mempool_manager.py:244-245`) exactly because the lineage lookup
   succeeded.
3. **At block build**, `SingletonFastForward` rebases stale spends onto
   the latest version (`eligible_coin_spends.py:170-287`).
4. **On every new peak**, pending FF items are refreshed to track
   singleton movement (`mempool_manager.py:845-959`).

The lineage lookup lands in the coin store as
`get_unspent_lineage_info_for_puzzle_hash` (`coin_store.py:650-674`),
riding a partial index (`coin_record_ph_ff_unspent_idx`).

None of this is consensus. `MempoolVisitor` computes the FF flags;
consensus validation uses `EmptyVisitor` and never sees them
(`spendbundle_conditions.rs:118,139`; `run_block_generator.rs:132,302`).
That's what makes the whole plan a mempool-policy change — no fork.

## Why third parties can rebase without keys

The eligibility rules exclude everything the signature commits to. So the
rebase only has to patch the solution's lineage proof
(`fast_forward.rs:139-141`); the signature is reused as-is
(`eligible_coin_spends.py:271`). Anyone holding a gossiped FF bundle can
rebase it onto the current singleton version without any keys. The
resolver role needs no privilege — it's permissionless by construction,
not by policy.

## F1 — the FF-downgrade rule is not deletable early

`can_replace` refuses to replace an FF item with a non-FF spend of the
same coin (`mempool_manager.py:1146-1150`). I hoped this rule was
deletable. It isn't, while node-FF is the recovery path — the threat it
guards against is real. Worked example, all against current code:

1. A victim gossips an FF bundle spending singleton coin `S`.
2. An attacker aggregates the victim's bundle with one attacker spend
   carrying `ASSERT_CONCURRENT_SPEND` on `S`. That condition clears the
   victim spend's FF flag at the bundle level (`conditions.rs:210-216`).
3. The attacker bumps the fee. The result spends every coin of the
   original, so it passes the superset rule (`mempool_manager.py:1093-1096`)
   and the fee gates — without the downgrade rule it would replace the
   victim's FF item.
4. The singleton next moves on-chain. The pinning bundle now double-spends
   `S` and dies. **The attacker's fee bump is never paid** — pinning is
   free, repeatable, and the victim's only recovery is wallet auto-resend
   (default ~60 min, `wallet_node.py:449,515-547`) plus the conflict-cache
   retry.

Under GFF the resolver re-injects the spend next block, so pinning
degrades to a one-block delay and the rule's purpose disappears. And
mechanically it becomes dead code the moment node-FF is removed, because
nothing sets `latest_singleton_lineage` anymore. Conclusion: delete it in
the same release that removes node-FF (N3), not before. Until then,
chained replacements stay blocked — which the
[pathway](pathway.md) is shaped around.

## F2 — the timelock-equality rules also block compositions

`can_replace` requires the new item's effective `assert_height` /
`assert_before_height` / `assert_before_seconds` to *exactly equal* the
aggregate over the items it replaces (`mempool_manager.py:1121-1144`). A
composition that adds material carrying any height or seconds assertion
changes the item-level aggregate and is rejected regardless of fees.
FF-eligible spends can't carry timelocks themselves
(`conditions.rs:106-119`) — but their non-FF companions can. So the
economic restatement of `can_replace` (P1) has to decide what replaces
this equality test; it's not just the fee-rate gate that binds
compositions.

## F3 — the all-FF-bundle rule is load-bearing beyond eviction

"FF spends only allowed when bundled with other, non-FF spends"
(`mempool_manager.py:679-683`) is also what makes a third party's rebased
*duplicate* of a live bundle hard-conflict via its companion spends,
instead of chaining onto the original and double-executing the user's
intent. Any annex admission spec and any resolver re-aggregation rule
needs an equivalent anti-replay property. (Replay of a *confirmed*
zero-signature FF spend is possible today by anyone and is the puzzle
designer's problem — not a GFF regression — but the annex must not become
an amplifier for it.)

## Two confirmations that help the transition

Two independent FF spends of the same singleton do *not* conflict in the
mempool — FF+FF falls through every conflict branch in `check_removals`
(`mempool_manager.py:268-288`) — and get chained at block building.

And only SUCCESS transactions are relayed (`full_node.py:2841-2844`), so
today's `ConflictTxCache` (`pending_tx_cache.py:13`) — which already holds
exactly the conflicting spends the annex wants — is invisible to the
network. The annex is mostly a relay-policy change plus admission rules on
an existing structure.

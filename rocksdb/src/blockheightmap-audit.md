**[agent draft — I haven't reviewed this text yet]**

# BlockHeightMap audit

S13 re-scopes `BlockHeightMap` from a full-history in-RAM cache (~275 MB,
growing forever) to a ~10k-height window pinned near the validation
frontier (~400 KB, constant forever). That's only safe if every caller on
the synchronous block-validation path stays within the window. This page
is the audit: every call site of `Blockchain.get_hash()` /
`height_to_hash()` / `contains_height()` (and the one place that reaches
past `Blockchain` to call `BlockHeightMap` directly), classified by
sync/async and by maximum lookback depth below the validation frontier.
Verified against `main` at `6c193275d` (2026-09-09).

> **Status (2026-11-03): partly superseded; re-audit before S13.** The
> difficulty-adjustment bound below still stands. Two conclusions don't,
> and they're rewritten in place below: the MMR walk is reachable from
> header validation, and the bound is relative to the block being
> validated, not to the peak.
> Line numbers are against `main` at `6c193275d`.

## The claim

> Every synchronous caller looks back at most 5,121 blocks
> (`BLOCKS_CACHE_SIZE = 4608 + 128*4 = 5120`, plus one for an inclusive
> range) from the validation frontier. Everything that reads deeper is
> already async and can move to snapshot/view reads.

**Verdict: not proven as stated.** Difficulty adjustment, the deepest
*bounded* walk, stays within `BLOCKS_CACHE_SIZE` of the block being
validated. One synchronous path isn't bounded that way:

- The MMR manager walks every height from `HARD_FORK2_HEIGHT` when it has
  no usable fork context (`blockchain_mmr.py:86-96`). That walk is
  reachable from header validation (`blockchain.py:1109-1116`,
  `block_header_validation.py:1103-1110`), not only from startup. Newer
  trees reuse MMR state instead (`blockchain_mmr.py:96-124` on the S9
  branch). Re-check current main before calling it an upstream bug.
And the bound is relative to the block being validated. During a deep fork
that block can be far below the peak, so a window has to follow the
validation frontier, or be preloaded for the fork, rather than be anchored
at the peak.

## Summary table

| Call site | Sync/async | Max lookback | Safe for 10k window? |
|---|---|---|---|
| `difficulty_adjustment._get_blocks_at_height` (`difficulty_adjustment.py:29-30,36`) | sync (block validation) | ≤ ~4,737 blocks, proven below | yes |
| `add_block`'s fork-point assert (`blockchain.py:373`) | sync (block validation) | 1 block (always `block.height - 1`) | yes |
| `_load_chain_from_store` fast-forward check (`full_node.py:1737`) | sync-adjacent (batch validation loop) | 0 (always the block just added) | yes |
| Backtrack short-sync fork search (`full_node.py:822`) | async, but self-bounded | ≤ 5 blocks (`while curr_height > peak_height - 5`) | yes |
| `lookup_block_generators` main-chain check (`blockchain.py:1077-1079`) | async function, sync map lookup | 1: checks the validated block's *parent* (`get_block_generator.py:26` passes `block.prev_header_hash`); ref'd heights go through `get_generators_at` (`:1103-1106`), a DB read | yes |
| **MMR rebuild** (`Blockchain.create`, `blockchain.py:193`; and from header validation via `blockchain_mmr.py:86-96`) | startup **and** validation | **unbounded** — full range from `HARD_FORK2_HEIGHT` | **no — needs a direct chain-index read or persisted MMR state** |
| Weight-proof creation (`weight_proof.py:134,214,227,266,331,352,466,497,517`) | async | unbounded — walks from genesis/SES boundaries to peak | no (already the named first consumer of S7's `ChainView`) |
| RPC handlers (`full_node_rpc_api.py:53,74,235,434,480,576,869,914`) | async | unbounded — client-specified heights | no (candidates for S8) |
| Peer-protocol handlers (`full_node_api.py:459,463,487,495,513,1412,1469,1476,1491,1560,1574,1671,2081,2127,2162`) | async | unbounded — peer-specified heights, or the hand-rolled reorg re-check idiom | no (the named S8 migration targets) |
| Batch/backtrack sync bookkeeping (`full_node.py:692,712,1328,1339,3578`) | async | unbounded — `full_node.py:3578` picks *random* historical heights for bluebox compaction | no (S8) |
| Post-reorg fork lookup (`full_node.py:2076`) | async, right after `add_block` returns | reorg depth — not formally bounded (see caveat below) | conditionally — see below |
| Wallet (`wallet_node.py:1787-1788`, `wallet_blockchain.py:233`) | async | n/a | **out of scope** — separate class, own cache, no `BlockHeightMap` |

## Sync call sites — the validation-critical path

### Difficulty adjustment: the load-bearing bound

`get_next_sub_slot_iters_and_difficulty` is called from block header
validation on every block that starts a new sub-slot. It's the one path
whose lookback depth is *structural* rather than incidental, and it's the
reason `BLOCKS_CACHE_SIZE` has the value it has.

The `height_to_hash`/`contains_height` calls live in
`_get_blocks_at_height` (`difficulty_adjustment.py:29-30,36`), reached from
`_get_second_to_last_transaction_block_in_previous_epoch`
(`difficulty_adjustment.py:51-100`), reached from `_get_next_difficulty` /
`_get_next_sub_slot_iters` (`difficulty_adjustment.py:220-350`).

Depth derivation, working from `prev_b` (the block being validated,
effectively the frontier):

- `height_in_next_epoch = prev_b.height + 2*MAX_SUB_SLOT_BLOCKS + MIN_BLOCKS_PER_CHALLENGE_BLOCK + 5`
  (`difficulty_adjustment.py:75-76`) — with mainnet constants
  (`MAX_SUB_SLOT_BLOCKS=128`, `MIN_BLOCKS_PER_CHALLENGE_BLOCK=16`), that's
  `prev_b.height + 277`, and it's guaranteed to fall in the epoch *after*
  `prev_b`'s own epoch (comment at `difficulty_adjustment.py:75`).
- `height_epoch_surpass` (`:77`) rounds that down to a multiple of
  `EPOCH_BLOCKS` (4608) — since it's guaranteed to be in the next epoch,
  this lands in `(prev_b.height, prev_b.height + 277]`.
- `height_prev_epoch_surpass = height_epoch_surpass - EPOCH_BLOCKS` (`:80`)
  — so in `(prev_b.height - 4608, prev_b.height - 4331]`.
- The lookup window fetched by `_get_blocks_at_height` starts at
  `height_prev_epoch_surpass - MAX_SUB_SLOT_BLOCKS - 1` (`:100`), i.e. at
  worst `prev_b.height - 4608 - 129 = prev_b.height - 4737`.

So the deepest height ever resolved through `height_to_hash`/
`contains_height` on this path is **`prev_b.height - 4737`** — comfortably
inside `BLOCKS_CACHE_SIZE = 5120`, with 383 blocks of headroom. This is
almost certainly where `BLOCKS_CACHE_SIZE` itself comes from: it's sized
as `EPOCH_BLOCKS + 128*4` specifically to cover this walk plus slack, not
some independently-chosen number.

(`_get_blocks_at_height` also has a slow path, `difficulty_adjustment.py:40-48`,
that walks `block_record`/`prev_hash` one at a time when the fast
`height_to_hash` path misses. That path doesn't call any of the three
audited methods — it's out of scope by the letter of the claim — but it's
worth noting it exists for fork contexts where the height map's
main-chain answer doesn't apply.)

### Where the "5,121" comes from

`BLOCKS_CACHE_SIZE` itself is 5120, not 5121. The extra one is very likely
the inclusive range in `warmup` (`blockchain.py:863-875`) and
`clean_block_record`/`clean_block_records` (`blockchain.py:877-912`):
`get_block_records_in_range(peak - BLOCKS_CACHE_SIZE, peak)` keeps
`BLOCKS_CACHE_SIZE + 1 = 5121` heights alive (both endpoints inclusive).
Either framing supports the claim — 4,737 measured depth fits under both
5,120 and 5,121 with margin.

### The fork-point assert in `add_block`

`blockchain.py:373` — `self.height_to_hash(uint32(fork_info.fork_height))
== block.prev_header_hash` — looks alarming out of context, because
`fork_info.fork_height` can in principle be arbitrarily far below the
peak (it's fixed at the start of a batch sync, e.g. `full_node.py:715`,
and stays fixed while `fork_info.peak_height` advances one block per
`add_block` call during the batch). But this assert only executes in the
branch where `fork_info.peak_height == fork_info.fork_height`
(`blockchain.py:365`) — i.e. exactly when the fork hasn't advanced past
its starting point yet, which is exactly the first block after the fork
point, where `fork_info.fork_height == block.height - 1`. The height
resolved is always the immediate parent of the block being validated.
Depth: 1.

### The batch-validation fast-forward check

`full_node.py:1737` (the batch-validation helper) compares `self.blockchain.height_to_hash(block.height) ==
header_hash` for a block already seen once before, to decide whether it's
still on the main chain. The guard immediately above it
(`full_node.py:1731-1732`, `if block.height <= fork_info.peak_height:
continue`) means this only runs for `block.height` strictly past the
current fork frontier — i.e. it's the block currently at the head of the
batch being validated, not a historical lookup. Depth: 0 (it's asking
about the frontier itself, not something below it).

### Generator resolution during validation

`lookup_block_generators` (`blockchain.py:1052-1106`) resolves generator
refs during transaction validation. Its one `height_to_hash` call
(`:1079`) checks whether the header hash it was given is on the main
chain. The normal caller passes the validated block's parent
(`get_block_generator.py:26`), so the depth is 1. The ref'd heights
themselves are read from the database by `get_generators_at`
(`:1103-1106`), not from the height map. If the parent *isn't* on the main
chain (a fork), resolution falls through to `lookup_fork_chain`
(`find_fork_point.py`), which walks `block_record`/`prev_hash`. The lookup
stays branch-aware after HF2 (see
[Target design](target.md#historical-generator-lookup-stays-branch-aware)).

## The MMR rebuild

`Blockchain.create()` → `_load_chain_from_store()` (`blockchain.py:190-196`)
loops `for height in range(self.mmr_manager.get_aggrtegate_from(),
self._peak_height + 1): header_hash = self.__height_map.get_hash(uint32(height))`
to rebuild the block MMR from `HARD_FORK2_HEIGHT` to the peak on every
node startup. This calls `get_hash()` directly on `BlockHeightMap` — the
one call site the RPC/peer layer doesn't go through `Blockchain` for — and
it is genuinely unbounded: as the chain grows past HF2, this range only
gets longer.

The same full walk is also reachable from header validation when the MMR
manager has no fork context (`blockchain_mmr.py:86-96`), so this isn't
startup-only. On newer trees the startup rebuild also calls
`coin_store.get_coin_commitments_root(height)` for every post-HF2 height
(`blockchain.py:190-199` on the S9 branch), which needs each height's
created and spent coins. That's a dependency on historical coin data, too
([Target design](target.md#historical-coin-data-that-consensus-reads)). Today it works because the full-history
`BlockHeightMap` is loaded from disk before this loop runs
(`block_height_map.py:87-134`). After S13, the windowed cache won't have
this range in RAM. Two ways out, both cheap: read the chain index
directly (if S11 makes the chain index the authority, this is a range
scan, not a per-height point query), or persist the MMR's nodes and frontier, not just
its root (a root alone can't support append, pop or proofs). This has to be
designed before S13, not discovered during it.

## Async call sites — deep by design, already the S7/S8 targets

Everything below reads at heights that are caller-chosen (a peer's
requested range, an RPC client's height, a bluebox-compaction random
height) or walk the *entire* chain by construction (weight proofs). None
of these run on the validation path — they're RPC handlers, peer-protocol
handlers, or background full-node loops — and all of them are exactly the
callers [Pathway](pathway.md)'s S7/S8 name as the ones that move to
`ChainView`/pinned reads:

- **Weight-proof creation** (`weight_proof.py:134,214,227,266,331,352,466,497,517`)
  — walks from genesis or SES boundaries up to the peak, interleaved with
  `await`s. Already named as S7's first consumer (pinned once per walk,
  aborts if the pin is reorged away, instead of the current unprotected
  walk that can silently mix chains on a mid-walk reorg).
- **RPC handlers** (`full_node_rpc_api.py:53,74,235,434,480,576,869,914`)
  — block/coin/additions-and-removals endpoints resolving a client-given
  height or hash. `full_node_rpc_api.py:235` in particular reads
  `peak.height - 4608` (`EPOCH_BLOCKS`) back for signage-point lookups —
  close to but a different bound than `BLOCKS_CACHE_SIZE`, and reached
  from an async RPC handler, not validation, so it doesn't affect the sync
  claim either way.
- **Peer-protocol handlers** (`full_node_api.py:459,463,487,495,513,1412,
  1469,1476,1491,1560,1574,1671,2081,2127,2162`) — `request_block(s)`,
  subscription updates, and the hand-rolled "read, then re-check
  `height_to_hash` still matches, bail on reorg" idiom
  ([Atomicity invariants](invariants.md) already catalogued these same
  sites: `full_node_api.py:1417,1432,1501,1515,2045,2126`). This idiom is
  precisely what S8 deletes once callers move to pinned views.
- **Batch/backtrack sync bookkeeping** (`full_node.py:692,712,1328,1339`)
  — fork-point hash lookups when starting a sync; the fork point can be
  arbitrarily deep for a long resync. `full_node.py:3578` is the
  standout: it picks *random* historical heights (`get_random_not_
  compactified`) for bluebox proof compaction, so its lookback is
  unbounded by construction, not just deep in the worst case.

## Caveat: the post-reorg fork lookup isn't formally bounded

`full_node.py:2076` — `self.blockchain.height_to_hash(state_change_summary.
fork_height)` — runs immediately after `add_block()` returns with a new
peak, to look up the fork's common-ancestor block for `FullNodeStore.new_
peak()`. It's async (a coroutine, not on the DB-transaction-holding
critical section), but it runs synchronously in the sense that it's not
an independently-scheduled background task — it's part of handling the
just-added block, and `fork_height` here is the *actual* reorg depth for
that block, not a small constant.

[Migrations](migration.md) already flags this precisely: *"'Bounded by
`MAX_REORG_DEPTH`' isn't true yet — that constant doesn't exist as an
enforced limit in the node today."* In practice it's shallow —
[Decision log](decisions.md)'s mainnet reorg archeology found 145 orphans
out of 8,582,005 blocks (0.0017%), essentially all single-block — but
"essentially all measured reorgs are shallow" is an empirical observation
about mainnet history, not a bound the code enforces. A theoretically deep
reorg (long enough to exceed the 10k window) would make this specific
lookup miss.

This doesn't break the claim as stated — the claim is about *validation*
lookback, and this call happens after validation and commit succeed, using
the *actual* fork depth of a reorg that already happened, not a
speculative lookback during validation of the next block. But it does mean
no fixed window margin covers it: reorg depth has no enforced bound. This
lookup has to fall back to a direct chain-index read (or a view preloaded
for the fork) when it misses the window, the same way the RPC/peer sites
move off the cache in S8.

## Out of scope

- **`WalletBlockchain`** (`wallet_blockchain.py`) and its callers
  (`wallet_node.py:1787-1788`) use a private `_height_to_hash: dict[uint32,
  bytes32]`, not `chia.consensus.block_height_map.BlockHeightMap`. Separate
  class, separate cache, unaffected by S13.
- **`BlockCache`** (`util/block_cache.py`) implements the same
  `BlockRecordsProtocol` shape (`height_to_hash`/`contains_height`) but is
  a plain in-memory dict built fresh per call, used for weight-proof
  segment validation (`weight_proof.py:546,748,1242`) and the block-tools
  test/simulator harness. It's not `BlockHeightMap` and holds no chain
  state between calls.
- **`AugmentedBlockchain`** (`consensus/augmented_chain.py`) wraps
  `Blockchain` to overlay not-yet-committed fork blocks during batch
  validation. Its `height_to_hash`/`contains_height`
  (`augmented_chain.py:186-199`) check the overlay dict first and fall
  through to the underlying `Blockchain` otherwise — it doesn't add depth
  beyond whatever the underlying call already resolves. Each call site
  above has the same bound (or the same lack of one) whether or not it's
  reached through an `AugmentedBlockchain`.

## Conclusion

Difficulty adjustment, the deepest bounded walk, stays within
`BLOCKS_CACHE_SIZE` (5,120, proven worst case 4,737) of the block being
validated. A 10k window gives it about 2x headroom, measured from the
validation frontier, not the peak. The claim doesn't hold for the MMR walk,
which needs direct chain-index reads or persisted MMR state in S13.

Two things aren't covered by "the claim is true" and need to be carried
into S13's implementation, not just its acceptance criteria:

1. The MMR walk (startup and header validation) needs reads that aren't
   limited to the window.
2. The post-reorg fork lookup (`full_node.py:2076`) uses actual (not
   speculative) reorg depth, which mainnet history says is shallow but
   which no constant enforces. A bigger window can't cover it. It needs a
   fallback to a direct chain-index read, alongside S8.

Every other deep-reading call site (weight proofs, RPC, peer protocol,
batch-sync bookkeeping) is already async and already the named target of
S7/S8's snapshot/view work — this audit didn't find anything in that
category that pathway.md doesn't already account for.

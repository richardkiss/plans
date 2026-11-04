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

## The claim

> Every synchronous caller looks back at most 5,121 blocks
> (`BLOCKS_CACHE_SIZE = 4608 + 128*4 = 5120`, plus one for an inclusive
> range) from the validation frontier. Everything that reads deeper is
> already async and can move to snapshot/view reads.

**Verdict: true, with one caveat.** Every call reachable from
`Blockchain.add_block()` — the only synchronous, validation-critical path
— resolves a height within `BLOCKS_CACHE_SIZE` of the block being
validated. The caveat isn't a violation of the claim, it's a gap in it:
one call site (the MMR rebuild in `Blockchain.create()`) reads the *entire*
post-HF2 range at startup. It's not on the validation path — it runs once,
before validation starts — but a 10k-window cache can't serve it either.
S13 needs to either exempt this path (read the chain index directly,
bypassing the windowed cache) or note it as a known follow-up.

## Summary table

| Call site | Sync/async | Max lookback | Safe for 10k window? |
|---|---|---|---|
| `difficulty_adjustment._get_blocks_at_height` (`difficulty_adjustment.py:29-30,36`) | sync (block validation) | ≤ ~4,737 blocks, proven below | yes |
| `add_block`'s fork-point assert (`blockchain.py:373`) | sync (block validation) | 1 block (always `block.height - 1`) | yes |
| `_load_chain_from_store` fast-forward check (`blockchain.py:1737` via `full_node.py`) | sync-adjacent (batch validation loop) | 0 (always the block just added) | yes |
| Backtrack short-sync fork search (`full_node.py:822`) | async, but self-bounded | ≤ 5 blocks (`while curr_height > peak_height - 5`) | yes |
| `lookup_block_generators` main-chain check (`blockchain.py:1079`) | sync (generator resolution during validation) | 1 (peak-membership check only; deep pre-HF2 refs use a different, non-audited fork-walk path — see [Target design](target.md) and S14) | yes |
| **`Blockchain.create` → MMR rebuild** (`blockchain.py:193`, `blockchain_mmr.py:90-94`) | one-time startup, not validation | **unbounded** — full range from `HARD_FORK2_HEIGHT` to peak | **no — needs a direct chain-index read, not the windowed cache** |
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

`blockchain.py:1737` (reached from `full_node.py`'s batch-validation
helper) compares `self.blockchain.height_to_hash(block.height) ==
header_hash` for a block already seen once before, to decide whether it's
still on the main chain. The guard immediately above it
(`blockchain.py:1731-1732`, `if block.height <= fork_info.peak_height:
continue`) means this only runs for `block.height` strictly past the
current fork frontier — i.e. it's the block currently at the head of the
batch being validated, not a historical lookup. Depth: 0 (it's asking
about the frontier itself, not something below it).

### Generator resolution during validation

`lookup_block_generators` (`blockchain.py:1051-1084`) resolves generator
refs during transaction validation. Its one `height_to_hash` call
(`blockchain.py:1079`) is a single membership check — "is this
generator's block still on the main chain?" — not a range walk, so depth
is 1 lookup at a specific height, not a lookback distance. If the
generator's block *isn't* on the main chain (a fork), resolution falls
through to `lookup_fork_chain` (`find_fork_point.py`), which walks
`block_record`/`prev_hash`, not `height_to_hash` — out of scope here, and
already the subject of S14's post-HF2 plan (once a ref'd height is more
than `MAX_REORG_DEPTH` behind HF2_HEIGHT it's reorg-immune and moves to
the archive; see [Target design](target.md)).

## The one gap: startup MMR rebuild

`Blockchain.create()` → `_load_chain_from_store()` (`blockchain.py:190-196`)
loops `for height in range(self.mmr_manager.get_aggrtegate_from(),
self._peak_height + 1): header_hash = self.__height_map.get_hash(uint32(height))`
to rebuild the block MMR from `HARD_FORK2_HEIGHT` to the peak on every
node startup. This calls `get_hash()` directly on `BlockHeightMap` — the
one call site the RPC/peer layer doesn't go through `Blockchain` for — and
it is genuinely unbounded: as the chain grows past HF2, this range only
gets longer.

This isn't a counterexample to the claim (it's not on the *validation*
path — it happens once, before `Blockchain.create()` returns and before
any block is validated), but it is a real requirement the 10k-window
design has to account for. Today it works because the full-history
`BlockHeightMap` is loaded from disk before this loop runs
(`block_height_map.py:87-134`). After S13, the windowed cache won't have
this range in RAM. Two ways out, both cheap: read the chain index
directly for this one startup walk (S9/S10 already put a `height →
header_hash` table in the DB, so this is a straight range scan, not a
per-height point query), or persist/cache the MMR root across restarts so
the rebuild isn't needed at all. Either is a small, separate fix; flagging
it here so it doesn't get discovered the hard way during S13's
implementation.

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
S13's window needs to be sized with the same margin `clean_block_record`
already gives `BLOCKS_CACHE_SIZE` (rather than the bare 5,120/5,121), or
this lookup needs to move off the windowed cache the same way the RPC/peer
sites do — it already reads the chain index today (via `Blockchain`
delegating to `BlockHeightMap`), so moving it to a direct chain-index read
alongside S8's other migrations costs nothing extra.

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
  beyond whatever the underlying call already resolves, so every sync
  call site audited above stays correctly bounded whether or not it's
  reached through an `AugmentedBlockchain`.

## Conclusion

The claim holds for the path that matters: **every call reachable from
`Blockchain.add_block()` resolves a height within `BLOCKS_CACHE_SIZE`
(5,120, with the difficulty-adjustment walk's proven worst case at 4,737)
of the block being validated.** A 10k-height window gives that walk
essentially 2x headroom over its proven bound, which is comfortable margin
for a constant that's derived from `EPOCH_BLOCKS`, not likely to move.

Two things aren't covered by "the claim is true" and need to be carried
into S13's implementation, not just its acceptance criteria:

1. The startup MMR rebuild (`blockchain.py:193`) needs a chain-index read
   that isn't limited to the window — it's not validation-path, but it is
   real, and it's unbounded today.
2. The post-reorg fork lookup (`full_node.py:2076`) uses actual (not
   speculative) reorg depth, which mainnet history says is shallow but
   which no constant enforces yet. Either give the window the same margin
   `clean_block_record` already uses, or move this one lookup off the
   windowed cache alongside S8.

Every other deep-reading call site (weight proofs, RPC, peer protocol,
batch-sync bookkeeping) is already async and already the named target of
S7/S8's snapshot/view work — this audit didn't find anything in that
category that pathway.md doesn't already account for.

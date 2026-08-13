# Pathway

The work is sharded into small reviewable PRs from one original fat draft
(#1418, closed once the shape was clear) — the same
entrance/exit discipline as the other plans: libraries first, consumer
last, each PR leaving a working system. All states below verified live
against GitHub on 2026-08-13.

## Merged — the entrance stack

| PR | What | Merged |
|----|------|--------|
| [clvm_rs #708](https://github.com/Chia-Network/clvm_rs/pull/708) | The serde_2026 format itself | 2026-05-19; released as clvmr 0.18.0 |
| [chia_rs #1435](https://github.com/Chia-Network/chia_rs/pull/1435) | `generator_interned_weight()` exposed to Python | 2026-05-20 |
| [chia_rs #1456](https://github.com/Chia-Network/chia_rs/pull/1456) | Versioned `FullBlock` wire format (Arvid's; framing only — see E4) | 2026-06-10 |
| [chia_rs #1436](https://github.com/Chia-Network/chia_rs/pull/1436) | `InternedBlockBuilder` — the conservative builder | 2026-07-02 |
| [chia_rs #1437](https://github.com/Chia-Network/chia_rs/pull/1437) | serde_2026 wiring into chia_rs (`node_from_bytes_auto` etc.) | 2026-07-16 |
| [chia_rs #1438](https://github.com/Chia-Network/chia_rs/pull/1438) | `INTERNED_GENERATOR` consensus path + strict serde_2026 enforcement | 2026-08-03, approved by Arvid |

\#1438 is the consensus-critical one: it's where the prefix became
mandatory ([Evidence](evidence.md)) and where classic blobs start failing
with `SerializationError` under the flag.

## In flight

| PR | State (2026-08-13) | What |
|----|--------------------|------|
| [chia_rs #1439](https://github.com/Chia-Network/chia_rs/pull/1439) | Open, restacked on main, CI green, no reviewer assigned yet | serde_2026 *emission*: `InternedBlockBuilder(serde_2026=True)`, `tree_hash_auto()`, `Program.from_program_bytes()`, prefix-aware `Program::parse`. The aggressive `Block2026Builder` moved out to the parked branch. |
| [chia_rs #1491](https://github.com/Chia-Network/chia_rs/pull/1491) | Open, CI green, no reviewer | Small follow-up owed from #1436: reset the builder on successful `finalize()` (a re-use footgun Bugbot caught). |
| [chia_rs #1500](https://github.com/Chia-Network/chia_rs/pull/1500) | Draft, CI green | serde_2026 in the trusted non-consensus readers (`additions_and_removals`, `get_puzzle_and_solution_for_coin`/`2`, `generator_interned_vbytes`) via prefix sniffing. Carries open judgment items — see [Decision log](decisions.md). |
| [chia-blockchain #20800](https://github.com/Chia-Network/chia-blockchain/pull/20800) | Draft, merge-conflicting (main moved past the 08-10 rebase); 47 failing checks, all expected git-dep noise (wheel matrix, dependency-review, one coverage job) | The exit: Python wiring with `INTERNED_GENERATOR` active post-HF2 — `generator_root()`, `compute_block_cost`, tests. Pinned to a chia_rs git dep until a release exists. I have no merge access here; it lands via the team. |

Parked, deliberately:
`park/block-2026-builder-optimization` on Chia-Network/chia_rs
(`efb05fd1`) — the aggressive anytime builder, extracted from #1439. It
returns as an opt-in optimization PR after HF2, not before
([Target design](target.md)).

Closed, deliberately:
[#1499](https://github.com/Chia-Network/chia_rs/pull/1499)
(prefix-optional consensus parsing) — closed unmerged 2026-07-29; the
reasoning is a settled decision.
[#1418](https://github.com/Chia-Network/chia_rs/pull/1418) and
[#1413](https://github.com/Chia-Network/chia_rs/pull/1413) — early drafts
superseded by the shards above.

## What remains

1. **#1439 review and merge** — the last chia_rs entrance PR. Everything
   emission-side waits on it.
2. **A chia_rs release** including #1438/#1439, so #20800 can drop its git
   pin and point at PyPI. Release timing is Arvid's/the team's call.
3. **#20800 rebase, review, merge** — needs another rebase (main moved),
   a reviewer, and a decision on the post-HF test knob (how tests opt into
   post-fork constants). Team-merged.
4. **Activation height** — deliberately not wired by any PR in this
   series. The hand-off surface is one line: adding
   `INTERNED_GENERATOR` to the flag set in
   `get_flags_for_height_and_constants()` at whatever height Arvid
   chooses. I deliver the complete flag-gated machinery; he flips it.
   (Verified 2026-08-13: chia_rs main still gates HF2 flags on
   `hard_fork2_height` without `INTERNED_GENERATOR`, and
   `HARD_FORK2_HEIGHT` on chia-blockchain main is still the
   `0xFFFFFFFA` placeholder.)

## Critical path

\#1439 → chia_rs release → #20800 repin/rebase → team merge → Arvid's
one-line activation. #1491 and #1500 are off the critical path — both are
green and waiting for review whenever convenient.

## After activation

Cleanup that can only land post-fork: remove `SIMPLE_GENERATOR` /
`check_generator_quote` / `check_generator_node` from the live path, and
un-park the aggressive builder if it earns it. Rename
`transactions_generator` to something honest (`spend_list`) where the wire
allows.

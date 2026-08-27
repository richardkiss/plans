# Pathway

The work is sharded into small reviewable PRs from one original fat draft
(#1418, closed once the shape was clear) — the same
entrance/exit discipline as the other plans: libraries first, consumer
last, each PR leaving a working system. All states below verified live
against GitHub on 2026-08-27.

## Merged — the entrance stack

| PR | What | Merged |
|----|------|--------|
| [clvm_rs #708](https://github.com/Chia-Network/clvm_rs/pull/708) | The serde_2026 format itself | 2026-05-19; released as clvmr 0.18.0 |
| [chia_rs #1435](https://github.com/Chia-Network/chia_rs/pull/1435) | `generator_interned_weight()` exposed to Python | 2026-05-20 |
| [chia_rs #1456](https://github.com/Chia-Network/chia_rs/pull/1456) | Versioned `FullBlock` wire format (Arvid's; framing only — see E4) | 2026-06-10 |
| [chia_rs #1436](https://github.com/Chia-Network/chia_rs/pull/1436) | `InternedBlockBuilder` — the conservative builder | 2026-07-02 |
| [chia_rs #1437](https://github.com/Chia-Network/chia_rs/pull/1437) | serde_2026 wiring into chia_rs (`node_from_bytes_auto` etc.) | 2026-07-16 |
| [chia_rs #1438](https://github.com/Chia-Network/chia_rs/pull/1438) | `INTERNED_GENERATOR` consensus path + strict serde_2026 enforcement | 2026-08-03, approved by Arvid |
| [chia_rs #1501](https://github.com/Chia-Network/chia_rs/pull/1501) | Correct `transactions_generator_buffer` type (Arvid's) | 2026-08-04 |
| [chia_rs #1502](https://github.com/Chia-Network/chia_rs/pull/1502) | New cost model (Arvid's) | 2026-08-06 |
| [chia-blockchain #21249](https://github.com/Chia-Network/chia-blockchain/pull/21249) | New full block format and cost model (Arvid's) | 2026-08-19 |

\#1438 is the consensus-critical one: it's where the prefix became
mandatory ([Evidence](evidence.md)) and where classic blobs start failing
with `SerializationError` under the flag.

\#21249 changed the ground under the exit side of this plan (see "Closed,
superseded" below): v1 blocks steal dead bits of the `Option<Program>`
prefix byte for a version field (historical blocks are untouched — their
bytes already read as v0; old parsers reject v1 cleanly), and carry the
generator as raw bytes in a new `transactions_generator_buffer` field —
no ref list in v1. `validate_tx_generator()` requires v0 before, v1 at or
after `HARD_FORK2_HEIGHT`.

## Closed, superseded

- [chia_rs #1439](https://github.com/Chia-Network/chia_rs/pull/1439) —
  **CLOSED 2026-08-27**, replaced by #1511 (below). #1439 tried to make
  `Program` itself learn serde_2026 (parse-widening, reader dispatch, an
  `is_serde_2026_encoded` probe). Once #21249 put the generator on its own
  raw-bytes wire path, the only place still wrapping generator bytes into
  a `Program` was chia-blockchain's `get_block_generator.py`, and only
  because of a type the exit side could fix directly (see "The open
  blocker" below). With that, `Program` never needed serde_2026 at all —
  Richard's ruling — and #1439 shrank to emission plus explicit-format
  readers. #1511 is that shrunk PR, not a rebase of #1439.
- [chia-blockchain #20800](https://github.com/Chia-Network/chia-blockchain/pull/20800) —
  **CLOSED 2026-08-27**, superseded by #21249's architecture, not rebased
  onto it. #20800 was written against the pre-#21249 world (its own
  `generator_root()`/`validate_generator_encoding()`, which #21249
  deleted and replaced with `block.version`-keyed validation). Salvage:
  its `generator_root`-is-tree-hash tests are the right shape but need a
  chia_rs tree-hash function that didn't exist until #1511; the
  replacement wiring is drafted locally (see "The wiring draft" below),
  not yet a PR.

## In flight

| PR | State (2026-08-27) | What |
|----|--------------------|------|
| [chia_rs #1511](https://github.com/Chia-Network/chia_rs/pull/1511) | Draft, tip `9cae0cfd`, CI green (all gates), `mergeStateStatus` BLOCKED on a missing review, no reviewer requested yet | serde_2026 *emission* (`InternedBlockBuilder`, always-on, no flag) plus explicit non-sniffing readers: `tree_hash_2026(blob) -> bytes32`, byte-native `get_puzzle_and_solution_for_coin_2026`, flag-dispatched `additions_and_removals`, `INTERNED_GENERATOR` exposed to Python and OR'd into `get_flags_for_height_and_constants` at `hard_fork2_height`. `Program` is untouched — byte-identical to main. This is the PR that replaces #1439. |
| [chia_rs #1491](https://github.com/Chia-Network/chia_rs/pull/1491) | Open, CI green, no reviewer | Small follow-up owed from #1436: reset the builder on successful `finalize()` (a re-use footgun Bugbot caught). Unchanged, off the critical path. |
| [chia_rs #1500](https://github.com/Chia-Network/chia_rs/pull/1500) | Draft, still open | serde_2026 in the trusted non-consensus readers (`additions_and_removals`, `get_puzzle_and_solution_for_coin`/`2`, `generator_interned_vbytes`) — but via prefix-sniffing (`node_from_bytes_auto`), predating Richard's no-sniffing ruling. **Overlaps #1511**: both touch `additions_and_removals.rs` and `wheel/src/api.rs`, and #1511 now ships flag-dispatched `additions_and_removals` plus a byte-native `get_puzzle_and_solution_for_coin_2026` — the same jobs, done the ruled-on way. Nobody has closed or rebased #1500 yet; flagging the overlap rather than asserting its fate. |

Parked, deliberately:
`park/block-2026-builder-optimization` on Chia-Network/chia_rs
(`efb05fd1`) — the aggressive anytime builder, extracted from the original
#1439. It returns as an opt-in optimization PR after HF2, not before
([Target design](target.md)).

Closed, deliberately:
[#1499](https://github.com/Chia-Network/chia_rs/pull/1499)
(prefix-optional consensus parsing) — closed unmerged 2026-07-29; the
reasoning is a settled decision.
[#1418](https://github.com/Chia-Network/chia_rs/pull/1418) and
[#1413](https://github.com/Chia-Network/chia_rs/pull/1413) — early drafts
superseded by the shards above.

## The wiring draft (local, not yet a PR)

#20800's replacement isn't a PR yet — it's a local, unpushed branch
(`hf2-wiring`, chia-blockchain, commit `470bb89427`) built to answer one
question empirically: does anything on the exit side need prefix-sniffing?
**No** — every call site dispatches on `block.version` or fork height,
verified against the pinned chia_rs wheel, not assumed. It wires: mempool
serde_2026 emission post-HF2, the `INTERNED_GENERATOR` flag via a
`consensus_flags.py` wrapper, the SF9 `is_canonical_serialization` check
gated to v0 (it would otherwise reject serde_2026 bytes), and
`generator_root` dispatched to tree-hash post-HF2 / `std_hash` pre-HF2.
It's blocked from running end-to-end by the open blocker below, and its
tree-hash path was written against a chia_rs wheel that had no
`tree_hash_2026` binding yet — #1511 now ships one, so re-testing this
draft against #1511's tip is the next step once the blocker clears.

## The open blocker

`BlockGenerator.program` (chia-blockchain, `generator_types.py`) is typed
`SerializedProgram` — that's `chia_rs.Program` — which structurally cannot
hold serde_2026 bytes. Confirmed directly: `Program.from_bytes` and
`.from_bytes_unchecked` both raise `unexpected end of buffer` on real
serde_2026 bytes. This isn't a hypothetical — it crashes mempool's own
block builders on their own output, crashes `Blockchain.add_block`'s
additions/removals computation, and in `multiprocess_validation.py` the
exception is swallowed, so every post-HF2 transaction block with a
generator would be silently rejected as invalid, not just crash loudly.

Proposed fix: retype `BlockGenerator.program` (and `NewBlockGenerator`) to
raw `bytes`. Every chia_rs call downstream of it is already byte-native,
and every caller already has `block.version` in hand. This is a
chia-blockchain type design decision, not a chia_rs question — Arvid's
design area — and the conversation hasn't happened yet. **This is the one
genuinely open, unsettled thing in this plan.**

## What remains

1. **#1511 review** — Richard's and then Arvid's. It's the last chia_rs
   entrance PR; a chia_rs release including it is what lets the exit side
   drop its git pin.
2. **The `BlockGenerator.program` conversation with Arvid** — blocks the
   wiring draft above from becoming a real PR.
3. **A real wiring PR**, once that conversation resolves — the actual
   replacement for #20800, built from the local draft.
4. **#1500's fate** — decide whether it's superseded by #1511's readers or
   still carries something #1511 doesn't.
5. **Activation height** — still nobody's job in this series but Arvid's.
   `INTERNED_GENERATOR` still isn't in chia_rs main's flag set, and
   `HARD_FORK2_HEIGHT` on chia-blockchain main is still a placeholder.

## Critical path

\#1511 review/merge → the `BlockGenerator.program` conversation → a real
wiring PR (the #20800 replacement) → chia_rs release → Arvid's one-line
activation. #1491 and #1500 are off the critical path.

## After activation

Cleanup that can only land post-fork: remove `SIMPLE_GENERATOR` /
`check_generator_quote` / `check_generator_node` from the live path, and
un-park the aggressive builder if it earns it. Rename
`transactions_generator` to something honest (`spend_list`) where the wire
allows.

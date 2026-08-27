# Decision log

Dated decisions with the reasoning, then what's still open.

## 2026-02 — Single activation at `HARD_FORK2_HEIGHT`

`INTERNED_GENERATOR` activates at `hard_fork2_height` with the rest of the
HF2 bundle, not at its own height. This is the established pattern —
features get flags, all flags flip at one master height — and the HF2
features genuinely depend on each other. A separate
`hard_fork_tree_generator_height` constant existed in an early branch and
was dropped from the activation logic. Settled.

## 2026-07 — The generator is data, not a program

Post-fork the blob is taken verbatim: tree hash is identity, cost is the
interned tree. No quote wrapper, no `check_generator_quote`. Corollary
that shaped every PR since: **flag-off behavior stays byte-identical to
deployed nodes** — no new code paths when `INTERNED_GENERATOR` is unset,
so post-fork design shifts can't force re-audits of shipped behavior.
Settled.

## 2026-07 — The prefix is mandatory consensus

The misparse check (E1/E2 in [Evidence](evidence.md)) settled the
question raised on
[#1438](https://github.com/Chia-Network/chia_rs/pull/1438): the body
behind the prefix parses "successfully" as garbage under old
deserializers, so the prefix is the *only* thing that makes old parsers
fail at byte one instead of executing noise. It's a load-bearing
consensus rule, not decoration. Settled — this argument carried the
review.

## 2026-07-29 — #1499 closed: no generous parsing at the consensus boundary

[#1499](https://github.com/Chia-Network/chia_rs/pull/1499) would have
accepted bare (prefix-stripped) serde_2026 bodies in
`run_block_generator2`. Closed unmerged, for three reasons:

1. The wire audit (E4) showed strict `run_block_generator2` is the *only*
   prefix enforcement anywhere — there is no separate wire check to fall
   back on. Generosity there would have made bare bodies consensus-valid
   on the wire: adversarial farmers could mint blocks that silently
   misparse in old parsers, and blocks become byte-malleable again.
2. It directly undermines the fail-fast argument that justified the
   prefix in the first place.
3. "Add generosity later if needed" only works *before* activation —
   once the flag is live, going strict→generous is rule-loosening (a
   chain-split risk) — except at layers consensus doesn't see (below).

What survived from that work: the structural-unambiguity proof (E3) and
the wire audit itself.

## 2026-07-29 — Store-side strip/prepend stays possible, node-locally

Because the post-fork header commits to the tree hash, framing at rest is
storage policy ([Target design](target.md)). A node may later strip the
prefix in its block DB and prepend on read — provably safe by E3, purely
node-local, no consensus change. Caveat kept visible: any such relaxation
must reject framing failures at the message level, never cache them as
block invalidity keyed by header hash. Settled as an option, not
scheduled.

## 2026-07-29 — Error type: reuse `EvalErr::SerializationError`

Arvid's call on #1438, and the right one: a post-fork classic blob fails
with the same error the non-interned path already uses for undecodable
bytes. No new error variant; Python-visible code unchanged. Done in
`616e4863`. Settled.

## 2026-07 — Conservative builder ships first

Two builders exist on purpose ([Target design](target.md)): the simple
synchronous `InternedBlockBuilder` is the default; the aggressive anytime
builder is parked (`park/block-2026-builder-optimization`) until proven.
Chain-stall risk from an unproven aggressive builder outweighs its
throughput upside on day one. Settled.

## 2026-07-09 — Activation is Arvid's, by design

No PR in this series wires `INTERNED_GENERATOR` into
`get_flags_for_height_and_constants()`. I deliver a complete flag-gated
surface; the activation is a one-line change at a height Arvid chooses.
Settled.

## 2026-08-13 — The builder never carries an emission-format flag

`InternedBlockBuilder` always emits serde_2026; there is no
`serde_2026=True/False` switch on it. Its interned-vbyte cost model is
only correct post-fork, and post-fork serde_2026 is the only legal
encoding — a classic-emission mode on this builder would just be a way to
build invalid blocks. Settled.

## 2026-08-24 — `Program` never learns serde_2026; #1439 replaced by #1511

Reading Arvid's merged work
([#1501](https://github.com/Chia-Network/chia_rs/pull/1501)/
[#1502](https://github.com/Chia-Network/chia_rs/pull/1502) in chia_rs,
[#21249](https://github.com/Chia-Network/chia-blockchain/pull/21249) in
chia-blockchain) settled the architecture: v1 blocks carry the generator
as raw bytes (`transactions_generator_buffer`), with the version known
from the block itself. Under that architecture the only code anywhere
that wraps generator bytes into a `Program` is chia-blockchain's exit-side
reader, and only because of a type it could fix directly (the
`BlockGenerator.program` blocker below) — so `Program`, the
general-purpose type used for puzzles and solutions everywhere else,
never needs to carry serde_2026 at all. Ruling: it doesn't, ever. #1439
(which had widened `Program::parse` to accept serde_2026) is superseded by
[#1511](https://github.com/Chia-Network/chia_rs/pull/1511), which is
emission plus explicit-format readers only — `Program` stays
byte-identical to main. Settled.

## 2026-08-24 — No sniffing, anywhere

Consensus never wants "accept either" — verified empirically, not just
argued: no consensus call site in the pinned chia_rs wheel calls a
prefix-sniffing function, and the wiring draft (chia-blockchain,
`hf2-wiring` branch) confirmed every exit-side call site also has
`block.version` or a fork-height comparison in hand already, so none of
them need to guess from the byte prefix either. The one sniffing helper
that had been built for this purpose, `node_from_bytes_auto` (and its
tree-hash counterpart `tree_hash_auto`), was deleted in
[#1511](https://github.com/Chia-Network/chia_rs/pull/1511)'s 2026-08-27
amendment rather than shipped — replaced by non-sniffing, explicitly-named
functions (`node_from_bytes_2026_trusted`, `tree_hash_2026`). Settled.

## 2026-08-24 — `generator_root` post-HF2 is the tree hash

Post-HF2 (v1), `generator_root` is the tree hash of the generator, not a
hash of its bytes — this is the change that makes serialization pure
transport and kills the malleability [Problem](problem.md) opens with.
Pre-HF2 (v0) keeps `std_hash` of the serialized bytes; the two are
dispatched on `block.version`. Note honestly: as of
[#21249](https://github.com/Chia-Network/chia-blockchain/pull/21249),
current chia-blockchain main still `std_hash`es v1 buffers — the
tree-hash change is not yet live anywhere; it's what the still-unwritten
exit-side wiring PR (replacing #20800) needs to do, and it's exactly what
the local `hf2-wiring` draft implements (blocked from being tested
end-to-end by the open question below, and until 2026-08-27 also blocked
by chia_rs having no Python-visible way to compute a serde_2026 tree hash
at all — [#1511](https://github.com/Chia-Network/chia_rs/pull/1511) now
ships `tree_hash_2026` for this).

## Open questions

Marked open because they are.

- **`BlockGenerator.program: SerializedProgram` cannot hold serde_2026
  bytes** (chia-blockchain, `generator_types.py`) — confirmed empirically:
  `Program.from_bytes`/`.from_bytes_unchecked` both reject serde_2026
  bytes with `unexpected end of buffer`, which crashes mempool's own
  block builders, `Blockchain.add_block`'s additions/removals path, and
  (via a swallowed exception) silently rejects every post-HF2
  transaction block in `multiprocess_validation.py`. Proposed fix: retype
  the field to raw `bytes` — every chia_rs call downstream is already
  byte-native, and callers already carry `block.version`. This is a
  chia-blockchain design decision, Arvid's design area, and **the
  conversation with him hasn't happened yet.** The only genuinely open
  thing left in this plan.
- **Activation height and timing** — Arvid's; nothing on my side blocks
  it once the pathway completes. `HARD_FORK2_HEIGHT` is still a
  placeholder on main.
- **chia_rs release timing** — needed before the exit-side wiring PR can
  point at PyPI instead of a git pin. Not mine to cut.
- **#1500's fate** — its trusted-reader changes overlap
  [#1511](https://github.com/Chia-Network/chia_rs/pull/1511)'s (same
  functions, sniffing vs. flag-dispatch), but nobody has closed or
  rebased it yet. Needs a decision, not an assumption.
- **Smaller, from #1500**: whether the wheel helpers should get real size
  caps instead of `usize::MAX` (input is the node's own validated data,
  so it's the same trust level as before — but worth a look).

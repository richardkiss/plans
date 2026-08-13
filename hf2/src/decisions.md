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

## Open questions

Marked open because they are.

- **Activation height and timing** — Arvid's; nothing on my side blocks
  it once the pathway completes. `HARD_FORK2_HEIGHT` is still a
  placeholder on main.
- **chia_rs release timing** — needed before #20800 can point at PyPI
  instead of a git pin. Not mine to cut.
- **`Program`/Streamable rejects serde_2026 blobs** — found in the
  [#1500](https://github.com/Chia-Network/chia_rs/pull/1500) audit:
  `Program::parse` refuses `0xfd`, so Python can't construct a `Program`
  from a serde_2026 blob, which gates every `Program`-taking helper and
  presumably `FullBlock` round-tripping. #1439's prefix-aware
  `Program::parse` is the intended fix — whether that's the right layer
  **needs Arvid's eyes**.
- **#20800 post-HF test knob** — how the chia-blockchain test suite opts
  into post-fork constants; design not settled.
- **Smaller, from #1500**: unify sniff-vs-flag dispatch across the
  trusted helpers; whether the wheel helpers should get real size caps
  instead of `usize::MAX` (input is the node's own validated data, so
  it's the same trust level as before — but worth a look).

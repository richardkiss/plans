# Target design

The post-HF2 world, in one line each:

- **Identity**: a generator is identified by the tree hash of its interned
  tree, not the hash of its bytes.
- **Cost**: interned vbytes — `atom_bytes + 2·atoms + 3·pairs` — replacing
  byte-length cost. Structure, not encoding.
- **Format**: serde_2026 is the generator serialization, prefix mandatory.
  Under `INTERNED_GENERATOR`, `run_block_generator2` accepts *only*
  serde_2026; classic and back-ref blobs fail with `SerializationError`.
- **`Program` stays classic-only**. The general-purpose `Program` type
  (puzzles, solutions, and anywhere else CLVM is passed around) never
  learns serde_2026 — Richard's ruling. The generator is the one place a
  block's version is known at deserialization time, so the block version
  selects the decoder there; `Program::parse` doesn't need to, and
  shouldn't, guess.
- **No sniffing, anywhere.** Every call site dispatches on `block.version`
  or fork height, never on the byte prefix. `Program.from_bytes` rejecting
  serde_2026 blobs is the direct consequence, not a gap to be closed with a
  prefix-sniffing fallback. See [Decision log](decisions.md).
- **`generator_root` post-HF2 is the tree hash of the generator.**
  Serialization becomes pure transport once the header commits to the tree
  hash instead of the bytes — the malleability problem this whole plan
  exists to fix. Pre-HF2 (v0) keeps `std_hash` of the serialized bytes;
  the two live side by side, dispatched on `block.version`.
- **Pipeline**: bytes → serde_2026 deserialize → intern → spend list. No
  ROM, no quote wrapper, no `SIMPLE_GENERATOR`, no `check_generator_quote`.
  The blob is data taken verbatim, not a program — the "generator" name
  survives only for wire compatibility. `transactions_generator_ref_list`
  is dead too; back-refs already broke cross-block compression, and nodes
  shouldn't need every historical generator forever.

## One activation, not two

`INTERNED_GENERATOR` and serde_2026 activate together at
`HARD_FORK2_HEIGHT`. They're tightly coupled by design — the new cost
model is computed over the interned tree that serde_2026 decodes into, and
the strict format check is the wire enforcement (E4 in
[Evidence](evidence.md)). There is no separate format-activation flag, and
none is needed later either: format versioning is baked into the prefix
itself (the magic spells "2026"), so a future format is a new magic, not a
new consensus flag mechanism.

This follows the established HF2 pattern: features get their own flags,
all flags flip at the single `hard_fork2_height`.

## Emission — a ladder of risk

Consumption is consensus; emission is farmer policy, and it gets a
conservative ladder:

1. `solution_generator_2026()` — one-shot batch function, the simplest
   fallback path.
2. `InternedBlockBuilder`
   ([#1436](https://github.com/Chia-Network/chia_rs/pull/1436) +
   [#1511](https://github.com/Chia-Network/chia_rs/pull/1511)) — the
   simple synchronous builder; it always emits serde_2026. It has no
   emission-format flag on purpose: its interned-vbyte cost model is only
   correct post-fork, and post-fork the strict rule makes serde_2026 the
   only valid format — a classic-emission mode would just be a way to
   build invalid blocks. This is what ships as the safe default.
3. An aggressive "anytime" builder (background optimization thread) —
   parked at `park/block-2026-builder-optimization`, opt-in later, only
   after it's proven in the field. If everyone ran an unproven aggressive
   builder and it had a bug, the chain could stall; the conservative one
   ships first on purpose.

The builder never sees consensus flags — the caller picks the classic
builder or the interned one based on `INTERNED_GENERATOR` activation.

## Framing becomes policy after the fork

Post-HF2 the block header commits to the generator's *tree hash*, so how
the bytes are framed at rest is relay/storage policy, not consensus — a
node could strip the 6-byte prefix in its DB and prepend on read, safely,
because no valid body can start with the magic (E3). That option is
deliberately kept open but not taken now; on the wire and at the consensus
boundary the prefix stays mandatory ([Decision log](decisions.md)).

## Design principle for the transition

Every consensus PR in this series minimizes new code paths when
`INTERNED_GENERATOR` is *not* set — flag-off behavior stays byte-identical
to deployed nodes. Post-fork semantics were still in motion while these
PRs landed; a frozen pre-activation path means design shifts can't force
re-audits of shipped behavior.

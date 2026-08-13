# Problem

A Chia block generator today is a byte blob. Its identity is the hash of
its serialized bytes, and its cost is charged partly by byte length. The
serialization is classic CLVM with back-references — and that encoding is
malleable: the same tree has many valid encodings, differing in back-ref
choices, each with a different hash and a different cost. Consensus is
coupled to a wire format.

(The field is called `transactions_generator`, but that's a misnomer by
now — it's a spend-list blob. It hasn't actually been run as a CLVM
program since back-ref handling was ported to Rust; the deserializer walks
it directly.)

## Why the coupling hurts

**Identity is accidental.** Two byte strings that decode to the identical
tree are different generators as far as the chain is concerned. Before
HF2's canonical-serialization rule, even overlong integer encodings
produced distinct hashes for semantically identical generators.

**Cost charges for encoding, not structure.** Byte-length cost rewards
whoever compresses hardest and makes the cost of a spend depend on how it
happened to be serialized, not on what it makes the chain do.

**Every format improvement is a fork.** A better serialization changes
hashes and costs, so it changes consensus. That's backwards — the format
should be a transport detail.

## What HF2 changes

Two things, activating together at `HARD_FORK2_HEIGHT`:

1. **Interned identity and cost** (`INTERNED_GENERATOR`). Generator
   identity becomes the tree hash of the interned (canonical) tree; cost
   becomes interned vbytes — `atom_bytes + 2·atoms + 3·pairs` — computed
   over structure, not encoding. Interning also dedups shared subtrees,
   which is where the compression headroom lives.
2. **A new serialization** (`serde_2026`). The post-fork wire format for
   generator blobs: measured roughly 20% smaller than the classic back-ref
   format and several times faster to decode (numbers from the clvm_rs
   work, [clvm_rs #708](https://github.com/Chia-Network/clvm_rs/pull/708)).
   It starts with a 6-byte magic prefix, `fd ff 32 30 32 36` — `0xfd`,
   `0xff`, then "2026" in ASCII.

## The safety question

The dangerous scenario in any format transition is mixed versions: a
post-fork blob reaching a pre-fork parser. If old code can "successfully"
parse new bytes into garbage, you get silent misbehavior instead of a
clean error. It turns out the serde_2026 *body* misparses near-universally
under classic deserializers, and the entire fail-fast property lives in
the prefix — which is why the prefix is mandatory consensus, not
decoration. That argument, made precise, is [Evidence](evidence.md); the
post-fork design is [Target design](target.md); the PR sequence is
[Pathway](pathway.md).

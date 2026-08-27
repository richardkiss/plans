# Evidence

Three findings, all verified by running code against clvm_rs and chia_rs
(main, May–July 2026 — serde_2026 as landed in
[clvm_rs #708](https://github.com/Chia-Network/clvm_rs/pull/708)). They
settled the prefix-bytes thread on
[chia_rs #1438](https://github.com/Chia-Network/chia_rs/pull/1438) and
they shape everything in [Decision log](decisions.md).

## E1 — a bare serde_2026 body misparses near-universally

I checked whether stripping the 6-byte prefix leaves a blob that old
parsers safely reject. It does not — the opposite. The bare body of
virtually every serde_2026 blob parses *successfully* under both
`node_from_bytes` and `node_from_bytes_backrefs`. Two facts combine:

1. **Neither classic deserializer checks for trailing bytes.** They pop
   ops until one node is complete and return it; the rest of the buffer is
   silently ignored.
2. **The body's first byte is a tiny varint.** The body layout starts with
   the atom-group count, minimally encoded — for any program with ≤ 63
   distinct atom-length groups (virtually every real generator) that's a
   single byte `0x00`–`0x3f`, which classic CLVM reads as a complete
   one-byte atom. Parse done after one byte.

Concrete: the serde_2026 body of `(q . 3)` classic-parses to the atom
`1` — which is itself a *runnable* CLVM program (returns the whole
environment). The garbage isn't even guaranteed to be inert. It is
bounded, though: the misparse always yields a small atom or nil, never a
pair (a pair needs first byte `0xff`, which no valid body can start
with — see E2).

The conclusion that matters: **nothing in the body format is designed to
fail old parsers. The fail-fast property lives entirely in the prefix.**
On the pre-fork consensus path, generators go straight into
`node_from_bytes_backrefs`, which ignores trailing bytes — so a bare body
handed to a deployed node parses at the deserializer level and is only
caught, if at all, downstream. The safety story must rest on the prefix
never being stripped, not on the body failing to parse.

One caveat, kept visible: callers that *do* enforce exact-length
consumption (Streamable `Program::parse`, `from_json_dict`) would reject
these bodies — but only because the classic parse consumes 1–65 bytes of
a longer buffer. That's incidental, not a format guarantee; an adversary
with overlong varints and arbitrary atom payloads should be assumed able
to construct a full-length polyglot.

## E2 — the prefix fails both old parsers from byte one, guaranteed

The first prefix byte alone does it. Classic and backrefs both route
`0xfd` to atom parsing; `decode_size` sees six leading ones, so the
declared atom length is ≥ 2^40 — over the hard 2^34 cap in
`parse_atom.rs`, which errors immediately and unconditionally.
Decoder-guaranteed, not buffer-size-dependent. (Even without the cap,
satisfying the declared length would take a ≥ 1 TiB input; the second
prefix byte `0xff` only adds margin.) Verified empirically: the prefix
alone, prefix plus 64 arbitrary bytes, and `0xfd` plus 64 zero bytes all
fail both deserializers with `bad encoding`.

So the two directions are asymmetric by design: new blob → old parser
fails at byte one; old blob → new parser fails the magic check. Nothing
executes as garbage in either direction — as long as the prefix is
mandatory.

## E3 — no valid body can start with the magic (structural)

The reverse-confusion question: can a valid serde_2026 body happen to
begin with `0xfd`, making prefixed and bare framings ambiguous? No — and
the guarantee is structural, not a magnitude cap. In serde_2026's varint
encoding, `0xfd` is six leading ones with the single payload bit set, and
that payload bit is the sign bit of the two's-complement value: any varint
starting `0xfd` decodes *negative*, unconditionally. The body's leading
varint is the atom-group count, which is rejected when negative. This
holds for lenient parsing and overlong encodings alike. Sign, not
magnitude — by construction, no childproofing needed.

Structurally, this is what would make prefix-sniffing dispatch sound if
anything ever needed it, and what makes a future store-side strip/prepend
provably safe. In practice nothing does: every real call site knows the
block version already, and Richard ruled out sniffing anywhere in the
shipped design — the trial sniffing helper (`node_from_bytes_auto`) was
built, then deleted before anything shipped ([Decision log](decisions.md)).

## E4 — the wire audit: strict consensus IS the enforcement

I audited where the prefix is actually enforced. **Nothing in chia_rs
checks it on the wire.** The `FullBlock` v1 wire format
([chia_rs #1456](https://github.com/Chia-Network/chia_rs/pull/1456))
carries the generator as an unvalidated raw buffer — there are explicit
tests asserting garbage round-trips. #1456 added framing only; a
long-standing claim in my own notes that it added a prefix check was
wrong.

So the only thing making the prefix consensus-mandatory is the strict
`run_block_generator2` under `INTERNED_GENERATOR`
([chia_rs #1438](https://github.com/Chia-Network/chia_rs/pull/1438)):
post-fork, a generator that doesn't start with the magic fails block
validation with `SerializationError`. That single check is the wire
enforcement. Weaken it — accept bare bodies at the consensus boundary —
and E1's misparse scenario becomes reachable by adversarial farmers, plus
blocks become byte-malleable again. That's why
[#1499](https://github.com/Chia-Network/chia_rs/pull/1499) was closed
([Decision log](decisions.md)).

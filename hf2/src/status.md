# Status

Living page. Dated entries, newest first.

## 2026-08-27 — Architecture settled, one blocker left; #1439/#20800 retired

All PR states on this page verified live today against GitHub.

- The consensus core is **merged**, and grew this week:
  [clvm_rs #708](https://github.com/Chia-Network/clvm_rs/pull/708),
  [chia_rs #1435](https://github.com/Chia-Network/chia_rs/pull/1435),
  [#1436](https://github.com/Chia-Network/chia_rs/pull/1436),
  [#1437](https://github.com/Chia-Network/chia_rs/pull/1437),
  [#1438](https://github.com/Chia-Network/chia_rs/pull/1438) (the
  consensus-critical one, approved by Arvid), and now also — Arvid's —
  [#1501](https://github.com/Chia-Network/chia_rs/pull/1501),
  [#1502](https://github.com/Chia-Network/chia_rs/pull/1502), and
  [chia-blockchain #21249](https://github.com/Chia-Network/chia-blockchain/pull/21249)
  (2026-08-19) — the new full block format that puts v1 generators on
  their own raw-bytes wire path with a version bit stolen from the old
  `Option<Program>` prefix byte.
- **#21249 changed the shape of the rest of this plan.** Reading it
  settled two rulings: `Program` never learns serde_2026 (the generator's
  version is known independently of the `Program` type now), and there is
  no sniffing anywhere — every call site, consensus or not, dispatches on
  `block.version` or fork height. See [Decision log](decisions.md).
- **[chia_rs #1439](https://github.com/Chia-Network/chia_rs/pull/1439) is
  CLOSED** (2026-08-27, replaced) — it had widened `Program::parse` to
  accept serde_2026, which the ruling above makes unnecessary.
  **[chia_rs #1511](https://github.com/Chia-Network/chia_rs/pull/1511)**
  replaces it: much smaller, `Program` untouched, tip `9cae0cfd`, all CI
  gates green, `mergeStateStatus` BLOCKED on a missing review (not on
  CI) — no reviewer requested yet. It ships serde_2026 emission
  (`InternedBlockBuilder`, still flag-free) plus explicit non-sniffing
  readers: `tree_hash_2026`, a byte-native
  `get_puzzle_and_solution_for_coin_2026`, flag-dispatched
  `additions_and_removals`, and `INTERNED_GENERATOR` exposed to Python
  and OR'd into `get_flags_for_height_and_constants` at
  `hard_fork2_height`.
  [#1491](https://github.com/Chia-Network/chia_rs/pull/1491) (builder-reset
  follow-up) is unchanged, still green, still unreviewed.
  [#1500](https://github.com/Chia-Network/chia_rs/pull/1500) (trusted RPC
  readers via prefix-sniffing) is still open but now overlaps #1511's
  readers — its fate is an open question, not yet decided by anyone.
- **[chia-blockchain #20800](https://github.com/Chia-Network/chia-blockchain/pull/20800)
  is CLOSED** (2026-08-27) — superseded by #21249's architecture, not
  rebased onto it; its own `generator_root()`/`validate_generator_encoding()`
  no longer exist on main. Its replacement is drafted but not yet a PR: a
  local, unpushed chia-blockchain branch (`hf2-wiring`, commit
  `470bb89427`) wiring mempool serde_2026 emission post-HF2, the
  `INTERNED_GENERATOR` flag, a version-gated SF9 canonicality check, and
  tree-hash `generator_root` post-HF2. Verified empirically against the
  question that mattered most: nothing in this draft needs prefix-sniffing
  either.
- **The one thing left genuinely open**: `BlockGenerator.program`
  (chia-blockchain) is typed `SerializedProgram`, which structurally
  cannot hold serde_2026 bytes — confirmed directly, not inferred:
  `Program.from_bytes`/`.from_bytes_unchecked` both raise on real
  serde_2026 bytes. This crashes the mempool's own block builders on
  their own output, and would make block validation silently reject
  every post-HF2 transaction block via a swallowed exception in
  `multiprocess_validation.py`. Proposed fix: retype the field to
  `bytes`. This is a chia-blockchain design call, Arvid's area, and the
  conversation with him about it hasn't happened yet — see
  [Decision log](decisions.md).
- **Still nothing is activated.** `HARD_FORK2_HEIGHT` on chia-blockchain
  main is still the `0xFFFFFFFA` placeholder, chia_rs main does not yet
  include `INTERNED_GENERATOR` in the HF2 flag set (that flip is
  Arvid's), and current chia-blockchain main (#21249) still `std_hash`es
  v1 generator buffers — the tree-hash `generator_root` change described
  above is not live anywhere yet; it ships with the wiring PR once
  written. No post-HF2 blocks exist on any chain.

## 2026-08-13 — Entrance stack merged; emission and exit in review

*(superseded by the entry above — kept for history.)* The consensus core
was merged through #1438; #1439 (serde_2026 emission) was restacked on
main and green, waiting for a reviewer; the exit,
[chia-blockchain #20800](https://github.com/Chia-Network/chia-blockchain/pull/20800),
was a draft in merge conflict. Both #1439 and #20800 have since been
closed — see above.

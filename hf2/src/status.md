# Status

Living page. Dated entries, newest first.

## 2026-08-13 — Entrance stack merged; emission and exit in review

All PR states on this page verified live today.

- The consensus core is **merged**:
  [clvm_rs #708](https://github.com/Chia-Network/clvm_rs/pull/708)
  (format, released as clvmr 0.18.0),
  [chia_rs #1435](https://github.com/Chia-Network/chia_rs/pull/1435),
  [#1436](https://github.com/Chia-Network/chia_rs/pull/1436),
  [#1437](https://github.com/Chia-Network/chia_rs/pull/1437), and — the
  consensus-critical one, approved by Arvid —
  [#1438](https://github.com/Chia-Network/chia_rs/pull/1438) (2026-08-03).
- [#1439](https://github.com/Chia-Network/chia_rs/pull/1439) (serde_2026
  emission) is restacked on main and green, waiting for a reviewer.
  [#1491](https://github.com/Chia-Network/chia_rs/pull/1491)
  (builder-reset follow-up) is green and unreviewed.
  [#1500](https://github.com/Chia-Network/chia_rs/pull/1500) (trusted
  RPC readers) is a green draft carrying the open `Program`/Streamable
  question ([Decision log](decisions.md)).
- The exit, [chia-blockchain #20800](https://github.com/Chia-Network/chia-blockchain/pull/20800),
  is a draft in merge conflict — main advanced past its 08-10 rebase.
  Its 47 failing checks are the expected git-dep noise (wheel matrix,
  dependency-review, one coverage job), not regressions. Needs a rebase,
  a reviewer, and a team merge — I have no merge access there.
- **Nothing is activated.** `HARD_FORK2_HEIGHT` on chia-blockchain main
  is still the `0xFFFFFFFA` placeholder, and chia_rs main does not yet
  include `INTERNED_GENERATOR` in the HF2 flag set — that one-line change
  is the intended hand-off to Arvid ([Pathway](pathway.md)). No post-HF2
  blocks exist on any chain.

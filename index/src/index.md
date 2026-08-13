# Plans

Engineering plans, one small book per plan. I write these to force myself to
think before committing weeks of work, and so anyone reviewing (or just
wondering why I'm doing something) can follow the reasoning.

Each plan has the same shape:

1. **Problem** — what hurts, with numbers.
2. **Evidence** — experiments, how to rerun them, and the caveats.
3. **Target** — the design I'm aiming at.
4. **Pathway** — small reviewable steps, each with acceptance criteria and a
   rollback story.
5. **Decisions** — what I chose and why.
6. **Status** — dated notes on where things actually stand.

Caveats stay visible and open questions stay marked open. The status page
says what's *actually* done, not what I hoped would be done by now.

## Active plans

| Plan | Status | Summary |
|------|--------|---------|
| [Chia coin store: RocksDB migration](rocksdb/index.html) | **in progress** | Move the consensus coin store off SQLite onto RocksDB. Full-mainnet replay: 101 h on SQLite vs 13 h on RocksDB, worst in dust segments. |

## Drafts

| Plan | Status | Summary |
|------|--------|---------|
| [Chia mempool: generalized fast forward](gff/index.html) | **draft** | Remove singleton fast-forward from the node; user-space resolvers plus a bounded, relayed annex pool. No fork, all mempool policy. R1 measurements pending. |
| [Chia consensus: generator identity (HF2)](hf2/index.html) | **draft** | Generator identity becomes the interned tree hash, cost becomes interned vbytes, serde_2026 is the post-fork format with a mandatory fail-fast prefix. Entrance PRs merged; emission and exit in review. |

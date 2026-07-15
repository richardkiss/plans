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
| [Chia coin store: RocksDB migration](rocksdb/index.html) | **in progress** | Move the consensus coin store off SQLite onto RocksDB. Benchmarks show a ~40x engine gap that widens as the DB grows. |

## Drafts

Nothing here yet.

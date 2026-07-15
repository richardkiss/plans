# Plans

This site collects engineering plans as living documents — one small book per
plan. The point is to make significant technical decisions reviewable: by me
(Richard Kiss), before committing weeks of work, and by anyone else wondering
why a change is being made the way it is.

Each plan follows the same template:

1. **Problem** — what hurts, with numbers.
2. **Evidence** — experiments and measurements, including how to reproduce
   them and what the caveats are.
3. **Target** — the design we're aiming at.
4. **Pathway** — the sequence of small, reviewable steps to get there, each
   with acceptance criteria and a rollback story.
5. **Decisions** — a log of the choices made along the way and why.
6. **Status** — a dated, living record of where things stand.

Plans are honest by construction: caveats stay visible, open questions are
marked as open, and the status page says what is *actually* done rather than
what was hoped.

## Active plans

| Plan | Status | Summary |
|------|--------|---------|
| [Chia coin store: RocksDB migration](rocksdb/index.html) | **in progress** | Move the consensus coin store off SQLite onto RocksDB. Benchmarks show a ~40x engine gap that widens as the DB grows. |

## Drafts

Nothing here yet. Drafts will be listed in this section before they graduate
to active plans.

# plans

Engineering plans as living documents — one small [mdBook](https://rust-lang.github.io/mdBook/)
per plan, deployed to GitHub Pages at
[richardkiss.github.io/plans](https://richardkiss.github.io/plans/).

Each plan follows a fixed template: **Problem → Evidence → Target → Path →
Decisions → Status**. Tone is honest and evidence-first: caveats stay
visible, open questions are marked open.

## Layout

- `index/` — tiny landing book: the plan index and a drafts section.
- `rocksdb/` — the Chia coin store RocksDB migration plan.
- `rocksdb/spike/` — the benchmark harness behind the plan's evidence,
  packaged so it runs straight from GitHub:
  `uvx --from "git+https://github.com/richardkiss/plans#subdirectory=rocksdb/spike" spike-test`
  (see its [README](rocksdb/spike/README.md)).
- `theme/giscus.js` — shared comments include, loaded by every book via a
  symlink in each book directory (`theme/giscus.html` documents the
  canonical snippet).
- `.github/workflows/deploy.yml` — builds all books, assembles them into one
  site (`index` at the root, each plan under `/<plan>/`), and deploys to
  Pages.

## Building locally

Install mdBook (`cargo install mdbook`, or grab a
[release binary](https://github.com/rust-lang/mdBook/releases)), then:

```bash
mdbook serve index      # landing page at http://localhost:3000
mdbook serve rocksdb    # a plan book
```

To assemble the full site the way CI does:

```bash
mdbook build index && mdbook build rocksdb
mkdir -p _site/rocksdb
cp -r index/book/. _site/
cp -r rocksdb/book/. _site/rocksdb/
```

## Adding a plan

1. `mdbook init <name>` (or copy `rocksdb/` as a skeleton), symlink the
   shared comments script into it (`ln -s ../theme/giscus.js <name>/giscus.js`),
   and set `additional-js = ["giscus.js"]` in its `book.toml`.
2. Add build/assemble lines for it in `.github/workflows/deploy.yml`.
3. Link it from `index/src/index.md` (or its drafts section).

## Comments (giscus) — one-time setup

Comments are wired into every page via `theme/giscus.js`, but the include
**no-ops until the placeholder ids are filled in**, so it never blocks a
deploy. To activate:

1. Enable **Discussions** on this repo (Settings → General → Features).
2. Install the [giscus GitHub App](https://github.com/apps/giscus) on the
   repo.
3. Visit [giscus.app](https://giscus.app), enter `richardkiss/plans`, choose
   the mapping **pathname** and a discussion category (e.g. Announcements),
   and copy the generated `data-repo-id` and `data-category-id`.
4. Replace `PLACEHOLDER_REPO_ID` and `PLACEHOLDER_CATEGORY_ID` in
   `theme/giscus.js`, commit, push.

## Pages setup

The workflow uses the standard `actions/deploy-pages` flow, which requires
the repo's Pages source to be set to **GitHub Actions** (Settings → Pages →
Source, or `gh api repos/richardkiss/plans/pages -X POST -f
build_type=workflow`). One-time step.

**[agent draft — I haven't reviewed this text yet]**

# Migrations

Every step on the [pathway](pathway.md) that touches an existing node's
database has to answer the same question: someone upgrades a running node,
and the old database is on disk. This page covers the two steps that
actually move data, S11 (the chain index, if it happens) and S15 (the
RocksDB backend).

*(Revised 2026-11-03. The earlier version proposed a general four-kind
migrations framework, a background S15 build, and a "drain" that moved
SQLite rows out as they were copied. The review found the drain unsafe and
the background build unspecified. Both are below under "Considered and set
aside". A framework for one background job is premature.)*

## S15: offline, resumable conversion

The default is the shape `chia db upgrade` already has: stop the node,
convert, validate, switch.

- **Source:** one read snapshot of the SQLite database, with the node
  stopped and the converter holding the file exclusively (a lock file the
  node also checks), so nothing writes to it during conversion. Record its
  identity (network id, peak height and hash, schema version) in the
  destination before writing anything.
- **Streams:** creations ordered by `confirmed_index` and removals ordered
  by `spent_index`. Undo records and per-height aggregates need input
  grouped by height, so the sort is required. S15 keeps spent coins, so
  *every* coin record is copied, with its spent height. Every height gets a
  chain-index key and an undo record, including blocks without
  transactions. That's full undo coverage, the same as the spike's `rocks`
  backend. Retention and pruning come with S17. The spike's `merge_blocks` emits only heights with coin
  changes and synthesizes hashes, so it isn't the converter yet.
- **Resume:** each batch's progress marker is written in the same
  WriteBatch as the data it covers, so they can't disagree after a crash.
  A restart checks the source identity against the destination's, and
  starts over if it doesn't match. Resuming because an undo key exists
  isn't enough.
- **Validate before switching:** coin counts and spot checks, a
  chain-index entry for every height that chains by `prev_hash` up to the
  recorded peak, an undo record for every height, and an archive blob and
  block record for every height.
- **Switch:** flush and sync the destination, then write a
  backend-selection manifest (write a temp file, fsync it, rename it over
  the old one). Until the manifest names RocksDB, the node uses SQLite. The
  exclusive lock is released only after that.
- **Keep the old SQLite consensus state** as a named checkpoint. It isn't
  a current alternate backend, it's an old copy, and switching back means
  bringing it forward from its peak.

> **Open question C (Richard to decide): checkpoint layout.** The archive
> (`full_blocks`) stays in SQLite and keeps growing, and today it lives in
> the same file as the coin tables.
> 1. *Same file, coin tables frozen.* No extra disk. But the old code
>    can't simply replay: its `add_block` returns `ALREADY_HAVE_BLOCK` for
>    blocks already archived, and old flag-based readers would see stale
>    `in_main_chain` flags. Rolling back needs a tool that replays
>    archived blocks into the frozen coin tables.
> 2. *Separate files.* Split the archive into its own file at conversion
>    time. Clean rollback (the old file is intact), but the split costs a
>    copy of the archive, and preflight has to count it.

**Disk:** budget the whole existing SQLite file, plus the destination,
plus SQLite's WAL, plus RocksDB's compaction and build workspace. The
benchmark sizes (99.5 GB SQLite consensus-only vs 68.3 / 54.2 GB RocksDB)
come from coin-store experiments. They aren't a production whole-file
number. The real file also holds `full_blocks`, hints and the other
tables. Freed pages in a SQLite file never come back without a rewrite
(`VACUUM`), which rewrites the archive too. A second volume changes where
the space goes, not how much is needed. Preflight checks this before
starting.

Also worth measuring: this direct build from the two sorted streams,
against replaying every historical coin operation. The direct build is
likely much cheaper. (A lean S17 conversion would copy only unspent coins
plus the undo records for its retained window. That's a later step.)

## S11: filling the chain index in the node

This applies only if S11 ships. The data already exists: every
`full_blocks` row has `height` and `in_main_chain`.

- Copy `in_main_chain` rows into `chain_index` in height batches, one
  snapshot per batch. Check one row per height and `prev_hash` continuity
  in memory, the way BlockHeightMap loads windows today. Continuity also
  holds across batches: each batch's top row's hash is the `prev_hash` of
  the row at `low`.
- Keep a low-water mark `low` (rows exist for every height in
  `[low, peak]`) and commit it in the same transaction as each batch. At
  commit, re-read `low`. If it changed, discard the batch. A rollback that
  deletes rows below `low` lowers it to fork height + 1 in the same
  transaction.
- Make completion visible (a log line and `chia db validate`) before any
  reader trusts the table.
- S9 and S11 ship behind one schema version bump that older binaries
  refuse to open, so a binary that ignores `chain_index` can't leave it
  stale ([Pathway](pathway.md), S11).

A prototype of the `low` bookkeeping exists (commit `538677bcd6` on
`store-split-s9-5-chain-index-fill`, not pushed). It walks `prev_hash` one
awaited query per block. The bookkeeping is sound: a rollback below
`low - 1` changes `low` and the batch is discarded; a fork exactly at
`low - 1` leaves the ancestry being filled intact. But the walk is the slow
choice. It also trusts `MIN(height)` as proof of contiguity at bootstrap,
and doesn't check stored heights or the genesis block. Rebuild it on the
batch copy above if S11 goes ahead.

## Considered and set aside

**Background S15 build in phases.** Split `[0, peak]` into height ranges,
each with its own short snapshot, then catch up. It isn't wrong, but it's
not specified. Each phase needs an anchor hash and source identity,
progress made durable together with the destination, and ancestry checks
on restart. A reorg can delete source rows or move spends back to unspent,
and "spends after the first snapshot" isn't a change log for those
reversals. Revisit only if measured offline cost says it's needed.

**Draining SQLite into RocksDB.** From the start, all writes go to
RocksDB, reads try RocksDB and fall back to SQLite, and rows move out of
SQLite in the background. This is unsafe as written:

- In a spent-deleting store, a missing RocksDB key is ambiguous: either not
  copied yet, or deliberately spent. Falling back to SQLite resurrects
  spent coins unless durable tombstones shadow the source.
- A copy racing a spend can overwrite newer state.
- Deleting source rows is another crash-sensitive copy-then-delete step.
- Reorgs below the cutover height still need recovery, even if they're rare.
- "Delete the empty SQLite file" deletes the block archive, which lives in
  the same file.

## What migrates, by step

| Step | What migrates | How |
|---|---|---|
| S9 | `chain_index` table (DDL) | inline at open |
| S10 | nothing (interface only) | n/a |
| S11 | chain index fill; flag retirement | batched copy in the node; one-way schema gate |
| S12, S14 | nothing on disk | n/a |
| S13 | MMR nodes and frontier persisted (if chosen) | written by the node, rebuildable |
| S15 | RocksDB backend | offline, resumable, validated, manifest switch |
| S16 | ExplorerStore | rebuild from archive (deletable) |
| S17 | lean mode / undo window | in place, after fork-relative reads ship |

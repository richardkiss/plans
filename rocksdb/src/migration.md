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

- **Source:** one read snapshot of the SQLite database. Record its identity
  (network id, peak height and hash, schema version) in the destination
  before writing anything.
- **Streams:** creations ordered by `confirmed_index` and removals ordered
  by `spent_index`. Undo records and per-height aggregates need input
  grouped by height, so the sort is required. Every height gets a
  chain-index key and an undo record, including blocks without
  transactions. The spike's `merge_blocks` emits only heights with coin
  changes and synthesizes hashes, so it isn't the converter yet.
- **Resume:** progress is stored in the destination with the source
  identity next to it. A restart checks that both match, and starts over
  if they don't. Resuming because an undo key exists isn't enough.
- **Validate before switching:** coin counts and spot checks, a
  chain-index entry for every height that chains by `prev_hash` up to the
  recorded peak, undo coverage for the retained window, and an archive blob
  for every height.
- **Switch:** a durable backend-selection manifest, written last. Until it
  exists the node keeps using SQLite.
- **Keep the SQLite file** as a named checkpoint. Switching back means
  pointing the manifest at it and replaying forward from its peak. It isn't
  a current alternate backend, it's an old copy.

**Disk:** budget the whole existing SQLite file, plus the destination,
plus SQLite's WAL, plus RocksDB's compaction and build workspace. The
benchmark sizes (99.5 GB SQLite consensus-only vs 68.3 / 54.2 GB RocksDB)
come from coin-store experiments. They aren't a production whole-file
number. The real file also holds `full_blocks`, hints and the other
tables. Freed pages in a SQLite file never come back without a rewrite
(`VACUUM`), which rewrites the archive too. A second volume changes where
the space goes, not how much is needed. Preflight checks this before
starting.

Also worth measuring: building the coin state directly (unspent coins plus
the undo records for the retained window), against replaying every
historical coin operation. The direct build is likely much cheaper.

## S11: filling the chain index in the node

This applies only if S11 ships. The data already exists: every
`full_blocks` row has `height` and `in_main_chain`.

- Copy `in_main_chain` rows into `chain_index` in height batches, from one
  snapshot per batch. Check one row per height and `prev_hash` continuity
  in memory, the way BlockHeightMap loads windows today.
- Keep a low-water mark `low` (rows exist for every height in
  `[low, peak]`) in the same transaction as each batch. A rollback that
  deletes rows below `low` lowers it to fork height + 1 in the same
  transaction.
- Make completion visible (a log line and `chia db validate`) before any
  reader trusts the table.
- Mark the database so that a binary which ignores `chain_index` can't
  open it and later hand back a stale table. A one-way schema gate is
  simplest.

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
| S12-S14 | nothing on disk | n/a |
| S15 | RocksDB backend | offline, resumable, validated, manifest switch |
| S16 | ExplorerStore | rebuild from archive (deletable) |
| S17 | lean mode / undo window | in place, after fork-relative reads ship |

#!/usr/bin/env python3
"""
One-pass sqlite → RocksDB coin-store migration.

Two sorted cursors on a single read-only sqlite connection, merged by block
height, applied via process_spends. Resumes from the rocks peak (walking back
if the undo record is missing).
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import time
from pathlib import Path

import sqlite3

from coin_store import RocksLeanStore, RocksStore, create_store
from merge_blocks import merge_blocks

MAINNET_DB = Path(
    os.environ.get(
        "CHIA_MAINNET_DB",
        Path.home() / ".chia/mainnet/db/blockchain_v2_mainnet.sqlite",
    )
)
DEFAULT_DB_PATH = Path(os.environ.get("SPIKE_MIGRATE_DB", "migrate.rocks"))
HEARTBEAT_FILE = os.environ.get("SPIKE_HEARTBEAT_FILE")
DEFAULT_BACKEND = os.environ.get("SPIKE_MIGRATE_BACKEND", "rocks")


def update_heartbeat(msg: str, status: str = "running") -> None:
    if not HEARTBEAT_FILE:
        return
    ts = int(time.time())
    Path(HEARTBEAT_FILE).write_text(f"ts={ts}\nstatus={status}\nmsg={msg}\n")


def undo_block_exists(store: RocksStore | RocksLeanStore, height: int) -> bool:
    return store.db.get(b"b" + struct.pack(">I", height)) is not None


def resolve_checkpoint(store: RocksStore | RocksLeanStore) -> int:
    """Last fully-applied block height, or -1 if empty.

    Start from peak ``p`` and walk backward until ``b{height}`` exists.
    """
    peak = store.peak()
    if peak is None:
        return -1

    height = peak[0]
    while height >= 0:
        if undo_block_exists(store, height):
            return height
        height -= 1
    return -1


def prepare_store(store: RocksStore | RocksLeanStore) -> int:
    """Align rocks state with the checkpoint and return ``after_height``."""
    checkpoint = resolve_checkpoint(store)
    peak = store.peak()
    if peak is not None and peak[0] > checkpoint:
        if checkpoint < 0:
            print(
                "  WARNING: peak set but no undo blocks found; "
                "rewinding to genesis",
                file=sys.stderr,
            )
            store.rewind_to_block(0)
            checkpoint = resolve_checkpoint(store)
        else:
            print(
                f"  Peak {peak[0]:,} ahead of undo checkpoint {checkpoint:,}; "
                f"rewinding to {checkpoint:,}",
            )
            store.rewind_to_block(checkpoint)
    return checkpoint


def open_mainnet_sqlite(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"Mainnet DB not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = 1")
    return conn


def migrate(
    *,
    sqlite_path: Path,
    rocks_path: Path,
    backend: str,
    max_height: int | None,
    dry_run: bool,
) -> None:
    if backend not in ("rocks", "rocks-lean"):
        raise ValueError(f"migrate supports rocks backends only, not {backend!r}")

    print("One-pass sqlite → rocks migration")
    print("=" * 60)
    print(f"  Source:  {sqlite_path}")
    print(f"  Target:  {rocks_path} ({backend})")
    if max_height is not None:
        print(f"  Height limit: {max_height:,}")
    if dry_run:
        print("  Mode: dry-run (no writes)")
    print()

    conn = open_mainnet_sqlite(sqlite_path)
    store = None
    after_height = -1

    try:
        if not dry_run:
            store = create_store(backend, rocks_path)
            assert isinstance(store, (RocksStore, RocksLeanStore))
            after_height = prepare_store(store)
            if after_height >= 0:
                print(f"  Resuming after block {after_height:,}")
            else:
                print("  Starting from genesis")
            print()

        blocks = 0
        creations = 0
        spends = 0
        start_time = time.time()
        last_update = start_time

        for height, timestamp, block_hash, created, spent in merge_blocks(
            conn, after_height, max_height
        ):
            if dry_run:
                blocks += 1
                creations += len(created)
                spends += len(spent)
            else:
                assert store is not None
                store.process_spends(
                    height, block_hash, timestamp, created, spent
                )
                blocks += 1
                creations += len(created)
                spends += len(spent)

            now = time.time()
            if blocks % 10_000 == 0 and now - last_update >= 10:
                elapsed = now - start_time
                rate = blocks / elapsed if elapsed else 0.0
                print(
                    f"  Block {height:,} — {blocks:,} blocks, "
                    f"{rate:.0f} blocks/sec"
                )
                update_heartbeat(f"{'Dry-run' if dry_run else 'Migrate'}: height {height:,}")
                last_update = now

        elapsed = time.time() - start_time
        print()
        print("Migration complete!" if not dry_run else "Dry-run complete!")
        print(f"  Blocks:    {blocks:,}")
        print(f"  Creations: {creations:,}")
        print(f"  Spends:    {spends:,}")
        print(f"  Elapsed:   {elapsed:.1f}s")
        if not dry_run and store is not None:
            peak = store.peak()
            if peak:
                print(f"  Peak:      {peak[0]:,}")
        update_heartbeat(
            f"{'Dry-run' if dry_run else 'Migrate'} complete: {blocks:,} blocks",
            status="done",
        )

    finally:
        conn.close()
        if store is not None:
            store.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-pass sqlite → RocksDB coin store migration",
    )
    parser.add_argument(
        "max_height",
        nargs="?",
        type=int,
        default=None,
        help="Optional upper block height (inclusive)",
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=MAINNET_DB,
        help="Chia mainnet sqlite path (default: CHIA_MAINNET_DB or ~/.chia/...)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="RocksDB output path (default: migrate.rocks or SPIKE_MIGRATE_DB)",
    )
    parser.add_argument(
        "--backend",
        choices=("rocks", "rocks-lean"),
        default=DEFAULT_BACKEND,
        help="Rocks backend (default: rocks)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Merge streams only; do not write to rocks",
    )
    args = parser.parse_args()

    update_heartbeat("Starting migration")
    migrate(
        sqlite_path=args.sqlite,
        rocks_path=args.db_path,
        backend=args.backend,
        max_height=args.max_height,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()

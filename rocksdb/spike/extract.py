#!/usr/bin/env python3
"""
Extract per-block coin deltas from Chia mainnet DB into a compressed binary format.

One-pass: two sorted sqlite cursors merged by height (see merge_blocks.py).
"""
from __future__ import annotations

import os
import sqlite3
import struct
import sys
import time
from pathlib import Path

import zstandard as zstd

from extract_format import write_block
from merge_blocks import merge_blocks_extract

MAINNET_DB = Path(
    os.environ.get(
        "CHIA_MAINNET_DB",
        Path.home() / ".chia/mainnet/db/blockchain_v2_mainnet.sqlite",
    )
)
OUTPUT_FILE = Path("extract.dat.zst")
HEARTBEAT_FILE = os.environ.get("SPIKE_HEARTBEAT_FILE")


def update_heartbeat(msg: str, status: str = "running") -> None:
    if not HEARTBEAT_FILE:
        return
    ts = int(time.time())
    Path(HEARTBEAT_FILE).write_text(f"ts={ts}\nstatus={status}\nmsg={msg}\n")


def format_bytes(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def pct(count: int, total: int | None) -> str:
    return f" ({100 * count / total:.1f}%)" if total else ""


def open_mainnet_sqlite(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = 1")
    return conn


def scan_last_height(path: Path) -> int | None:
    """Return the highest block height in an existing extract.dat.zst, or None."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    last_height = None
    with open(path, "rb") as f:
        dctx = zstd.ZstdDecompressor()
        with dctx.stream_reader(f) as reader:
            while True:
                header = reader.read(16)
                if not header or len(header) < 16:
                    break
                height, _timestamp, n_created = struct.unpack(">IQI", header)
                last_height = height
                reader.read(105 * n_created)
                n_spent = struct.unpack(">I", reader.read(4))[0]
                reader.read(32 * n_spent)
    return last_height


def extract_onepass(
    conn: sqlite3.Connection,
    output_file: Path,
    max_height: int | None,
    *,
    resume: bool = False,
) -> tuple[int, int, int]:
    """Write extract.dat.zst in one pass. Returns (blocks_written, creations, spends)."""
    after_height = -1
    if resume and output_file.exists():
        last = scan_last_height(output_file)
        if last is not None:
            after_height = last
            print(f"  Resuming after block {after_height:,}")

    tmp_output = output_file.with_suffix(".zst.tmp")
    compressor = zstd.ZstdCompressor(level=3, threads=-1)

    blocks_written = 0
    created_count = 0
    spent_count = 0
    start_time = time.time()
    last_update = start_time

    with open(tmp_output, "wb") as f:
        with compressor.stream_writer(f) as writer:
            if after_height >= 0 and resume and output_file.exists():
                with open(output_file, "rb") as existing:
                    dctx = zstd.ZstdDecompressor()
                    with dctx.stream_reader(existing) as reader:
                        while True:
                            header = reader.read(16)
                            if not header or len(header) < 16:
                                break
                            height, timestamp, n_created = struct.unpack(">IQI", header)
                            created_records = [reader.read(105) for _ in range(n_created)]
                            n_spent = struct.unpack(">I", reader.read(4))[0]
                            spent_ids = [reader.read(32) for _ in range(n_spent)]
                            write_block(writer, height, timestamp, created_records, spent_ids)
                            blocks_written += 1
                            created_count += n_created
                            spent_count += n_spent
                            if height >= after_height:
                                break

            for height, timestamp, created_records, spent in merge_blocks_extract(
                conn, after_height, max_height
            ):
                write_block(writer, height, timestamp, created_records, spent)
                blocks_written += 1
                created_count += len(created_records)
                spent_count += len(spent)

                if blocks_written % 10_000 == 0:
                    now = time.time()
                    if now - last_update >= 10:
                        progress = pct(height, max_height)
                        print(
                            f"  Written {blocks_written:,} blocks - "
                            f"height {height:,}{progress}"
                        )
                        update_heartbeat(
                            f"Extract: {blocks_written:,} blocks, height {height:,}{progress}"
                        )
                        last_update = now

    tmp_output.replace(output_file)
    elapsed = time.time() - start_time
    print(
        f"  Complete: {blocks_written:,} blocks in {elapsed:.1f}s "
        f"({blocks_written / elapsed:.0f} blocks/sec)"
    )
    return blocks_written, created_count, spent_count


def main() -> None:
    max_height = int(sys.argv[1]) if len(sys.argv) > 1 else None
    resume = os.environ.get("SPIKE_EXTRACT_RESUME") == "1"

    print("Phase A: Extraction")
    print("=" * 60)

    conn = open_mainnet_sqlite(MAINNET_DB)
    cursor = conn.cursor()

    peak_height = max_height
    if max_height:
        cursor.execute(
            "SELECT COUNT(*) FROM coin_record WHERE confirmed_index <= ?",
            (max_height,),
        )
        total_coins = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM coin_record WHERE spent_index > 0 AND spent_index <= ?",
            (max_height,),
        )
        total_spends = cursor.fetchone()[0]
        print(f"Total coins (up to height {max_height:,}): {total_coins:,}")
        print(f"Total spends (up to height {max_height:,}): {total_spends:,}")
    else:
        cursor.execute("SELECT COUNT(*) FROM coin_record")
        total_coins = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM coin_record WHERE spent_index > 0")
        total_spends = cursor.fetchone()[0]
        cursor.execute("SELECT MAX(confirmed_index) FROM coin_record")
        peak_height = cursor.fetchone()[0]
        print(f"Total coins: {total_coins:,}")
        print(f"Total spends: {total_spends:,}")
        print(f"Peak height: {peak_height:,}")

    print()
    update_heartbeat("Starting extraction")

    blocks_written, created_count, spent_count = extract_onepass(
        conn, OUTPUT_FILE, max_height, resume=resume
    )
    conn.close()

    print()
    print("Verification:")
    print(f"  Total creations: {created_count:,} (expected {total_coins:,})")
    print(f"  Total spends: {spent_count:,} (expected {total_spends:,})")
    assert created_count == total_coins, "Creation count mismatch"
    assert spent_count == total_spends, "Spend count mismatch"
    print("  ✓ Counts match")
    print()
    print("Extraction complete!")
    print(f"  Output: {OUTPUT_FILE}")
    print(f"  Size: {format_bytes(OUTPUT_FILE.stat().st_size)}")
    print(f"  Blocks: {blocks_written:,}")
    print(f"  Total coins: {created_count:,}")
    print(f"  Total spends: {spent_count:,}")
    update_heartbeat(
        f"Phase A complete: {blocks_written:,} blocks, "
        f"{format_bytes(OUTPUT_FILE.stat().st_size)}"
    )


if __name__ == "__main__":
    main()

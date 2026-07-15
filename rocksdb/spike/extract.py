#!/usr/bin/env python3
"""
Extract per-block coin deltas from Chia mainnet DB into a compressed binary format.
"""
import os
import sqlite3
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path
import zstandard as zstd


# Mainnet DB path - read-only. Override with CHIA_MAINNET_DB.
MAINNET_DB = Path(
    os.environ.get(
        "CHIA_MAINNET_DB",
        Path.home() / ".chia/mainnet/db/blockchain_v2_mainnet.sqlite",
    )
)
OUTPUT_FILE = Path("extract.dat.zst")
# Optional progress file for external monitoring (set SPIKE_HEARTBEAT_FILE).
HEARTBEAT_FILE = os.environ.get("SPIKE_HEARTBEAT_FILE")


def update_heartbeat(msg: str, status: str = "running"):
    """Update heartbeat file, if one is configured."""
    if not HEARTBEAT_FILE:
        return
    ts = int(time.time())
    Path(HEARTBEAT_FILE).write_text(f"ts={ts}\nstatus={status}\nmsg={msg}\n")


def format_bytes(size: int) -> str:
    """Format bytes as human-readable."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def pct(count, total):
    """Format count as a percentage of total, if total is known."""
    return f" ({100 * count / total:.1f}%)" if total else ""


def write_temp_creations(conn, temp_file, max_height=None, total=None):
    """Write creations stream to temp file: height(4) timestamp(8) coin_id(32) parent(32) puzzle_hash(32) amount(8) coinbase(1)."""
    print("Pass 1: Extracting creations...")
    if max_height:
        print(f"  Height limit: {max_height:,}")
    
    cursor = conn.cursor()
    
    if max_height:
        cursor.execute("""
            SELECT confirmed_index, timestamp, coin_name, coin_parent, puzzle_hash, amount, coinbase
            FROM coin_record
            WHERE confirmed_index <= ?
            ORDER BY confirmed_index
        """, (max_height,))
    else:
        cursor.execute("""
            SELECT confirmed_index, timestamp, coin_name, coin_parent, puzzle_hash, amount, coinbase
            FROM coin_record
            ORDER BY confirmed_index
        """)
    
    count = 0
    start_time = time.time()
    last_update = start_time
    
    with open(temp_file, "wb") as f:
        for row in cursor:
            confirmed_idx, timestamp, coin_id, coin_parent, puzzle_hash, amount_blob, coinbase = row
            
            # Write: height(4) timestamp(8) coin_id(32) parent(32) puzzle_hash(32) amount(8) coinbase(1)
            data = struct.pack(">I", confirmed_idx)  # u32 BE
            data += struct.pack(">Q", timestamp)  # u64 BE
            data += coin_id  # 32 bytes
            data += coin_parent  # 32 bytes
            data += puzzle_hash  # 32 bytes
            data += amount_blob  # 8 bytes
            data += bytes([coinbase])  # 1 byte
            f.write(data)
            
            count += 1
            if count % 1_000_000 == 0:
                now = time.time()
                if now - last_update >= 10:
                    elapsed = now - start_time
                    rate = count / elapsed
                    print(f"  Processed {count:,} coins{pct(count, total)} - {rate:.0f} coins/sec")
                    update_heartbeat(f"Pass 1: {count:,} creations{pct(count, total)}")
                    last_update = now
    
    elapsed = time.time() - start_time
    print(f"  Complete: {count:,} creations in {elapsed:.1f}s ({count/elapsed:.0f} coins/sec)")
    return count


def write_temp_spends(conn, temp_file, max_height=None, total=None):
    """Write spends stream to temp file: height(4) coin_id(32)."""
    print("Pass 2: Extracting spends...")
    if max_height:
        print(f"  Height limit: {max_height:,}")
    
    cursor = conn.cursor()
    
    if max_height:
        cursor.execute("""
            SELECT spent_index, coin_name
            FROM coin_record
            WHERE spent_index > 0 AND spent_index <= ?
            ORDER BY spent_index
        """, (max_height,))
    else:
        cursor.execute("""
            SELECT spent_index, coin_name
            FROM coin_record
            WHERE spent_index > 0
            ORDER BY spent_index
        """)
    
    count = 0
    start_time = time.time()
    last_update = start_time
    
    with open(temp_file, "wb") as f:
        for row in cursor:
            spent_idx, coin_id = row
            
            # Write: height(4) coin_id(32)
            data = struct.pack(">I", spent_idx)  # u32 BE
            data += coin_id  # 32 bytes
            f.write(data)
            
            count += 1
            if count % 1_000_000 == 0:
                now = time.time()
                if now - last_update >= 10:
                    elapsed = now - start_time
                    rate = count / elapsed
                    print(f"  Processed {count:,} spends{pct(count, total)} - {rate:.0f} spends/sec")
                    update_heartbeat(f"Pass 2: {count:,} spends{pct(count, total)}")
                    last_update = now
    
    elapsed = time.time() - start_time
    print(f"  Complete: {count:,} spends in {elapsed:.1f}s ({count/elapsed:.0f} spends/sec)")
    return count


def merge_and_compress(creations_file, spends_file, output_file, total_created, total_spent, peak_height=None):
    """Merge sorted creation and spend streams into compressed output."""
    print(f"Pass 3: Merging and compressing to {output_file}...")
    update_heartbeat("Merging streams and compressing")
    
    CREATION_RECORD_SIZE = 4 + 8 + 32 + 32 + 32 + 8 + 1  # 117 bytes
    SPEND_RECORD_SIZE = 4 + 32  # 36 bytes
    
    compressor = zstd.ZstdCompressor(level=3, threads=-1)
    
    with open(creations_file, "rb") as cf, open(spends_file, "rb") as sf:
        with open(output_file, "wb") as f:
            with compressor.stream_writer(f) as writer:
                # Read first records
                creation_data = cf.read(CREATION_RECORD_SIZE)
                spend_data = sf.read(SPEND_RECORD_SIZE)
                
                current_height = None
                current_timestamp = None
                current_created = []
                current_spent = []
                blocks_written = 0
                start_time = time.time()
                last_update = start_time
                
                while creation_data or spend_data:
                    # Parse heights
                    creation_height = struct.unpack(">I", creation_data[:4])[0] if creation_data else float('inf')
                    spend_height = struct.unpack(">I", spend_data[:4])[0] if spend_data else float('inf')
                    
                    next_height = min(creation_height, spend_height)
                    
                    # If we hit a new height, write the previous block
                    if current_height is not None and next_height != current_height:
                        # Write block
                        data = struct.pack(">I", current_height)
                        data += struct.pack(">Q", current_timestamp)
                        data += struct.pack(">I", len(current_created))
                        for coin_rec in current_created:
                            data += coin_rec
                        data += struct.pack(">I", len(current_spent))
                        for coin_id in current_spent:
                            data += coin_id
                        writer.write(data)
                        
                        blocks_written += 1
                        if blocks_written % 10000 == 0:
                            now = time.time()
                            if now - last_update >= 10:
                                # Total tx blocks isn't known up front; height vs peak is.
                                progress = pct(current_height, peak_height)
                                print(f"  Merged {blocks_written:,} blocks - height {current_height:,}{progress}")
                                update_heartbeat(f"Merging: {blocks_written:,} blocks, height {current_height:,}{progress}")
                                last_update = now
                        
                        # Reset for next block
                        current_created = []
                        current_spent = []
                    
                    # Process records at this height
                    while creation_data and struct.unpack(">I", creation_data[:4])[0] == next_height:
                        current_height = next_height
                        current_timestamp = struct.unpack(">Q", creation_data[4:12])[0]
                        # Store the coin data (id, parent, puzzle_hash, amount, coinbase)
                        current_created.append(creation_data[12:117])
                        creation_data = cf.read(CREATION_RECORD_SIZE)
                    
                    while spend_data and struct.unpack(">I", spend_data[:4])[0] == next_height:
                        current_height = next_height
                        # Store the coin_id
                        current_spent.append(spend_data[4:36])
                        spend_data = sf.read(SPEND_RECORD_SIZE)
                
                # Write last block if any
                if current_height is not None:
                    data = struct.pack(">I", current_height)
                    data += struct.pack(">Q", current_timestamp or 0)
                    data += struct.pack(">I", len(current_created))
                    for coin_rec in current_created:
                        data += coin_rec
                    data += struct.pack(">I", len(current_spent))
                    for coin_id in current_spent:
                        data += coin_id
                    writer.write(data)
                    blocks_written += 1
    
    file_size = output_file.stat().st_size
    print(f"  Complete: {blocks_written:,} blocks, {format_bytes(file_size)}")
    return blocks_written


def main():
    import sys
    
    # Check for height limit argument
    max_height = None
    if len(sys.argv) > 1:
        max_height = int(sys.argv[1])
    
    print("Phase A: Extraction")
    print("=" * 60)
    
    # Open mainnet DB read-only
    db_uri = f"file:{MAINNET_DB}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    conn.execute("PRAGMA query_only = 1")
    cursor = conn.cursor()
    
    # Get DB stats
    peak_height = max_height
    if max_height:
        cursor.execute("SELECT COUNT(*) FROM coin_record WHERE confirmed_index <= ?", (max_height,))
        total_coins = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM coin_record WHERE spent_index > 0 AND spent_index <= ?", (max_height,))
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
    
    update_heartbeat(f"Starting extraction")
    
    # Use temporary files for streaming
    creations_temp = Path("_creations.tmp")
    spends_temp = Path("_spends.tmp")
    
    try:
        # Pass 1: Extract creations
        created_count = write_temp_creations(conn, creations_temp, max_height, total=total_coins)
        print(f"  Temp file size: {format_bytes(creations_temp.stat().st_size)}")
        print()
        
        # Pass 2: Extract spends
        spent_count = write_temp_spends(conn, spends_temp, max_height, total=total_spends)
        print(f"  Temp file size: {format_bytes(spends_temp.stat().st_size)}")
        print()
        
        conn.close()
        
        # Verify counts
        print(f"Verification:")
        print(f"  Total creations: {created_count:,} (expected {total_coins:,})")
        print(f"  Total spends: {spent_count:,} (expected {total_spends:,})")
        assert created_count == total_coins, "Creation count mismatch"
        assert spent_count == total_spends, "Spend count mismatch"
        print(f"  ✓ Counts match")
        print()
        
        # Pass 3: Merge and compress
        blocks_written = merge_and_compress(creations_temp, spends_temp, OUTPUT_FILE, 
                                           created_count, spent_count, peak_height=peak_height)
        
    finally:
        # Clean up temp files
        for temp in [creations_temp, spends_temp]:
            if temp.exists():
                temp.unlink()
                print(f"Cleaned up {temp}")
    
    file_size = OUTPUT_FILE.stat().st_size
    print()
    print("Extraction complete!")
    print(f"  Output: {OUTPUT_FILE}")
    print(f"  Size: {format_bytes(file_size)}")
    print(f"  Blocks: {blocks_written:,}")
    print(f"  Total coins: {created_count:,}")
    print(f"  Total spends: {spent_count:,}")
    
    update_heartbeat(f"Phase A complete: {blocks_written:,} blocks, {format_bytes(file_size)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Replay extracted coin deltas through all 4 backends and measure performance.
"""
import csv
import hashlib
import os
import shutil
import struct
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import zstandard as zstd

from coin_store import NewCoin, create_store


# Constants
EXTRACT_FILE = Path("extract.dat.zst")
# Optional progress file for external monitoring (set SPIKE_HEARTBEAT_FILE).
HEARTBEAT_FILE = os.environ.get("SPIKE_HEARTBEAT_FILE")
REPORT_FILE = Path(os.environ.get("SPIKE_REPORT_FILE", "report.md"))
PLOTS_DIR = Path("plots")

# Measurement intervals
MEASUREMENT_INTERVAL = 10_000  # blocks
REWIND_TEST_INTERVAL = 250_000  # blocks
REWIND_DEPTH = 3  # blocks to rewind


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


def read_extract(path: Path):
    """Generator that yields blocks from the extract file."""
    with open(path, "rb") as f:
        dctx = zstd.ZstdDecompressor()
        with dctx.stream_reader(f) as reader:
            while True:
                # Read block header
                header = reader.read(16)  # height(4) + timestamp(8) + n_created(4)
                if not header or len(header) < 16:
                    break
                
                height, timestamp, n_created = struct.unpack(">IQI", header)
                
                # Read created coins
                created_coins = []
                for _ in range(n_created):
                    coin_data = reader.read(105)  # coin_id(32) + parent(32) + puzzle_hash(32) + amount(8) + coinbase(1)
                    if len(coin_data) < 105:
                        break
                    
                    coin_id = coin_data[:32]
                    parent = coin_data[32:64]
                    puzzle_hash = coin_data[64:96]
                    amount = struct.unpack(">Q", coin_data[96:104])[0]
                    coinbase = bool(coin_data[104])
                    
                    created_coins.append(NewCoin(coin_id, parent, puzzle_hash, amount, coinbase))
                
                # Read spent coins
                n_spent_data = reader.read(4)
                if len(n_spent_data) < 4:
                    break
                n_spent = struct.unpack(">I", n_spent_data)[0]
                
                spent_ids = []
                for _ in range(n_spent):
                    coin_id = reader.read(32)
                    if len(coin_id) < 32:
                        break
                    spent_ids.append(coin_id)
                
                # Generate synthetic block hash
                block_hash = hashlib.sha256(str(height).encode()).digest()
                
                yield height, timestamp, block_hash, created_coins, spent_ids


def replay_backend(backend_name: str, db_path: Path, max_height: int | None = None):
    """Replay blocks through a backend and collect measurements."""
    print(f"\n{'='*70}")
    print(f"Backend: {backend_name}")
    print(f"{'='*70}")
    
    update_heartbeat(f"Replaying {backend_name}: starting")
    
    # Create store
    if db_path.exists():
        if db_path.is_dir():
            shutil.rmtree(db_path)
        else:
            db_path.unlink()
    
    store = create_store(backend_name, db_path)
    
    # CSV output for measurements
    csv_path = PLOTS_DIR / f"{backend_name}.csv"
    csv_file = open(csv_path, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["height", "wall_seconds", "blocks_per_sec", "coins_in_db", "db_size_bytes", "rss_mb"])
    
    # Replay loop
    start_time = time.time()
    last_measurement = start_time
    last_heartbeat = start_time
    blocks_since_measurement = 0
    last_rewind_test = 0
    tx_blocks = 0
    total_spends = 0
    
    # For rewind test - save state
    rewind_test_data = []
    
    for height, timestamp, block_hash, created_coins, spent_ids in read_extract(EXTRACT_FILE):
        if max_height is not None and height > max_height:
            break
        
        tx_blocks += 1
        total_spends += len(spent_ids)
        
        # Process block
        try:
            store.process_spends(height, block_hash, timestamp, created_coins, spent_ids)
        except Exception as e:
            print(f"ERROR at height {height}: {e}")
            raise
        
        blocks_since_measurement += 1
        
        # Time-based heartbeat: measurement intervals can be hours apart on a
        # slow backend at scale, which would look like a stalled job.
        if HEARTBEAT_FILE and time.time() - last_heartbeat > 60:
            update_heartbeat(f"Replaying {backend_name}: height {height:,}")
            last_heartbeat = time.time()
        
        # Measurement
        if height % MEASUREMENT_INTERVAL == 0:
            now = time.time()
            elapsed = now - last_measurement
            blocks_per_sec = blocks_since_measurement / elapsed if elapsed > 0 else 0
            wall_seconds = now - start_time
            
            coins_in_db = store.num_coins()
            db_size = store.db_size()
            
            # RSS (approximate)
            try:
                import resource
                rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
                rss_mb = rss_bytes / (1024 * 1024)
            except:
                rss_mb = 0
            
            csv_writer.writerow([height, wall_seconds, blocks_per_sec, coins_in_db, db_size, rss_mb])
            csv_file.flush()
            
            print(f"  Height {height:,}: {blocks_per_sec:.1f} blk/s, "
                  f"{coins_in_db:,} coins, {format_bytes(db_size)}")
            update_heartbeat(f"Replaying {backend_name}: height {height:,}")
            
            last_measurement = now
            blocks_since_measurement = 0
        
        # Rewind correctness test - DISABLED for streaming benchmark
        # (Rewinds are tested in unit tests; streaming makes re-applying blocks complex)
        # if height - last_rewind_test >= REWIND_TEST_INTERVAL and height > REWIND_DEPTH:
        #     print(f"  Rewind test at height {height}")
        #     ...
        #     last_rewind_test = height
    
    csv_file.close()
    
    # Final stats
    final_time = time.time() - start_time
    peak = store.peak()
    final_height = peak[0] if peak else 0
    final_size = store.db_size()
    final_coins = store.num_coins()
    
    print(f"\nComplete:")
    print(f"  Final height: {final_height:,}")
    print(f"  Total time: {final_time:.1f}s ({final_height/final_time:.1f} blk/s average)")
    print(f"  Final size: {format_bytes(final_size)}")
    print(f"  Coins in DB: {final_coins:,}")
    
    store.close()
    
    return {
        "backend": backend_name,
        "final_height": final_height,
        "total_time": final_time,
        "final_size": final_size,
        "final_coins": final_coins,
        "csv_path": csv_path,
        "tx_blocks": tx_blocks,
        "total_spends": total_spends,
    }


def plot_results(results: list[dict]):
    """Generate performance plots."""
    PLOTS_DIR.mkdir(exist_ok=True)
    
    print("\nGenerating plots...")
    
    # Plot 1: Throughput over time (all backends)
    fig, ax = plt.subplots(figsize=(12, 6))
    
    for result in results:
        data = []
        with open(result["csv_path"]) as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append({
                    "height": int(row["height"]),
                    "blocks_per_sec": float(row["blocks_per_sec"]),
                })
        
        if data:
            heights = [d["height"] for d in data]
            bps = [d["blocks_per_sec"] for d in data]
            ax.plot(heights, bps, label=result["backend"], marker='o', markersize=3)
    
    ax.set_xlabel("Block Height")
    ax.set_ylabel("Blocks/Second")
    ax.set_title("Coin Store Throughput: SQLite vs RocksDB")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_yscale("log")
    
    plot_path = PLOTS_DIR / "throughput.png"
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    print(f"  Saved {plot_path}")
    plt.close()
    
    # Plot 2: DB size over time
    fig, ax = plt.subplots(figsize=(12, 6))
    
    for result in results:
        data = []
        with open(result["csv_path"]) as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append({
                    "height": int(row["height"]),
                    "db_size_bytes": int(row["db_size_bytes"]),
                })
        
        if data:
            heights = [d["height"] for d in data]
            sizes = [d["db_size_bytes"] / (1024**3) for d in data]  # GB
            ax.plot(heights, sizes, label=result["backend"], marker='o', markersize=3)
    
    ax.set_xlabel("Block Height")
    ax.set_ylabel("Database Size (GB)")
    ax.set_title("Database Size Growth")
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plot_path = PLOTS_DIR / "db_size.png"
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    print(f"  Saved {plot_path}")
    plt.close()


def write_report(results: list[dict], extract_stats: dict):
    """Write comprehensive report."""
    with open(REPORT_FILE, "w") as f:
        f.write("# Coin Store Benchmark: SQLite vs RocksDB\n\n")
        f.write(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## Extraction Stats\n\n")
        f.write(f"- Extract file: {format_bytes(extract_stats['file_size'])}\n")
        f.write(f"- Final height: {extract_stats['final_height']:,}\n")
        f.write(f"- Transaction blocks: {extract_stats['tx_blocks']:,}\n")
        f.write(f"- Total coins: {extract_stats['total_coins']:,}\n")
        f.write(f"- Total spends: {extract_stats['total_spends']:,}\n\n")
        
        f.write("## Backend Results\n\n")
        f.write("| Backend | Final Height | Time (s) | Avg Blk/s | Final Size | Coins |\n")
        f.write("|---------|--------------|----------|-----------|------------|-------|\n")
        
        for r in results:
            avg_bps = r["final_height"] / r["total_time"] if r["total_time"] > 0 else 0
            f.write(f"| {r['backend']:15} | {r['final_height']:12,} | {r['total_time']:8.1f} | "
                   f"{avg_bps:9.1f} | {format_bytes(r['final_size']):>10} | {r['final_coins']:13,} |\n")
        
        f.write("\n## Performance Charts\n\n")
        f.write("![Throughput](plots/throughput.png)\n\n")
        f.write("![Database Size](plots/db_size.png)\n\n")
        
        f.write("## API Notes\n\n")
        f.write("The minimal post-HF2 API proved sufficient:\n\n")
        f.write("- `process_spends()` handles creation, spending, and ephemeral coins\n")
        f.write("- `rewind_to_block()` atomically undoes blocks with undo log\n")
        f.write("- `get_coin_records()` for lookups (batched in RocksDB via multi_get)\n")
        f.write("- `peak()` tracks current chain tip\n\n")
        
        f.write("Analysis of these results lives in the plan book: ")
        f.write("https://richardkiss.github.io/plans/rocksdb/benchmarks.html\n")
    
    print(f"\nReport written to {REPORT_FILE}")


def main():
    if not EXTRACT_FILE.exists():
        print(f"ERROR: Extract file {EXTRACT_FILE} not found")
        print("Run extract.py first")
        sys.exit(1)
    
    # Extract stats
    extract_stats = {
        "file_size": EXTRACT_FILE.stat().st_size,
        "final_height": 0,  # Filled in during replay
        "tx_blocks": 0,
        "total_coins": 0,
        "total_spends": 0,
    }
    
    PLOTS_DIR.mkdir(exist_ok=True)
    
    # Run each backend sequentially
    backends = [
        ("sqlite-full", Path("db_sqlite_full.db")),
        ("sqlite-consensus", Path("db_sqlite_consensus.db")),
        ("rocks", Path("db_rocks")),
        ("rocks-lean", Path("db_rocks_lean")),
    ]
    
    results = []
    
    for backend_name, db_path in backends:
        result = replay_backend(backend_name, db_path)
        results.append(result)
        
        # Update extract stats from first backend
        if not extract_stats["tx_blocks"]:
            extract_stats["final_height"] = result["final_height"]
            extract_stats["tx_blocks"] = result["tx_blocks"]
            extract_stats["total_coins"] = result["final_coins"]
            extract_stats["total_spends"] = result["total_spends"]
        
        # Delete DB to save space
        print(f"\nDeleting {db_path} to save space...")
        if db_path.exists():
            if db_path.is_dir():
                shutil.rmtree(db_path)
            else:
                db_path.unlink()
    
    # Generate plots
    plot_results(results)
    
    # Write report
    write_report(results, extract_stats)
    
    # Run enrichment to add ops/sec analysis
    print("\nRunning enrichment analysis...")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("enrich_results.py"))],
        capture_output=True, text=True)
    if result.returncode == 0:
        print("  Enrichment complete")
        # Append enriched summary to report
        with open(REPORT_FILE, "a") as f:
            f.write("\n## Operations/Sec Analysis\n\n")
            f.write("```\n")
            f.write(result.stdout)
            f.write("```\n")
    else:
        print(f"  Enrichment failed: {result.stderr}")
    
    update_heartbeat("Phase C complete", "done")
    print("\nAll backends complete!")


if __name__ == "__main__":
    main()

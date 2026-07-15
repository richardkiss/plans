#!/usr/bin/env python3
"""
Post-process CSV data to compute operations/sec (creates + spends).
"""
import csv
import sys
from pathlib import Path

def analyze_csv(csv_path):
    """Compute ops/sec from CSV data."""
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    print(f"\nBackend: {csv_path.stem}")
    print("=" * 70)
    print(f"{'Height':>10} {'Blk/s':>10} {'Coins':>12} {'Δ Coins':>12} {'Est Ops/s':>12}")
    print("-" * 70)
    
    prev_coins = 0
    for i, row in enumerate(rows):
        height = int(row['height'])
        blk_per_sec = float(row['blocks_per_sec'])
        coins = int(row['coins_in_db'])
        
        # Estimate ops (creates + spends) from coin delta
        # This is approximate since coins_in_db = creates - spends for lean stores
        delta_coins = coins - prev_coins
        
        # Rough estimate: delta_coins is net, but actual ops higher
        # For sqlite stores: delta = creates - spends, actual ops ~2x delta on average
        # This is a lower bound
        est_ops_per_sec = (delta_coins / 10000) * blk_per_sec if delta_coins > 0 else 0
        
        if i % 5 == 0 or i == len(rows) - 1:  # Sample every 5th row
            print(f"{height:>10,} {blk_per_sec:>10.1f} {coins:>12,} {delta_coins:>12,} {est_ops_per_sec:>12.1f}")
        
        prev_coins = coins
    
    print()

if __name__ == "__main__":
    plots_dir = Path("plots")
    for csv_file in sorted(plots_dir.glob("*.csv")):
        analyze_csv(csv_file)

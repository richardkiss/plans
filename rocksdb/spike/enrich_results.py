#!/usr/bin/env python3
"""
Post-process benchmark CSV results to add operations data and compute marginal costs.
"""
import csv
import struct
from pathlib import Path
import numpy as np
from scipy import stats
import zstandard as zstd


def load_ops_per_block(extract_path):
    """Load operations count for each block from extract."""
    print("Loading operations per block from extract...")
    block_ops = {}
    
    with open(extract_path, 'rb') as f:
        dctx = zstd.ZstdDecompressor()
        with dctx.stream_reader(f) as reader:
            while True:
                header = reader.read(16)
                if not header or len(header) < 16:
                    break
                
                height, timestamp, n_created = struct.unpack(">IQI", header)
                reader.read(105 * n_created)
                
                n_spent_data = reader.read(4)
                if len(n_spent_data) < 4:
                    break
                n_spent = struct.unpack(">I", n_spent_data)[0]
                reader.read(32 * n_spent)
                
                block_ops[height] = n_created + n_spent
    
    print(f"  Loaded {len(block_ops):,} blocks")
    return block_ops


def estimate_avg_ops(block_ops, start_height, end_height):
    """Estimate average ops/block in a height range."""
    ops_values = [block_ops.get(h, 0) for h in range(start_height, end_height + 1)]
    ops_values = [o for o in ops_values if o > 0]  # Exclude empty blocks
    if not ops_values:
        return 0
    return np.mean(ops_values)


def enrich_csv(csv_path, block_ops):
    """Add ops/block and ops/sec columns to CSV."""
    print(f"\nEnriching {csv_path.name}...")
    
    # Read existing CSV
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Enrich with ops data
    enriched = []
    for row in rows:
        height = int(row['height'])
        blk_per_sec = float(row['blocks_per_sec'])
        
        # Estimate avg ops/block for the 10k block window
        start_h = max(0, height - 10000)
        avg_ops = estimate_avg_ops(block_ops, start_h, height)
        
        ops_per_sec = blk_per_sec * avg_ops
        
        enriched.append({
            **row,
            'avg_ops_per_block': f'{avg_ops:.1f}',
            'ops_per_sec': f'{ops_per_sec:.1f}',
        })
    
    # Write enriched CSV
    enriched_path = csv_path.parent / f"{csv_path.stem}_enriched.csv"
    with open(enriched_path, 'w', newline='') as f:
        if enriched:
            writer = csv.DictWriter(f, fieldnames=enriched[0].keys())
            writer.writeheader()
            writer.writerows(enriched)
    
    print(f"  Wrote {enriched_path}")
    return enriched


def analyze_marginal_cost(backend_name, enriched_data, block_ops):
    """Fit linear model: time = fixed + marginal*ops at different height ranges."""
    print(f"\n{'='*70}")
    print(f"Marginal Cost Analysis: {backend_name}")
    print(f"{'='*70}")
    
    # Define height ranges for analysis (covers 1M-capped and full-chain runs)
    ranges = [
        (100000, 200000, "100-200k (Small DB)"),
        (300000, 400000, "300-400k"),
        (500000, 600000, "500-600k"),
        (700000, 800000, "700-800k"),
        (900000, 1000000, "900k-1M"),
        (1600000, 2100000, "1.6-2.1M (dust)"),
        (2500000, 3500000, "2.5-3.5M"),
        (4600000, 5100000, "4.6-5.1M (dust 2)"),
        (6000000, 7000000, "6-7M"),
        (7500000, 8500000, "7.5-8.5M (late chain)"),
    ]
    
    results = []
    
    for start, end, label in ranges:
        # Get data points in range
        range_data = [r for r in enriched_data 
                     if start <= int(r['height']) <= end]
        
        if not range_data:
            continue
        
        # For each measurement point, estimate time per block
        points = []
        for row in range_data:
            height = int(row['height'])
            blk_per_sec = float(row['blocks_per_sec'])
            avg_ops = float(row['avg_ops_per_block'])
            
            if blk_per_sec > 0 and avg_ops > 0:
                time_per_block_ms = 1000.0 / blk_per_sec
                points.append((avg_ops, time_per_block_ms))
        
        if len(points) < 2:
            continue
        
        # Linear regression: time = fixed + marginal*ops
        ops_vals = np.array([p[0] for p in points])
        time_vals = np.array([p[1] for p in points])
        
        slope, intercept, r_value, p_value, std_err = stats.linregress(ops_vals, time_vals)
        
        print(f"\n{label}")
        print(f"  Sample points: {len(points)}")
        print(f"  Ops/block range: {min(ops_vals):.0f} - {max(ops_vals):.0f}")
        print(f"  Fixed overhead: {intercept:.2f} ms/block")
        print(f"  Marginal cost: {slope:.2f} ms/op ({slope*1000:.0f} μs/op)")
        print(f"  R²: {r_value**2:.3f}")
        
        # Calculate ops/sec at median ops
        median_ops = np.median(ops_vals)
        time_at_median = intercept + slope * median_ops
        ops_per_sec = (1000.0 / time_at_median) * median_ops
        print(f"  At {median_ops:.0f} ops/block: {ops_per_sec:.0f} ops/sec")
        
        results.append({
            'range': label,
            'fixed_ms': intercept,
            'marginal_ms': slope,
            'r_squared': r_value**2,
            'median_ops_per_block': median_ops,
            'ops_per_sec_at_median': ops_per_sec,
        })
    
    return results


def main():
    extract_path = Path('extract.dat.zst')
    plots_dir = Path('plots')
    
    if not extract_path.exists():
        print(f"ERROR: {extract_path} not found")
        return
    
    # Load ops per block
    block_ops = load_ops_per_block(extract_path)
    
    # Process each backend's CSV
    all_results = {}
    
    for csv_path in sorted(plots_dir.glob('*.csv')):
        if '_enriched' in csv_path.stem:
            continue
        
        backend_name = csv_path.stem
        enriched = enrich_csv(csv_path, block_ops)
        
        if enriched:
            marginal_results = analyze_marginal_cost(backend_name, enriched, block_ops)
            all_results[backend_name] = marginal_results
    
    # Print summary comparison
    print(f"\n{'='*70}")
    print("Summary: Marginal Cost Degradation")
    print(f"{'='*70}")
    
    for backend_name, results in all_results.items():
        if len(results) >= 2:
            early = results[0]
            late = results[-1]
            
            degradation = late['marginal_ms'] / early['marginal_ms'] if early['marginal_ms'] > 0 else 0
            
            print(f"\n{backend_name}:")
            print(f"  Early marginal: {early['marginal_ms']*1000:.0f} μs/op")
            print(f"  Late marginal:  {late['marginal_ms']*1000:.0f} μs/op")
            print(f"  Degradation:    {degradation:.1f}x")
            
            ops_degradation = early['ops_per_sec_at_median'] / late['ops_per_sec_at_median']
            print(f"  Ops/sec degradation: {ops_degradation:.1f}x")


if __name__ == '__main__':
    main()

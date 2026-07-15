#!/usr/bin/env python3
"""
Analyze marginal cost per operation vs fixed transaction overhead.
Extract the relationship: time_per_block = fixed_overhead + (marginal_cost * ops)
"""
import struct
import zstandard as zstd
from collections import defaultdict
import numpy as np

# Read extract to get ops per block
print("Reading extract to count operations per block...")
block_ops = {}

with open('extract.dat.zst', 'rb') as f:
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

print(f"Loaded {len(block_ops):,} blocks")

# Analyze at different height ranges
height_ranges = [
    (100000, 200000, "100k-200k (Early transactions, small DB)"),
    (300000, 400000, "300k-400k (Active, ~1GB)"),
    (500000, 600000, "500k-600k (Active, ~3GB)"),
    (700000, 800000, "700k-800k (Active, ~5GB)"),
    (900000, 1000000, "900k-1M (Active, ~8GB)"),
]

print("\n" + "="*80)
print("Marginal Cost Analysis: time = fixed + marginal*ops")
print("="*80)

for start, end, label in height_ranges:
    # Collect samples in this range
    samples = []
    for h in range(start, end):
        if h in block_ops and block_ops[h] > 0:  # Skip empty blocks
            ops = block_ops[h]
            samples.append((h, ops))
    
    if not samples:
        continue
    
    # Group by ops to get average time per op-count
    # (This smooths out variance)
    ops_to_times = defaultdict(list)
    
    # We need actual timing data - for now use the 10k block windows
    # Calculate expected blocks/sec at midpoint
    mid_height = (start + end) // 2
    
    print(f"\n{label}")
    print(f"  Sample size: {len(samples):,} blocks")
    print(f"  Ops range: {min(s[1] for s in samples)} - {max(s[1] for s in samples)}")
    
    # Show distribution
    ops_values = [s[1] for s in samples]
    print(f"  Median ops/block: {np.median(ops_values):.1f}")
    print(f"  Mean ops/block: {np.mean(ops_values):.1f}")
    
    # For actual regression, we'd need timing per block
    # But we can estimate from the CSV data at nearest measurement point
    print(f"  (Need per-block timing for full regression - CSV has 10k-block windows)")

print("\n" + "="*80)
print("\nTo get true marginal cost, we need to instrument replay.py to record")
print("time-per-block at the block level, not just 10k-block aggregates.")
print("\nAlternatively, we can sample blocks and time them individually in a")
print("separate micro-benchmark.")

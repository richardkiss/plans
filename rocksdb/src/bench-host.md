# Benchmark hosts

Every result on the [Benchmarks](benchmarks.md) page names the host it ran
on, so numbers can be compared across machines. New hosts get a new section
here (I plan to try a slower box).

## host-1 (2026-07-15 runs)

The host for all published results so far: a virtual machine backed by
rotational storage — deliberately representative of the weak-hardware
target, not a fast dev box.

| Component | Spec |
|---|---|
| CPU | AMD Ryzen AI Max+ 395 (VM guest, 32 vCPUs, 1 thread/core) |
| RAM | 15 GB |
| Disk | QEMU virtual disk, 600 GB, rotational (HDD-backed) |
| Filesystem | ext4 |
| OS | Debian 12 (bookworm), kernel 6.1 |
| Python | 3.13 (via uv) |

Notes for cross-machine comparison:

- The CPU is fast; the disk is the deliberate bottleneck. The engine gap is
  mostly an I/O-pattern story, so disk type matters far more than CPU here.
- 15 GB RAM means the replayed databases (3–8 GB) partially fit in page
  cache — see the caveats on the [Benchmarks](benchmarks.md) page. A
  smaller-RAM host would likely *widen* the SQLite/RocksDB gap.
- Virtualization adds I/O overhead, but it applies equally to all four
  backends.

## Capturing specs for a new host

```bash
lscpu | grep 'Model name'; free -g | head -2; lsblk -d -o NAME,MODEL,SIZE,ROTA
```

Add a section above with the output, and tag result tables/CSVs with the
host name.

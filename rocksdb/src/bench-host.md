# Benchmark hosts

Every result on the [Benchmarks](benchmarks.md) page names the host it ran
on, so numbers can be compared across machines. New hosts get a new section
here (I plan to try a slower box).

## host-1 (2026-07-15 runs)

The host for all published results so far: a virtual machine whose disk is
NVMe-backed. (The guest reports the disk as rotational — `lsblk` says
`ROTA=1` — but that's the virtualization layer talking; the backing store is
NVMe.) So host-1 is *not* the spinning-disk target machine, and the
published numbers should be read as NVMe numbers.

| Component | Spec |
|---|---|
| CPU | AMD Ryzen AI Max+ 395 (VM guest, 32 vCPUs, 1 thread/core) |
| RAM | 15 GB |
| Disk | QEMU virtual disk, 600 GB, NVMe-backed (guest reports rotational) |
| Filesystem | ext4 |
| OS | Debian 12 (bookworm), kernel 6.1 |
| Python | 3.13 (via uv) |

Notes for cross-machine comparison:

- On NVMe, random reads are cheap, which *flatters SQLite*. The B-tree vs
  LSM divergence should be larger on a real spinning disk, where scattered
  point reads pay full seek cost. Until a real-HDD run exists, the
  spinning-disk story is extrapolation.
- 15 GB RAM means the replayed databases (3–8 GB) partially fit in page
  cache — see the caveats on the [Benchmarks](benchmarks.md) page. A
  smaller-RAM host would likely *widen* the SQLite/RocksDB gap.
- Virtualization adds I/O overhead, but it applies equally to all four
  backends.

## Capturing specs for a new host

```bash
lscpu | grep 'Model name'; free -g | head -2; lsblk -d -o NAME,MODEL,SIZE,ROTA
```

Don't trust `ROTA` inside a VM (see above) — record what the backing store
actually is. Add a section here with the output, and tag result tables/CSVs
with the host name.

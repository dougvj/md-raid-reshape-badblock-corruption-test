# MD RAID reshape bad-block corruption test

Tests data integrity when RAID5/6 reshape encounters bad-block metadata.
Disposable QEMU guests verify a deterministic pattern before reshape,
after failure, and after reboot with read-only assembly. Successful reads
with wrong contents are counted separately from failed or blocked reads.

This extends the [original MD bad-block reshape stall test](https://github.com/dougvj/md_badblock_reshape_stall_test).

## Results

Doug ran these comparisons on October 15, 2026, using QEMU 11.0.1 (TCG)
and mdadm 4.6. RAID5 growth from 3 to 4 members and RAID6 growth from 4 to
5 members **each produced the following results after read-only reassembly**.
Each array originally contained 401,408 sectors of 512 bytes.

| Kernel | Correct | Read errors | Wrong data | Previously correct, now wrong | Unchecked |
| --- | ---: | ---: | ---: | ---: | ---: |
| Parent | 397,296 | 0 | 16 | **14** | 4,096 |
| Upstream deadlock fix | 401,358 | 2 | 48 | **46** | 0 |
| Original v3 freeze handler | 397,296 | 0 | 16 | **14** | 4,096 |
| Cleanup plus interruption | 401,392 | 16 | **0** | **0** | **0** |

Before reshape, two sectors returned errors; all others matched.
The parent/v3 returned **7,168 bytes** of previously correct data incorrectly;
the upstream fix returned **23,552 bytes** incorrectly. Their reshape states
were stalled/frozen at position 46080 and completed, respectively.

Interruption froze reshape at position 24576. After reboot, every sector
was attempted: 16 returned errors and every successful read matched.
It did not restore full readability. Before reboot, some reads still blocked.
Every clean RAID5 control verified all 401,408 sectors correctly.

The parent's unchecked **2 MiB** prevents claiming exactly 32 additional
corrupted sectors from the upstream fix. Corruption already exists in the
parent; these tests do not identify its original introduction or prove the
interruption safe for every failure scenario.

## Evidence and kernels

- [Original v3 comparison](results/2026-10-15-original-v3/results.csv).
- [Interruption comparison](results/2026-10-15-interrupted-cleanup/results.csv).
- [Interruption patch tested](results/2026-10-15-interrupted-cleanup/abort.patch).

Both result directories include JSON, manifests and all serial logs.
Parent: `6cb6ab75bdf2`; upstream fix: `788e4139463f`; original v3 handler:
`efcb3cc42930`. V3 uses its original 6.14-rc4 base; the newer pair uses a
7.2-rc5-era tree. Neither candidate includes the preflight check.

## Run

```bash
./run.sh
```

Defaults to parent, upstream fix, and your current failure handler.
It reuses builds in `baseline-path.txt`. Set `HANDLER_SOURCE` and
`BASELINE_KERNEL_DIR` to override local paths. `./run.sh freeze` builds
and tests the original v3 handler instead. Historical v3 references must
exist in the Linux checkout; set `LINUX_REPO` when running elsewhere.

Cases: `raid5bad`, `raid6bad`, `raid5clean`. Components are 100 MiB,
chunks 512 KiB, and injection is `20000 1` on every original member.
All MD operations run inside guests; no sudo is needed. Builds require
GCC; execution requires Python 3.11+, QEMU, mdadm, cpio, e2fsprogs and
standard Linux utilities. See `run.py --help` for supplied-image options.

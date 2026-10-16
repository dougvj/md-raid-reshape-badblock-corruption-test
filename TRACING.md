# Trace reshape and locate misplaced data

Run from this directory:

```bash
./trace.sh
```

Uses the cached baseline configuration (`BASELINE_KERNEL_DIR`, or
`baseline-path.txt`) to build a persistent instrumented Chen checkout. Subsequent runs reuse its
worktree and build directory, rebuilding incrementally. An existing trace build
is adopted automatically on first use. `TRACE_CACHE_DIR` selects a different
cache; its path is remembered locally in ignored `trace-cache-path.txt`. Each
run still saves separate kernel images, configuration, diffs, and results. Leaves
production patches and cached baseline sources unchanged. Builds Chen plus
probes, then the same probes plus interruption, and compares both with the
uninstrumented Chen image. Default case is RAID5; use
`TRACE_CASE=raid6bad ./trace.sh` for RAID6. You run the guests as before.

Serial logs contain `MDTRACE` records for failed stripes, dependent destination
lookups/cancellations (`active=1` means still expanding), source-to-destination
copy submissions, destination write submissions, and checkpoint attempts.
Sector fields are member-relative stripe addresses; `logical` is the array
sector mapped from that source block. Copy/write records indicate submission,
not successful completion. Checkpoint records precede persistence and are not
proof of a durable checkpoint. `TRACE_FIRST` and `TRACE_LAST` select inclusive
stripe addresses (default 0–40000); failure/copy records filter on source and
write records on destination. A filtered log is not a complete I/O history.

The existing deterministic pattern is retained. Every wrong sector now emits
its complete returned bytes as `SECTOR_BYTES`, including beyond the original
30-sector reporting limit. To identify the returned data and find original
sector patterns in saved members:

```bash
python3 analyze-trace.py /tmp/md-reshape-trace-run.XXXXXXXX/results chen-trace raid5bad > fingerprints.json
```

Requires `debugfs` from e2fsprogs. This extracts members into temporary files
without mounting or assembling anything on the host. Scans all physical
512-byte sectors, including old and new data areas; reports physical offsets
including metadata. Each candidate match is checked against all 512 bytes.
`matches_original_sectors` identifies another original logical sector, an
empty list means no complete pattern matched, and `all_zero` identifies zeros.
The scanner locates patterns for wrong logical sectors and identified origins,
not every pattern in the array. An absent pattern does not prove that parity,
reshape backups, or other recovery methods cannot recover it.

Compare `failed` → `cancel_destination active=1` → later checkpoints and
completion with the interrupted build. Use the source/destination mappings
and member offsets to explain the observed misplaced data. Instrumentation
changes scheduling; first check whether traced and untraced Chen reproduce
the same integrity failure. These probes establish scheduling and cleanup;
they do not alone prove the complete order or success of physical writes.

The [recorded trace analysis](results/2026-10-15-traced-cleanup/analysis.md)
includes serial logs, fingerprints, build configurations, and instrumentation
diffs from the RAID5 run.

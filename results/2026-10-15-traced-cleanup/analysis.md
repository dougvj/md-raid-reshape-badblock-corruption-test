# RAID5 trace result, 2026-10-15

Run: /tmp/md-reshape-trace-run.BhXmV1MZ. Traced and untraced Chen
both returned 48 wrong sectors, 46 previously readable, plus 2 read errors.
Interrupted trace returned zero wrong sectors and 16 errors after read-only
reassembly; its live check still had 13056 unchecked sectors.

## Confirmed event sequence

1. Checkpoint attempt progress=24576 safe=18432 intr=0.
2. Source stripe 15904 fails with three unavailable blocks. Destination 10784,
   logical 31264 on member 2, is still expanding and gets canceled. The same
   destination for logical 32288 on member 3 is already inactive at the second
   lookup. Canceling this whole destination also loses the migration of its
   other data block, logical 33312.
3. Chen continues checkpoint attempts at 33792 and 46080.
4. Later source copies are submitted toward destination 15904 for logical
   46624 (member 1), 47648 (member 2), and 48672 (member 3).
5. Destination 15904 fails with expanding=1 ready=1 and three unavailable
   blocks. No destination_write_submit record exists for either 10784 or 15904.
6. Chen continues checkpoint attempts to 439296 and finishes with no reshape
   position. The interrupted build stops after step 2 with position 24576.

The final new member data offset is 1024 sectors. Destination addresses
10784 and 15904 therefore correspond to raw member offsets 11808 and 16928.

## Full-sector fingerprints of returned data

| Wrong logical sectors | Returned contents |
| --- | --- |
| 31264-31271 | Original logical 14880-14887 |
| 32288-32295 | All zero |
| 33312-33319 | Original logical 15904-15911 |
| 46624-46631 | Original logical 26144-26151 |
| 47648-47655 | Original parity: pattern(25120+i) XOR pattern(26144+i), i=0..7 |
| 48672-48679 | All zero |

Every fingerprint and parity comparison used all 512 bytes of each sector.
The raw member scan finds the stale patterns at the new destination offsets.
With the old offset 4096, those same physical positions were old-layout
member sectors 7712 and 12832, explaining the old data/parity returned.
The added member's corresponding destinations remain zero-filled.

This directly supports skipped destination writes followed by reads under
the completed new mapping. Copy/write probes record submission, not physical
I/O completion; checkpoint probes precede persistence. This is not a complete
block-I/O timeline, proof of general safety, or proof that missing data cannot
be recovered through parity/backups. Corruption already existed in the parent.

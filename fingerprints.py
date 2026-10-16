#!/usr/bin/env python3
"""Identify misplaced pattern sectors; scan extracted member files read-only."""
import argparse
import json
from pathlib import Path
import re

MASK = (1 << 64) - 1


def pattern(sector, length=512):
    x = (sector + 0x9e3779b97f4a7c15) & MASK
    result = bytearray()
    for _ in range(length):
        x ^= x >> 12
        x ^= (x << 25) & MASK
        x ^= x >> 27
        result.append(((x * 2685821657736338717) & MASK) >> 56)
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--sectors', type=int, default=401408)
    parser.add_argument('--member', type=Path, action='append', default=[])
    args = parser.parse_args()
    # Index every possible origin, then verify the complete sector before matching.
    index = {}
    for sector in range(args.sectors):
        index.setdefault(pattern(sector, 8), []).append(sector)

    def identify(data):
        return [s for s in index.get(data[:8], []) if pattern(s) == data]

    observed = []
    wanted = set()
    for logical, value in re.findall(r'SECTOR_BYTES logical=(\d+) hex=([0-9a-f]{1024})',
                                     args.log.read_text(errors='replace')):
        logical = int(logical)
        data = bytes.fromhex(value)
        origins = identify(data)
        wanted.add(logical)
        wanted.update(origins)
        observed.append({'logical': logical, 'matches_original_sectors': origins,
                         'all_zero': not any(data)})
    if not observed:
        parser.error('No SECTOR_BYTES records; rerun with the updated read-probe.')
    locations = []
    for member in args.member:
        with member.open('rb') as f:
            offset = 0
            while chunk := f.read(1024 * 1024):
                for pos in range(0, len(chunk) - 511, 512):
                    data = chunk[pos:pos + 512]
                    if data[:8] not in index:
                        continue
                    matches = [s for s in index[data[:8]]
                               if s in wanted and pattern(s) == data]
                    if matches:
                        locations.append({'member': str(member),
                                          'physical_sector': (offset + pos) // 512,
                                          'original_sectors': matches})
                offset += len(chunk)
    print(json.dumps({'observations': observed, 'member_locations': locations,
                      'note': 'Physical sectors include member metadata/data offsets. '
                              'No match does not establish irrecoverability.'}, indent=2))


if __name__ == '__main__':
    main()

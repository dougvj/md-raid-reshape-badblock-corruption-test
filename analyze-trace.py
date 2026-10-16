#!/usr/bin/env python3
"""Extract saved member files without mounting; correlate observed fingerprints."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('results', type=Path)
p.add_argument('label')
p.add_argument('case', choices=['raid5bad', 'raid6bad', 'raid5clean'])
p.add_argument('--phase', choices=['prepare', 'readonly'], default='readonly')
a = p.parse_args()
if not all(c.isalnum() or c in '_-' for c in a.label):
    p.error('Invalid kernel label')
stem = f'{a.label}-{a.case}'
log = a.results / f'{stem}-{a.phase}.log'
disk = (a.results / f'{stem}.img').resolve()
# Explicit /tmp keeps debugfs command paths free of whitespace/quoting surprises.
with tempfile.TemporaryDirectory(prefix='md-fingerprints-', dir='/tmp') as tmp:
    command = [sys.executable, '-I', str(Path(__file__).with_name('fingerprints.py')), str(log)]
    for i in range(5 if a.case == 'raid6bad' else 4):
        member = Path(tmp) / f'rd{i}.img'
        subprocess.run(['debugfs', '-R', f'dump /rd{i}.img {member}', str(disk)], check=True)
        if not member.is_file() or not member.stat().st_size:
            raise SystemExit(f'Member extraction failed: {member.name}')
        command += ['--member', str(member)]
    subprocess.run(command, check=True)

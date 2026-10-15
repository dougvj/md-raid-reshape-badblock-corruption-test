#!/usr/bin/env python3
"""Run MD integrity comparisons exclusively inside disposable QEMU guests."""
import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
TOOLS = ['bash', 'mount', 'losetup', 'mdadm', 'dd', 'cat', 'grep', 'sleep',
         'sync', 'mkdir', 'timeout', 'uname']


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def install_binary(source, destination, root):
    target = root / destination.lstrip('/')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o755)
    result = subprocess.run(['ldd', str(source)], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if 'not found' in result.stdout:
        raise RuntimeError(f'Missing library for {source}: {result.stdout}')
    if result.returncode and not any(s in result.stdout for s in
                                    ['not a dynamic executable', 'statically linked']):
        raise RuntimeError(f'ldd failed for {source}: {result.stdout}')
    for library in re.findall(r'(/[^\s()]+)', result.stdout):
        source_lib = Path(library)
        if not source_lib.is_file():
            continue
        target_lib = root / library.lstrip('/')
        target_lib.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_lib, target_lib)
        target_lib.chmod(0o755)


def build_initramfs(output):
    root = output / 'initramfs-root'
    for directory in ['bin', 'sbin', 'dev', 'proc', 'sys', 'tmp', 'work', 'etc']:
        (root / directory).mkdir(parents=True, exist_ok=True)
    for name in TOOLS:
        install_binary(shutil.which(name), '/bin/' + name, root)
    (root / 'bin/sh').symlink_to('bash')
    (root / 'etc/passwd').write_text('root:x:0:0:root:/root:/bin/bash\n')
    (root / 'etc/group').write_text('root:x:0:\n')
    for name, source in [('pattern-check', 'pattern-check.c'),
                         ('read-probe', 'read-probe.c'), ('poweroff', 'poweroff.c')]:
        subprocess.run(['gcc', '-O2', '-static', '-Wall', '-Wextra',
                        str(HERE / source), '-o', str(root / 'bin' / name)], check=True)
    for name in ['init', 'guest.sh']:
        shutil.copyfile(HERE / name, root / name)
        (root / name).chmod(0o755)
    names = ['.'] + sorted(str(p.relative_to(root)) for p in root.rglob('*'))
    archive = subprocess.run(['cpio', '--null', '-o', '--format=newc', '--owner=0:0'],
                             cwd=root, input=('\0'.join(names) + '\0').encode(),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             check=True).stdout
    path = output / 'initramfs.cpio.gz'
    with gzip.GzipFile(filename=str(path), mode='wb', mtime=0) as f:
        f.write(archive)
    return path


def run_guest(kernel, disk, initramfs, phase, case, log, deadline_seconds):
    command = ['qemu-system-x86_64', '-accel', 'tcg', '-m', '1536', '-smp', '2',
               '-kernel', str(kernel), '-initrd', str(initramfs),
               '-append', 'console=ttyS0 rdinit=/init panic=-1 '
               f'disposable_md_repro=1 phase={phase} case={case}',
               '-drive', f'file={disk},format=raw,if=virtio,cache=none',
               '-nographic', '-no-reboot', '-monitor', 'none', '-nic', 'none']
    # No host mounts, loop devices, MD devices, or privileged commands.
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, bufsize=0)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + deadline_seconds
    heartbeat = time.monotonic() + 15
    complete = False
    recent = b''
    try:
        with open(log, 'wb') as f:
            while time.monotonic() < deadline:
                if time.monotonic() >= heartbeat:
                    print(f'  {log.stem}: still running', flush=True)
                    heartbeat = time.monotonic() + 15
                if not selector.select(1):
                    if process.poll() is not None:
                        break
                    continue
                data = os.read(process.stdout.fileno(), 65536)
                if not data:
                    break
                f.write(data)
                f.flush()
                recent = (recent + data)[-65536:]
                if b'VALIDATION_END' in recent:
                    complete = True
                    break
    finally:
        selector.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    return complete


def parse_result(log, label, case, phase, complete):
    text = log.read_text(errors='replace').replace('\r', '')
    row = {'kernel': label, 'case': case, 'phase': phase, 'status': 'fixture-error',
           'complete': complete, 'log': str(log)}
    for name in ['sync_action', 'reshape_position', 'raid_disks', 'degraded']:
        matches = re.findall(r'^STATE_' + name + r'=(.*)$', text, re.M)
        row[name] = matches[-1] if matches else ''
    for name in ['GROW_EXIT', 'PHASE_EXIT', 'ORIGINAL_SECTORS']:
        matches = re.findall(r'^' + name + r'=(\d+)$', text, re.M)
        row[name.lower()] = int(matches[-1]) if matches else None
    before = re.search(r'^VERIFY phase=pre (.*)$', text, re.M)
    if before:
        row.update({'before_' + k: int(v) for k, v in
                    re.findall(r'(\w+)=(\d+)', before.group(1))})
    summaries = re.findall(r'^READ_SUMMARY (.*)$', text, re.M)
    if summaries:
        row.update({k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', summaries[-1])})
        row['wrong_bytes'] = row['wrong'] * 512
        row['previously_correct_now_wrong_bytes'] = row['previously_correct_now_wrong'] * 512
        row['unchecked_bytes'] = (row['in_flight'] + row['untested']) * 512
    row['backing_filesystem_flushed'] = 'PREPARE_FLUSHED' in text
    valid = (complete and row['phase_exit'] == 0 and summaries
             and 'FIXTURE_ERROR=' not in text and 'WORKER_ERROR=' not in text
             and all(row[k] for k in ['sync_action', 'reshape_position', 'raid_disks', 'degraded'])
             and (phase != 'prepare' or row['backing_filesystem_flushed']))
    if phase == 'prepare':
        valid = (valid and row.get('before_readable_mismatch') == 0
                 and row['grow_exit'] is not None
                 and row.get('before_checked', 0) + row.get('before_eio', 0)
                 == row['original_sectors'])
    if valid:
        accounted = sum(row[k] for k in ['correct', 'read_error', 'wrong', 'in_flight', 'untested'])
        if accounted != row['original_sectors']:
            return row
        if row['wrong']:
            row['status'] = 'wrong-data'
        elif row['in_flight'] or row['untested']:
            row['status'] = 'incomplete-read-check'
        elif phase == 'prepare' and row['grow_exit'] in [124, 137]:
            row['status'] = 'grow-command-timeout'
        elif phase == 'prepare' and row['grow_exit'] != 0:
            row['status'] = 'reshape-rejected'
        elif row['reshape_position'] != 'none':
            row['status'] = 'reshape-incomplete'
        elif row['read_error']:
            row['status'] = 'read-errors'
        else:
            row['status'] = 'data-matches'
    return row


def write_results(output, rows):
    (output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
    if rows:
        fields = list(dict.fromkeys(k for row in rows for k in row))
        with open(output / 'results.csv', 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', action='append', required=True, metavar='LABEL=IMAGE',
                        help='Supply exactly three kernel images, with distinct labels.')
    parser.add_argument('--output', required=True, type=Path,
                        help='New directory; existing paths are refused.')
    parser.add_argument('--case', action='append', choices=['raid5bad', 'raid6bad', 'raid5clean'])
    parser.add_argument('--timeout', type=int, default=240, help='Seconds per guest boot.')
    parser.add_argument('--prepare-only', action='store_true',
                        help='Build initramfs and manifest without booting any VM.')
    args = parser.parse_args()
    kernels = {}
    for argument in args.kernel:
        label, separator, value = argument.partition('=')
        if not separator or not re.fullmatch(r'[a-zA-Z0-9_-]+', label) or label in kernels:
            parser.error(f'Invalid or duplicate kernel argument: {argument}')
        image = Path(value).resolve()
        if not image.is_file():
            parser.error(f'Kernel image missing: {image}')
        kernels[label] = image
    if len(kernels) != 3:
        parser.error('Supply exactly three --kernel arguments.')
    if args.timeout < 60:
        parser.error('--timeout must be at least 60 seconds.')
    missing = [name for name in TOOLS + ['gcc', 'ldd', 'cpio', 'mkfs.ext4',
                                        'qemu-system-x86_64'] if not shutil.which(name)]
    if missing:
        parser.error('Missing commands: ' + ', '.join(missing))
    output = args.output.resolve()
    if ',' in str(output):
        parser.error('Output path must not contain commas (QEMU drive syntax).')
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'kernels': {label: {'image': str(path), 'sha256': sha256(path)}
                            for label, path in kernels.items()},
                'fixture': {p.name: sha256(p) for p in HERE.iterdir() if p.is_file()},
                'cases': args.case or ['raid5bad', 'raid6bad', 'raid5clean'],
                'sector_bytes': 512, 'acceleration': 'tcg',
                'uname': list(os.uname()),
                'qemu': subprocess.check_output(['qemu-system-x86_64', '--version'], text=True),
                'mdadm': subprocess.check_output(['mdadm', '--version'], text=True,
                                                 stderr=subprocess.STDOUT)}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Building initramfs...', flush=True)
    initramfs = build_initramfs(output)
    manifest['initramfs_sha256'] = sha256(initramfs)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if args.prepare_only:
        print(f'Prepared {output}; no VMs started.')
        return
    rows = []
    try:
        for label, image in kernels.items():
            for case in manifest['cases']:
                disk = output / f'{label}-{case}.img'
                with open(disk, 'xb') as f:
                    f.truncate(1536 * 1024 * 1024)
                subprocess.run(['mkfs.ext4', '-q', '-F', str(disk)], check=True)
                for phase in ['prepare', 'readonly']:
                    log = output / f'{label}-{case}-{phase}.log'
                    print(f'{label} / {case} / {phase}: starting', flush=True)
                    complete = run_guest(image, disk, initramfs, phase, case, log, args.timeout)
                    row = parse_result(log, label, case, phase, complete)
                    rows.append(row)
                    write_results(output, rows)
                    print(f"  {row['status']}: wrong={row.get('wrong', '?')}, "
                          f"previously-correct-now-wrong={row.get('previously_correct_now_wrong', '?')}, "
                          f"errors={row.get('read_error', '?')}, "
                          f"unchecked={row.get('in_flight', 0) + row.get('untested', 0)}", flush=True)
                    if row['status'] == 'fixture-error':
                        print(f'  Check {log}; skipping further phases for this case.', flush=True)
                        break
    finally:
        write_results(output, rows)
    print(f'Results: {output / "results.csv"}')
    if any(row['status'] == 'fixture-error' for row in rows):
        sys.exit(2)


if __name__ == '__main__':
    main()

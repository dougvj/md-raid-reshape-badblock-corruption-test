#!/bin/bash
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
source "$here/linux-path.sh"
repo=$(linux_repo "$here")
baseline=${BASELINE_KERNEL_DIR:-}
if [[ -z $baseline && -f "$here/baseline-path.txt" ]]; then
 IFS= read -r baseline < "$here/baseline-path.txt"
fi
[[ -f "$baseline/build-chen/.config" && -f "$baseline/chen.bzImage" ]] || { echo 'Set BASELINE_KERNEL_DIR to cached kernels directory.' >&2; exit 2; }
cache=${TRACE_CACHE_DIR:-}
if [[ -z $cache && -f "$here/trace-cache-path.txt" ]]; then
 IFS= read -r cache < "$here/trace-cache-path.txt"
fi
if [[ -z $cache ]]; then
 # Adopt an earlier trace build instead of discarding that compilation work.
 cache=$(python3 - <<'PY'
from pathlib import Path
import os
root=Path(os.environ.get('TMPDIR', '/tmp'))
candidates=[p for p in root.glob('md-reshape-trace.*')
            if (p/'source/.git').is_file() and (p/'build/.config').is_file()]
if candidates:
 print(max(candidates, key=lambda p: (p/'build/.config').stat().st_mtime))
PY
 )
 cache=${cache:-$baseline/trace-cache}
fi
mkdir -p "$cache"
cache=$(cd -- "$cache" && pwd)
exec 9>"$cache/.trace.lock"
flock -n 9 || { echo "Another trace run is using $cache" >&2; exit 2; }
revision=788e4139463f74b945600237f7186411015d996e
if [[ ! -e "$cache/source" ]]; then
 git -C "$repo" worktree add --detach "$cache/source" "$revision"
fi
[[ $(git -C "$cache/source" rev-parse HEAD) == "$revision" ]] || { echo 'Trace checkout has an unexpected revision.' >&2; exit 2; }
mkdir -p "$cache/build"
if [[ ! -f "$cache/build/.config" ]]; then
 cp "$baseline/build-chen/.config" "$cache/build/.config"
fi
printf '%s\n' "$cache" > "$here/trace-cache-path.txt"
workspace=$(mktemp -d "${TMPDIR:-/tmp}/md-reshape-trace-run.XXXXXXXX")
echo "Reusing trace cache: $cache"
echo "Run workspace: $workspace"
git -C "$cache/source" show "$revision:drivers/md/raid5.c" > "$workspace/raid5-base.c"
cp "$workspace/raid5-base.c" "$workspace/raid5-chen.c"
python3 -I "$here/instrument-reshape.py" "$workspace/raid5-chen.c" \
 --first "${TRACE_FIRST:-0}" --last "${TRACE_LAST:-40000}"
python3 - "$workspace" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=(p/'raid5-chen.c').read_text()
anchor='\tif (was_expanding || was_ready) {'
assert s.count(anchor)==1
s=s.replace(anchor, '\tset_bit(MD_RECOVERY_FROZEN, &conf->mddev->recovery);\n\tmd_sync_error(conf->mddev);\n\n'+anchor)
(p/'raid5-interrupted.c').write_text(s)
PY
# Refuse unrelated tracked edits, including hand edits to the cached source.
python3 - "$cache" "$workspace" <<'PY'
from pathlib import Path
import hashlib, subprocess, sys
cache,run=map(Path,sys.argv[1:])
changed=subprocess.check_output(['git','-C',str(cache/'source'),'diff','HEAD','--name-only'],text=True).splitlines()
if any(p != 'drivers/md/raid5.c' for p in changed):
 raise SystemExit('Trace checkout has unrelated tracked edits; leaving it untouched.')
current=(cache/'source/drivers/md/raid5.c').read_bytes()
known=[(run/f'raid5-{v}.c').read_bytes() for v in ['base','chen','interrupted']]
state=cache/'source.sha256'
if current not in known and (not state.exists() or hashlib.sha256(current).hexdigest()!=state.read_text().strip()):
 raise SystemExit('Trace source has unrecognized edits; leaving it untouched. Choose a different TRACE_CACHE_DIR.')
PY
for variant in chen interrupted; do
 # Avoid touching identical source; make retains all other compiled objects.
 if ! cmp -s "$workspace/raid5-$variant.c" "$cache/source/drivers/md/raid5.c"; then
  cp "$workspace/raid5-$variant.c" "$cache/source/drivers/md/raid5.c"
 fi
 sha256sum "$cache/source/drivers/md/raid5.c" | cut -d ' ' -f 1 > "$cache/source.sha256"
 git -C "$cache/source" diff HEAD > "$workspace/$variant-instrumentation.patch"
 echo "Incremental build: $variant; log: $workspace/$variant-build.log"
 make -C "$cache/source" O="$cache/build" olddefconfig > "$workspace/$variant-build.log" 2>&1
 make -C "$cache/source" O="$cache/build" -j"${JOBS:-16}" bzImage >> "$workspace/$variant-build.log" 2>&1
 cp "$cache/build/arch/x86/boot/bzImage" "$workspace/$variant-trace.bzImage"
 cp "$cache/build/.config" "$workspace/$variant.config"
done
printf '%s\n' "$revision" > "$workspace/source-revision.txt"
python3 -I "$here/run.py" --kernel "chen=$baseline/chen.bzImage" \
 --kernel "chen-trace=$workspace/chen-trace.bzImage" \
 --kernel "interrupted-trace=$workspace/interrupted-trace.bzImage" \
 --case "${TRACE_CASE:-raid5bad}" --output "$workspace/results"
echo "Trace results: $workspace/results"

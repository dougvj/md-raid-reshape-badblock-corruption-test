#!/bin/bash
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
variant=${1:-abort}
case "$variant" in
 abort|freeze|full) ;;
 *) echo "Usage: $0 [abort|freeze|full]" >&2; exit 2;;
esac
# Each invocation keeps its own builds, logs, and guest disk images.
workspace=$(mktemp -d "${TMPDIR:-/tmp}/md-three-kernels.XXXXXXXX")
echo "Workspace: $workspace"
if [[ $variant == abort ]]; then
 baseline=${BASELINE_KERNEL_DIR:-}
 if [[ -z $baseline && -f "$here/baseline-path.txt" ]]; then
  IFS= read -r baseline < "$here/baseline-path.txt"
 fi
 if [[ -z $baseline || ! -f "$baseline/parent.bzImage" || ! -f "$baseline/chen.bzImage" || ! -d "$baseline/source-chen" || ! -d "$baseline/build-chen" ]]; then
  echo 'Baseline builds missing. Set BASELINE_KERNEL_DIR to the previous kernels directory,' >&2
  echo 'or first run ./run.sh freeze to build the historical baseline kernels.' >&2
  exit 2
 fi
 source "$here/linux-path.sh"
 repo=$(linux_repo "$here")
 handler_source=${HANDLER_SOURCE:-$repo/.validation/md-fixes/drivers/md/raid5.c}
 echo "Comparing: parent, chen, abort"
 echo "Baseline builds: $baseline"
 python3 -I "$here/copy-handler.py" "$handler_source" "$baseline/source-chen" \
  "$workspace/handler.c"
 git -C "$baseline/source-chen" diff -- drivers/md/raid5.c > "$workspace/abort.patch"
 echo "Building your handler edit; log: $workspace/abort-build.log"
 make -C "$baseline/source-chen" O="$baseline/build-chen" -j"${JOBS:-16}" bzImage \
  > "$workspace/abort-build.log" 2>&1
 cp "$baseline/build-chen/arch/x86/boot/bzImage" "$workspace/abort.bzImage"
 python3 -I "$here/run.py" \
  --kernel "parent=$baseline/parent.bzImage" \
  --kernel "chen=$baseline/chen.bzImage" \
  --kernel "abort=$workspace/abort.bzImage" \
  --output "$workspace/results"
 exit
fi
echo "Original v3 variant: $variant"
bash "$here/build-kernels.sh" "$workspace/kernels" "$variant"
printf '%s\n' "$workspace/kernels" > "$here/baseline-path.txt"
python3 -I "$here/run.py" \
 --kernel "parent=$workspace/kernels/parent.bzImage" \
 --kernel "chen=$workspace/kernels/chen.bzImage" \
 --kernel "v3=$workspace/kernels/v3.bzImage" \
 --output "$workspace/results"

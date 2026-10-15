#!/bin/bash
# Optional: build the three historical kernels; never starts a test VM.
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
source "$here/linux-path.sh"
repo=$(linux_repo "$here")
out=${1:?Usage: bash build-kernels.sh NEW_OUTPUT_DIRECTORY [freeze|full]}
variant=${2:-freeze}
case "$variant" in
 freeze) v3=efcb3cc429308e796efe308d9f9c1f67124ffc61;;
 full) v3=c098245c8ebd095eadb3cf228118c65250740137;;
 *) echo 'Variant must be freeze or full' >&2;exit 2;;
esac
mkdir -- "$out"
out=$(cd -- "$out" && pwd)
printf 'label\trevision\timage\n' > "$out/revisions.tsv"
for label in parent chen v3; do
 case "$label" in
  parent) revision=6cb6ab75bdf2f49c0adb0fd6971886b082932eaa;;
  chen) revision=788e4139463f74b945600237f7186411015d996e;;
  v3) revision=$v3;;
 esac
 git -C "$repo" worktree add --detach "$out/source-$label" "$revision"
 mkdir "$out/build-$label"
 cp "$here/kernel.config" "$out/build-$label/.config"
 echo "Building $label ($revision); log: $out/$label-build.log"
 make -C "$out/source-$label" O="$out/build-$label" olddefconfig \
  > "$out/$label-config.log" 2>&1
 make -C "$out/source-$label" O="$out/build-$label" -j"${JOBS:-16}" bzImage \
  > "$out/$label-build.log" 2>&1
 cp "$out/build-$label/arch/x86/boot/bzImage" "$out/$label.bzImage"
 printf '%s\t%s\t%s\n' "$label" "$revision" "$out/$label.bzImage" >> "$out/revisions.tsv"
done
echo "Kernel images: $out/{parent,chen,v3}.bzImage"
echo "v3 variant: $variant"

#!/bin/bash
# This script is embedded in the initramfs, not run by the host runner.
set -eu
grep -q 'disposable_md_repro=1' /proc/cmdline || exit 99
[[ -b /dev/vda && -f /work/.fixture-disk ]] || exit 99
cd /work
phase=$1; case_name=$2
level=5; members=3
[[ $case_name == raid6bad ]] && { level=6; members=4; }
total=$((members+1))

state() {
 for field in sync_action reshape_position raid_disks degraded; do
  echo "STATE_$field=$(cat /sys/block/md127/md/$field)"
 done
 cat /proc/mdstat
}

if [[ $phase == prepare ]]; then
 devices=()
 for ((i=0;i<total;i++)); do
  dd if=/dev/zero of=rd$i.img bs=1M count=100 status=none
  losetup /dev/loop$i rd$i.img
  ((i<members)) && devices+=(/dev/loop$i)
 done
 mdadm --create /dev/md127 --metadata=1.2 --level=$level \
  --raid-devices=$members --chunk=512 --bitmap=none --force --run "${devices[@]}"
 for ((n=0;n<60;n++)); do
  [[ $(cat /sys/block/md127/md/sync_action) == idle ]] && break
  sleep 1
 done
 [[ $(cat /sys/block/md127/md/sync_action) == idle ]] || exit 20
 sectors=$(cat /sys/block/md127/size)
 echo "$sectors" > original-sectors
 echo "ORIGINAL_SECTORS=$sectors"
 pattern-check write /dev/md127 "$sectors"
 if [[ $case_name != raid5clean ]]; then
  for ((i=0;i<members;i++)); do
   echo '20000 1' > /sys/block/md127/md/rd$i/bad_blocks
  done
 fi
 sync
 echo 3 > /proc/sys/vm/drop_caches
 pattern-check pre /dev/md127 "$sectors"
 set +e
 timeout -k 2 30 mdadm --grow --add /dev/md127 /dev/loop$members --raid-devices=$total
 growrc=$?
 set -e
 echo "GROW_EXIT=$growrc"
 for ((n=0;n<25;n++)); do
  state
  [[ $(cat /sys/block/md127/md/sync_action) != reshape ]] && break
  sleep 1
 done
else
 devices=()
 for ((i=0;i<total;i++)); do
  losetup /dev/loop$i rd$i.img
  devices+=(/dev/loop$i)
 done
 mdadm --assemble --readonly --run /dev/md127 "${devices[@]}"
 sectors=$(cat original-sectors)
 echo "ORIGINAL_SECTORS=$sectors"
fi

echo CHECK_STATE_BEFORE
state
read-probe /dev/md127 "$sectors"
echo CHECK_STATE_AFTER
state
for ((i=0;i<total;i++)); do
 echo "MEMBER=$i"
 mdadm --examine /dev/loop$i
done

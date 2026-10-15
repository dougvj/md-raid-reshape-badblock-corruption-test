# Resolve the Linux source checkout independently of this fixture's Git repo.
linux_repo() {
 if [[ -n ${LINUX_REPO:-} ]]; then
  printf '%s\n' "$LINUX_REPO"
  return
 fi
 local candidate=$1
 while [[ $candidate != / ]]; do
  if [[ -f "$candidate/Makefile" && -f "$candidate/drivers/md/raid5.c" ]]; then
   printf '%s\n' "$candidate"
   return
  fi
  candidate=$(dirname -- "$candidate")
 done
 echo 'Set LINUX_REPO to your Linux source checkout.' >&2
 return 2
}

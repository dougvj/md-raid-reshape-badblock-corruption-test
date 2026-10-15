"""Copy only the current failure handler into the isolated Chen test tree."""
from pathlib import Path
import subprocess
import sys

source, checkout, snapshot = map(Path, sys.argv[1:])
revision = '788e4139463f74b945600237f7186411015d996e'
assert subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'],
                               text=True).strip() == revision
target = checkout / 'drivers/md/raid5.c'
original = subprocess.check_output(['git', '-C', str(checkout), 'show',
                                    revision + ':drivers/md/raid5.c'], text=True)


def split(text):
    start = text.index('static void handle_failed_reshape(')
    end = text.index('\nstatic int want_replace(', start)
    return text[:start], text[start:end], text[end:]


before, old_handler, after = split(original)
current_before, _, current_after = split(target.read_text())
if current_before != before or current_after != after:
    raise SystemExit('Test checkout has edits outside the handler; leaving it untouched.')
_, handler, _ = split(source.read_text())
if 'MD_RECOVER_FROZEN' in handler:
    raise SystemExit('Fix MD_RECOVER_FROZEN to MD_RECOVERY_FROZEN in your source first.')
snapshot.write_text(handler)
target.write_text(before + handler + after)
print('Handler copied from:', source)
print('Handler snapshot:', snapshot)

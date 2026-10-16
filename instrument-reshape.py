#!/usr/bin/env python3
"""Instrument a disposable raid5.c; refuse already instrumented/unknown layouts."""
import argparse
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('source', type=Path)
p.add_argument('--first', type=int, default=0)
p.add_argument('--last', type=int, default=40000)
a = p.parse_args()
if not 0 <= a.first <= a.last:
    p.error('Require 0 <= first <= last')
s = a.source.read_text()
if 'MDTRACE' in s:
    p.error('Already instrumented')


def replace(old, new):
    global s
    if s.count(old) != 1:
        raise SystemExit(f'Expected exactly one anchor: {old!r}')
    s = s.replace(old, new)


def event(name, expr='sh->sector', fields='', values='', indent=1):
    tabs = '\t' * indent
    return (f'\n{tabs}if ({expr} >= {a.first}ULL && {expr} <= {a.last}ULL)\n'
            f'{tabs}\tpr_info("MDTRACE event={name} sector=%llu{fields}\\n", '
            f'(unsigned long long)({expr}){values});\n')

replace('\tbool was_ready = test_and_clear_bit(STRIPE_EXPAND_READY, &sh->state);',
        '\tbool was_ready = test_and_clear_bit(STRIPE_EXPAND_READY, &sh->state);' +
        event('failed', fields=' expanding=%d ready=%d source=%d failed=%d',
              values=', was_expanding, was_ready, test_bit(STRIPE_EXPAND_SOURCE, &sh->state), s->failed'))
replace('\t\t\tif (test_and_clear_bit(STRIPE_EXPANDING, &sh2->state)) {',
        event('cancel_destination', indent=3, fields=' destination=%llu logical=%llu disk=%d active=%d',
              values=', (unsigned long long)sec, (unsigned long long)bn, dd_idx, test_bit(STRIPE_EXPANDING, &sh2->state)') +
        '\t\t\tif (test_and_clear_bit(STRIPE_EXPANDING, &sh2->state)) {')
replace('\t\t\ttx = async_memcpy(sh2->dev[dd_idx].page,',
        event('copy_submit', indent=3, fields=' destination=%llu logical=%llu source_disk=%d destination_disk=%d',
              values=', (unsigned long long)s, (unsigned long long)bn, i, dd_idx') +
        '\t\t\ttx = async_memcpy(sh2->dev[dd_idx].page,')
replace('\t\tsh->reconstruct_state = reconstruct_state_idle;\n\t\tclear_bit(STRIPE_EXPANDING, &sh->state);',
        event('destination_write_submit', indent=2) +
        '\t\tsh->reconstruct_state = reconstruct_state_idle;\n\t\tclear_bit(STRIPE_EXPANDING, &sh->state);')
# Both checkpoint paths matter; explicit count prevents silently missing a path.
anchor='\t\tmddev->reshape_position = conf->reshape_progress;'
if s.count(anchor) != 2:
    raise SystemExit('Expected two checkpoint sites')
s=s.replace(anchor, '\t\tpr_info("MDTRACE event=checkpoint progress=%llu safe=%llu intr=%d\\n",\n'
            '\t\t\t(unsigned long long)conf->reshape_progress,\n'
            '\t\t\t(unsigned long long)conf->reshape_safe,\n'
            '\t\t\ttest_bit(MD_RECOVERY_INTR, &mddev->recovery));\n'+anchor)
a.source.write_text(s)

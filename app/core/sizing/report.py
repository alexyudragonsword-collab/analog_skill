"""The completed-run record and its human-readable reports.

``SizingRun`` is what ``optimize()`` returns, what the GUI displays and
what :mod:`.runs` persists.  Its ``report()`` method and the
``change_summary()`` next to it are presentation over the layers below —
registry, scorer, evaluator — which is why they live here rather than
with the plain dataclasses in :mod:`.spec`.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.sizing.assets import parse_variables
from app.core.sizing.evaluation import _run_dir, _write_params
from app.core.sizing.registry import SIZING
from app.core.sizing.scoring import _violation
from app.core.sizing.spec import _fmt_num


@dataclass
class SizingRun:
    circuit: str
    best_values: dict
    best_metrics: dict
    best_cost: float
    initial_cost: float
    history: list                 # [(eval_no, best_cost_so_far)]
    evals: int
    cancelled: bool
    elapsed: float
    overrides: dict | None = None
    verified: dict | None = None  # full re-evaluation of the best point

    def report(self) -> str:
        spec = SIZING[self.circuit]
        ov = self.overrides or {}
        lines = [spec.title, '',
                 f'evaluations: {self.evals}'
                 + ('  (cancelled)' if self.cancelled else '')
                 + f'   elapsed: {self.elapsed:.0f}s',
                 f'cost: {self.initial_cost:.4f}  ->  {self.best_cost:.4f}'
                 f'   (FoM {-self.best_cost:.4f})', '',
                 f'{"metric":<22}{"value":>14}   target']
        for ms in spec.metrics:
            target, hard = ov.get(ms.key, (ms.target, ms.hard))
            m = self.best_metrics.get(ms.key)
            if m is None:
                mark, val = '✗', 'n/a'
            else:
                mark = '✓' if _violation(ms, m, target) <= 1e-9 else '✗'
                val = f'{m:.4g}'
            lines.append(f'{ms.label:<22}{val:>14} {ms.unit:<6}'
                         f'{mark} {ms.direction} {target:g}'
                         + ('  [HARD]' if hard else ''))
        if self.verified is not None:
            vkey = SIZING[self.circuit].verify_key
            lines += ['', f'verified (full evaluation, {vkey}):']
            for ms in SIZING[vkey].metrics:
                m = self.verified.get(ms.key)
                val = f'{m:.4g}' if m is not None else 'n/a'
                lines.append(f'  {ms.label:<20}{val:>14} {ms.unit}')
        lines += ['', 'device changes vs default '
                      '(W/L um, M multiplier; before->after):',
                  change_summary(self.circuit, self.best_values)]
        lines += ['', 'best design variables:']
        for k, v in self.best_values.items():
            lines.append(f'  {k} = {_fmt_num(v)}')
        return '\n'.join(lines)

    def params_text(self) -> str:
        """Best sizing as a .PARAM file (same shape as the shipped one);
        skill circuits export a plain name = value listing instead."""
        spec = SIZING[self.circuit]
        if spec.kind == 'skill':
            return '\n'.join(f'{k} = {_fmt_num(v)}'
                             for k, v in self.best_values.items()) + '\n'
        buf = Path(_run_dir(self.circuit) / 'best_params.spice')
        _write_params(spec, self.best_values, buf)
        return buf.read_text()


_MOS_VAR = re.compile(r'^(MOSFET_\d+_\d+)_([WLM])_(\w+)$')


def change_summary(circuit: str, best_values: dict) -> str:
    """Per-device summary of the best sizing vs the shipped defaults.

    AnalogGym variables (MOSFET_<i>_<j>_{W,L,M}_<role>) are grouped into
    one line per device showing its W/L/M before -> after; everything else
    (capacitors, bias currents, skill W.xxx dict entries) gets a flat line.
    Devices are ordered by how much they changed (largest |log ratio|
    first); unchanged variables collapse into a trailing count.
    """
    defaults = {v.name: v.default for v in parse_variables(circuit)}

    def fmt(a: float, b: float) -> str:
        if a == b:
            return _fmt_num(a)
        return f'{_fmt_num(a)}->{_fmt_num(b)}'

    def ratio(a: float, b: float) -> float:
        if a == b:
            return 0.0
        if a == 0 or b == 0:
            return float('inf')
        return abs(np.log(abs(b / a)))

    groups: dict[str, dict] = {}      # device -> {'role':…, 'W':(a,b), …}
    flat: list[tuple[str, float, float]] = []
    unchanged = 0
    for name, a in defaults.items():
        b = best_values.get(name, a)
        m = _MOS_VAR.match(name)
        if m:
            dev, dim, role = m.groups()
            g = groups.setdefault(dev, {'role': role})
            g[dim] = (a, b)
        elif a == b:
            unchanged += 1
        else:
            flat.append((name, a, b))

    lines = []
    dev_rows = []
    for dev, g in groups.items():
        r = max(ratio(*g[d]) for d in 'WLM' if d in g)
        if r == 0.0:
            unchanged += sum(1 for d in 'WLM' if d in g)
            continue
        cell = '  '.join(f'{d} {fmt(*g[d])}' for d in 'WLM' if d in g)
        dev_rows.append((r, f'  {dev:<14}{g["role"]:<18}{cell}'))
    for _rank, row in sorted(dev_rows, key=lambda t: -t[0]):
        lines.append(row)
    for name, a, b in sorted(flat, key=lambda t: -ratio(t[1], t[2])):
        lines.append(f'  {name:<32}{fmt(a, b)}')
    if unchanged:
        lines.append(f'  ({unchanged} variable(s) unchanged)')
    if not lines:
        lines.append('  (no changes vs default)')
    return '\n'.join(lines)

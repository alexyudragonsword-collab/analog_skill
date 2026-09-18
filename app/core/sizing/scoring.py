"""Folding a metric dict into the single cost the optimizer minimizes.

Each metric contributes its relative violation of the circuit's target
(0 when the target is met); hard constraints weigh 10x, and a metric the
simulation failed to produce takes a fixed penalty.

`score_detail` is the same arithmetic without the summing, so that anything
needing to *explain* a cost — the LLM loop's feedback, above all — reads it
from here instead of re-deriving it and drifting.
"""

from dataclasses import dataclass

import numpy as np

from app.core.sizing.registry import SIZING
from app.core.sizing.spec import MetricSpec


_MISSING_PENALTY = 10.0


_HARD_FACTOR = 10.0


def _violation(ms: MetricSpec, m: float, target: float) -> float:
    if ms.direction == 'max':
        v = max(0.0, (target - m) / abs(target))
        if ms.ceiling is not None:            # a band: over the top costs too
            v = max(v, (m - ms.ceiling) / abs(ms.ceiling))
        return v
    if ms.direction == 'min':
        return max(0.0, (m - target) / abs(target))
    if ms.direction == 'absmin':
        return max(0.0, (abs(m) - target) / abs(target))
    # 'target' — note it is met only at exact equality, so no spec in the
    # registry uses it; it stays for overrides and custom circuits.
    return abs(m - target) / abs(target)


@dataclass
class MetricScore:
    """One metric's part of the cost, with the numbers behind it."""

    spec: MetricSpec
    value: float | None       # None when the simulation produced nothing
    target: float
    hard: bool
    violation: float          # relative, 0.0 when the target is met
    contribution: float       # weighted — what this added to the cost

    @property
    def met(self) -> bool:
        return self.value is not None and self.violation <= 0.0


def score_detail(circuit: str, metrics: dict,
                 overrides: dict | None = None) -> list[MetricScore]:
    """Per-metric breakdown of the cost, in the circuit's own metric order.

    max:    penalize (target − m)/|target| when below target; with a
            ceiling, also (m − ceiling)/|ceiling| above it (a band)
    min:    penalize (m − target)/|target| when above target
    absmin: like min on |m|
    target: |m − target|/|target|  (e.g. phase margin 60°)

    overrides: {metric_key: (target, hard)} — GUI-edited targets; a hard
    constraint multiplies its violation by 10.
    """
    overrides = overrides or {}
    out = []
    for ms in SIZING[circuit].metrics:
        target, hard = overrides.get(ms.key, (ms.target, ms.hard))
        w = ms.weight * (_HARD_FACTOR if hard else 1.0)
        m = metrics.get(ms.key)
        if m is None or not np.isfinite(m):
            out.append(MetricScore(ms, None, target, hard,
                                   _MISSING_PENALTY, w * _MISSING_PENALTY))
            continue
        v = min(_violation(ms, m, target), _MISSING_PENALTY)
        out.append(MetricScore(ms, float(m), target, hard, v, w * v))
    return out


def signed_margin(ms: MetricSpec, m: float, target: float) -> float:
    """How far inside its target a metric sits, relative; negative when it
    is outside.  The constrained search maximizes the sum of these once
    every target is met, so it keeps going after feasibility instead of
    stopping at the first point that clears the bar."""
    if ms.direction == 'max':
        v = (m - target) / abs(target)
        if ms.ceiling is not None:
            v = min(v, (ms.ceiling - m) / abs(ms.ceiling))
        return v
    if ms.direction == 'min':
        return (target - m) / abs(target)
    if ms.direction == 'absmin':
        return (target - abs(m)) / abs(target)
    return -abs(m - target) / abs(target)


#: a margin beyond this counts for nothing more — one metric with ten
#: times its target must not buy slack for the rest
MARGIN_CAP = 0.5


def slack(circuit: str, metrics: dict | None,
          overrides: dict | None = None) -> float:
    """Sum of capped signed margins; only meaningful when every target is
    met (the cost is the measure until then).  Missing metrics count as
    nothing."""
    if not metrics:
        return -_MISSING_PENALTY
    overrides = overrides or {}
    total = 0.0
    for ms in SIZING[circuit].metrics:
        target, _hard = overrides.get(ms.key, (ms.target, ms.hard))
        m = metrics.get(ms.key)
        if m is None or not np.isfinite(m):
            total -= _MISSING_PENALTY
            continue
        total += min(signed_margin(ms, float(m), target), MARGIN_CAP)
    return total


def feedback_line(circuit: str, metrics: dict | None,
                  overrides: dict | None = None, limit: int = 5) -> str:
    """One line saying which targets a sizing missed, and by how much.

    Shared by the LLM prompts and the Sizing tab's status line: the same
    sentence a designer would want — "DC gain 62 dB, want >= 100, off
    38%" — not the scalar it folds into.  The worst `limit` contributors
    are named; the met ones are counted, since their slack is the thing
    a fix trades away.
    """
    if not metrics:
        return 'simulation produced no metrics'
    detail = score_detail(circuit, metrics, overrides)
    missed = sorted((d for d in detail if not d.met),
                    key=lambda d: -d.contribution)
    met = len(detail) - len(missed)
    if not missed:
        return f'all {met} targets met'
    parts = []
    for d in missed[:limit]:
        ms = d.spec
        if d.value is None:
            parts.append(f'{ms.label} MISSING')
            continue
        want = {'max': '>=', 'min': '<=', 'absmin': '|x| <=',
                'target': '='}[ms.direction]
        goal = (f'{d.target:.4g}..{ms.ceiling:.4g}' if ms.ceiling is not None
                else f'{want} {d.target:.4g}')
        parts.append(f'{ms.label} {d.value:.4g} {ms.unit} '
                     f'(want {goal}, off {d.violation:.0%})')
    more = f' +{len(missed) - limit} more' if len(missed) > limit else ''
    return f'{met}/{len(detail)} met; ' + '; '.join(parts) + more


def score(circuit: str, metrics: dict, overrides: dict | None = None) -> float:
    """Weighted violation cost against the target specs (0 = all met).

    See score_detail for the per-metric arithmetic; this is its sum, and is
    deliberately not a second implementation of it.
    """
    return sum(d.contribution
               for d in score_detail(circuit, metrics, overrides))

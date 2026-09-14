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
        return max(0.0, (target - m) / abs(target))
    if ms.direction == 'min':
        return max(0.0, (m - target) / abs(target))
    if ms.direction == 'absmin':
        return max(0.0, (abs(m) - target) / abs(target))
    return abs(m - target) / abs(target)         # 'target'


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

    max:    penalize (target − m)/|target| when below target
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


def score(circuit: str, metrics: dict, overrides: dict | None = None) -> float:
    """Weighted violation cost against the target specs (0 = all met).

    See score_detail for the per-metric arithmetic; this is its sum, and is
    deliberately not a second implementation of it.
    """
    return sum(d.contribution
               for d in score_detail(circuit, metrics, overrides))

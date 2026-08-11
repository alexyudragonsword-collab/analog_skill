"""Folding a metric dict into the single cost the optimizer minimizes.

Each metric contributes its relative violation of the circuit's target
(0 when the target is met); hard constraints weigh 10x, and a metric the
simulation failed to produce takes a fixed penalty.
"""

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


def score(circuit: str, metrics: dict, overrides: dict | None = None) -> float:
    """Weighted violation cost against the target specs (0 = all met).

    max:    penalize (target − m)/|target| when below target
    min:    penalize (m − target)/|target| when above target
    absmin: like min on |m|
    target: |m − target|/|target|  (e.g. phase margin 60°)

    overrides: {metric_key: (target, hard)} — GUI-edited targets; a hard
    constraint multiplies its violation by 10.
    """
    overrides = overrides or {}
    cost = 0.0
    for ms in SIZING[circuit].metrics:
        target, hard = overrides.get(ms.key, (ms.target, ms.hard))
        w = ms.weight * (_HARD_FACTOR if hard else 1.0)
        m = metrics.get(ms.key)
        if m is None or not np.isfinite(m):
            cost += w * _MISSING_PENALTY
            continue
        cost += w * min(_violation(ms, m, target), _MISSING_PENALTY)
    return cost

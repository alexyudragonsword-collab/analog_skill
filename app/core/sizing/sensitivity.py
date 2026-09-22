"""A local linear model of the metrics around a point, from the archive.

The finish's measured shape (cairn/pitfalls.md): the model gets the
variables right and the amounts wrong, and the search that got stuck
has just spent hundreds of evaluations near the point it stuck at.
Those evaluations are in the archive.  A weighted linear fit of each
metric over the archive's points nearest the current best gives two
things nothing else here had: sensitivities to put in the finish
prompt ("+10 % of range on CAPACITOR_0 moves the phase margin +6°"),
and a predicted cost along a proposed direction, so the line search
can centre its first scan on the amount the fit expects instead of on
a fixed grid.  Numpy only; the fit is a weighted ridge regression in
the normalised box, metrics that span decades in log.
"""

from dataclasses import dataclass

import numpy as np

from app.core.sizing import archive
from app.core.sizing.registry import SIZING
from app.core.sizing.scoring import score, score_detail
from app.core.sizing.spec import VarSpec

#: points per dimension the fit wants; below MIN_POINTS it is not built
POINTS_PER_DIM = 2
MIN_EXTRA = 8
#: coefficient of determination below which a metric's fit is not
#: shown to the model (its prediction still enters the cost)
SHOW_R2 = 0.5


@dataclass
class LocalModel:
    names: list
    center: np.ndarray            # normalised point the fit is around
    keys: list                    # metrics fitted
    coef: dict                    # key -> (dims,) slope in transformed y
    intercept: dict               # key -> transformed y at the centre
    log: dict                     # key -> bool, fitted as log10(y)
    r2: dict                      # key -> weighted in-sample R²
    n: int                        # points used
    radius: float                 # normalised distance to the farthest

    def predict(self, xn) -> dict:
        d = np.clip(np.asarray(xn, float), 0, 1) - self.center
        out = {}
        for k in self.keys:
            t = self.intercept[k] + float(self.coef[k] @ d)
            out[k] = float(10 ** t) if self.log[k] else float(t)
        return out

    def cost(self, xn, overrides=None, circuit: str = '') -> float:
        return score(circuit, self.predict(xn), overrides)

    def effect(self, key: str, i: int, step: float = 0.1) -> float:
        """Change of metric `key` for +`step` of variable i's range."""
        t0 = self.intercept[key]
        t1 = t0 + self.coef[key][i] * step
        return (10 ** t1 - 10 ** t0) if self.log[key] else (t1 - t0)


def fit(circuit: str, variables: list[VarSpec], center_values: dict,
        rows: list[dict] | None = None) -> LocalModel | None:
    """The model around `center_values`, or None when the archive holds
    too few points with these variables (POINTS_PER_DIM per dimension
    plus MIN_EXTRA)."""
    names = [v.name for v in variables]
    lo = np.array([v.lo for v in variables], float)
    hi = np.array([v.hi for v in variables], float)
    span = np.where(hi > lo, hi - lo, 1.0)
    dims = len(names)
    want = set(names)
    if rows is None:
        rows = archive.load(circuit)
    rows = [r for r in rows if set(r['values']) == want and r['metrics']]
    need = POINTS_PER_DIM * dims + MIN_EXTRA
    if len(rows) < need:
        return None
    X = (np.array([[r['values'][n] for n in names] for r in rows], float)
         - lo) / span
    c = np.clip((np.array([center_values[n] for n in names], float) - lo)
                / span, 0, 1)
    dist = np.linalg.norm(X - c, axis=1)
    take = np.argsort(dist)[:max(need, min(len(rows), 4 * dims))]
    X, rows, dist = X[take], [rows[i] for i in take], dist[take]
    radius = float(dist.max()) or 1e-9
    w_all = np.exp(-(dist / radius) ** 2)
    keys = [m.key for m in SIZING[circuit].metrics]
    model = LocalModel(names, c, [], {}, {}, {}, {}, len(rows), radius)
    D = X - c
    for k in keys:
        has = np.array([k in r['metrics'] and np.isfinite(r['metrics'][k])
                        for r in rows])
        if has.sum() < dims + 3:
            continue
        y = np.array([r['metrics'][k] for r, h in zip(rows, has, strict=True)
                      if h], float)
        use_log = bool(y.min() > 0 and y.max() / y.min() > 10)
        t = np.log10(y) if use_log else y
        w = w_all[has]
        Dh = D[has]
        # columns scaled to unit weighted norm, so the ridge (which keeps
        # a fit with fewer points than dimensions sane, and pins a
        # variable the archive never varied at zero slope) is relative
        # to each column's own spread, not to the intercept's
        scale = np.sqrt((w[:, None] * Dh ** 2).sum(axis=0)) + 1e-12
        A = np.hstack([np.ones((has.sum(), 1)), Dh / scale])
        Aw = A * w[:, None]
        reg = 1e-3 * np.eye(A.shape[1])
        reg[0, 0] = 0.0
        beta = np.linalg.solve(Aw.T @ A + reg, Aw.T @ t)
        pred = A @ beta
        beta = np.concatenate([[beta[0]], beta[1:] / scale])
        ss_res = float(np.sum(w * (t - pred) ** 2))
        mean = float(np.sum(w * t) / np.sum(w))
        ss_tot = float(np.sum(w * (t - mean) ** 2)) or 1e-30
        model.keys.append(k)
        model.intercept[k], model.coef[k] = float(beta[0]), beta[1:]
        model.log[k], model.r2[k] = use_log, max(0.0, 1 - ss_res / ss_tot)
    return model if model.keys else None


def lines(model: LocalModel, circuit: str, metrics: dict,
          overrides=None, top: int = 3) -> list[str]:
    """Prompt lines: for every missed target, the variables whose +10 %
    of range moves it most, with the size of the move and its largest
    side effect on a met target.  Fits below SHOW_R2 are left out."""
    detail = score_detail(circuit, metrics, overrides)
    missed = [d for d in detail if not d.met and d.value is not None]
    met = [d for d in detail if d.met and d.value is not None]
    out = []
    for d in missed:
        k = d.spec.key
        if k not in model.keys or model.r2[k] < SHOW_R2:
            continue
        eff = [(abs(model.effect(k, i)), i) for i in range(len(model.names))]
        eff.sort(reverse=True)
        parts = []
        for _, i in eff[:top]:
            e = model.effect(k, i)
            side = ''
            worst = None
            for m in met:
                mk = m.spec.key
                if mk in model.keys and model.r2[mk] >= SHOW_R2:
                    de = model.effect(mk, i)
                    rel = abs(de) / max(abs(m.target), 1e-30)
                    if worst is None or rel > worst[0]:
                        worst = (rel, mk, de)
            if worst and worst[0] > 0.02:
                side = f' (also {worst[1]} {worst[2]:+.3g})'
            parts.append(f'{model.names[i]} {e:+.3g}{side}')
        out.append(f'  - {k} (now {d.value:.4g}, want {d.spec.rule} '
                   f'{d.target:g}): per +10% of range, '
                   + '; '.join(parts)
                   + f'  [fit on {model.n} nearby evaluations, R² '
                     f'{model.r2[k]:.2f}]')
    return out


def best_alpha(model: LocalModel, circuit: str, xb, direction,
               overrides=None, grid=None) -> float:
    """The multiple of `direction` from `xb` at which the model predicts
    the lowest cost (the search's first scan is centred on it)."""
    grid = np.linspace(0.1, 3.0, 30) if grid is None else grid
    costs = [model.cost(np.clip(xb + a * direction, 0, 1), overrides,
                        circuit) for a in grid]
    return float(grid[int(np.argmin(costs))])

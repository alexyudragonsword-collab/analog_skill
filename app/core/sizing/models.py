"""Metric models trained on a circuit's archive, and proposals from them.

The amortised surrogate (cairn/pitfalls.md, 2026-09-21): sample a
circuit's whole design box once, keep the evaluations, and when the same
circuit gets new targets, let models of its metrics pick candidates in
seconds and SPICE verify a handful.  Measured against a cold search at
200 evaluations on eight target sets: the archive alone won six, the
models added two more (0.27 where the archive had 1.0-1.3).

Gradient-boosted trees, one per metric, plus a classifier for "does this
point simulate at all"; at 512 points and up they matched or beat a
Gaussian process at a hundredth of the fit time, so there is no GP
here.  scikit-learn is optional at runtime: available() gates the
feature.  Models are trained on demand from the archive (about 15 s
for 2000 points) and cached in memory, never pickled — a pickle ties
the app to one scikit-learn version, the archive does not.
"""

import warnings

import numpy as np

from app.core.sizing import archive
from app.core.sizing.registry import SIZING
from app.core.sizing.scoring import score
from app.core.sizing.spec import VarSpec

#: rows with the full metric set needed before a model is trained
MIN_ROWS = 50
#: predicted-failure penalty: a point the classifier thinks will not
#: simulate scores as if it missed two targets
FAIL_PENALTY = 20.0


def available() -> bool:
    try:
        import sklearn                                    # noqa: F401
        return True
    except ImportError:
        return False


class MetricModels:
    """Per-metric regressors and a failure classifier for one circuit.

    keys: the metric keys modelled.  n: archive rows with all of them.
    """

    def __init__(self, circuit: str, names: list[str], keys: list[str],
                 rows: list[dict]):
        from sklearn.ensemble import (HistGradientBoostingClassifier,
                                      HistGradientBoostingRegressor)
        self.circuit, self.names, self.keys = circuit, list(names), list(keys)
        absmin = {m.key for m in SIZING[circuit].metrics
                  if m.direction == 'absmin'}
        X = np.array([[r['values'][n] for n in names] for r in rows], float)
        ok = np.array([all(k in r['metrics'] and np.isfinite(r['metrics'][k])
                           for k in keys) for r in rows])
        self.n = int(ok.sum())
        self.models, self.log = {}, {}
        for k in keys:
            has = np.array([k in r['metrics'] and np.isfinite(r['metrics'][k])
                            for r in rows])
            y = np.array([r['metrics'][k] for r, h in zip(rows, has,
                                                          strict=True) if h],
                         float)
            # metrics that span decades (GBW, power, settling) and the
            # magnitude-judged ones (offset, regulation) are fitted as
            # log |y|: the score reads only |m| of an 'absmin' metric,
            # and a raw fit of a metric whose garbage rows sit at 1e3
            # predicted 5.7 for a line regulation that was 0.004.  The
            # bounded sign-carrying ones (PSRR in dB, phase) stay raw.
            # Either way the 1st/99th percentiles cap what a failed
            # simulation's numbers can pull the fit towards.
            a = np.abs(y)
            self.log[k] = bool(len(y) and (k in absmin or (
                y.min() > 0 and y.max() / max(y.min(), 1e-300) > 100)))
            t = np.log10(a + 1e-15) if self.log[k] else y
            if len(t) > 20:
                t = np.clip(t, *np.percentile(t, [1, 99]))
            m = HistGradientBoostingRegressor(max_iter=500,
                                              learning_rate=0.05,
                                              random_state=0)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                m.fit(X[has], t)
            self.models[k] = m
        self.clf = None
        if 0 < ok.sum() < len(ok):
            self.clf = HistGradientBoostingClassifier(
                max_iter=300, random_state=0).fit(X, ok)

    def predict(self, points: np.ndarray) -> list[dict]:
        """Metric dicts for rows of physical values (names order)."""
        P = {k: m.predict(points) for k, m in self.models.items()}
        return [{k: float(10 ** P[k][i] if self.log[k] else P[k][i])
                 for k in self.keys} for i in range(len(points))]

    def p_ok(self, points: np.ndarray) -> np.ndarray:
        if self.clf is None:
            return np.ones(len(points))
        return self.clf.predict_proba(points)[:, 1]

    def cost(self, points: np.ndarray, overrides: dict | None = None) -> list:
        """Predicted cost under the targets, failure-penalised."""
        pf = self.p_ok(points)
        return [score(self.circuit, m, overrides) + FAIL_PENALTY * (1 - p)
                for m, p in zip(self.predict(points), pf, strict=True)]


_cache: dict[tuple, MetricModels] = {}


def metric_keys(circuit: str, rows: list[dict]) -> list[str]:
    """The spec's metric keys that the archive actually carries; a circuit
    whose archive holds other keys (a custom scorer) gets those."""
    keys = [m.key for m in SIZING[circuit].metrics]
    have = {k for r in rows for k in r['metrics']}
    keys = [k for k in keys if k in have]
    return keys or sorted(have)


def train(circuit: str, names: list[str]) -> MetricModels:
    """Models for the circuit's archive rows with exactly these variables;
    cached per archive size.  ValueError below MIN_ROWS complete rows."""
    rows = [r for r in archive.load(circuit) if set(r['values']) == set(names)]
    keys = metric_keys(circuit, rows)
    complete = sum(all(k in r['metrics'] for k in keys) for r in rows)
    if complete < MIN_ROWS:
        raise ValueError(f'{complete} archived evaluations with all metrics; '
                         f'{MIN_ROWS} needed — characterise the circuit '
                         '(Sobol sample) first')
    key = (circuit, tuple(names), len(rows))
    if key not in _cache:
        _cache.clear()                       # one circuit at a time
        _cache[key] = MetricModels(circuit, names, keys, rows)
    return _cache[key]


def propose(circuit: str, variables: list[VarSpec],
            overrides: dict | None = None, k: int = 8,
            seed: int = 0) -> tuple[list[dict], list[float], MetricModels]:
    """k distinct candidate points (physical values) from CMA-ES on the
    models, started at the archive's best under the targets; the
    archive's own top points compete for the k slots.  Returns
    (points, predicted costs, models)."""
    import cma
    names = [v.name for v in variables]
    lo = np.array([v.lo for v in variables], float)
    hi = np.array([v.hi for v in variables], float)
    span = np.where(hi > lo, hi - lo, 1.0)
    is_int = np.array([v.is_int for v in variables])
    mm = train(circuit, names)
    rows = [r for r in archive.load(circuit) if set(r['values']) == set(names)]
    A = np.array([[r['values'][n] for n in names] for r in rows], float)

    def to_phys(xn):
        x = np.clip(np.atleast_2d(xn), 0, 1) * span + lo
        return np.where(is_int, np.round(x), x)

    arch_cost = np.array([score(circuit, r['metrics'], overrides)
                          for r in rows])
    start = np.clip((A[int(np.argmin(arch_cost))] - lo) / span, 0, 1)
    es = cma.CMAEvolutionStrategy(start, 0.2, {
        'bounds': [0.0, 1.0], 'popsize': 32, 'maxfevals': 6000,
        'seed': seed + 1, 'verbose': -9, 'verb_disp': 0, 'verb_log': 0})
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        while not es.stop():
            sol = es.ask()
            es.tell(sol, mm.cost(to_phys(np.array(sol)), overrides))
    top = np.argsort(arch_cost)[:k]
    cand = np.vstack([to_phys(es.result.xbest), to_phys(np.array(sol)),
                      A[top]])
    pc = mm.cost(cand, overrides)
    picked, costs = [], []
    for i in np.argsort(pc):
        xn = (cand[i] - lo) / span
        if all(np.linalg.norm(xn - (p - lo) / span) > 0.05 for p in picked):
            picked.append(cand[i])
            costs.append(float(pc[i]))
        if len(picked) == k:
            break
    return ([dict(zip(names, p.tolist(), strict=True)) for p in picked],
            costs, mm)

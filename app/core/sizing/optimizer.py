"""The optimization loop: evaluate -> score -> propose, under a budget.

Four algorithms share one driver (budget accounting, cancellation and
parallel evaluation slots): the built-in Sobol+Powell search, SciPy
differential evolution, Optuna TPE, and the LLM-guided loop in
:mod:`app.core.llm_sizing`.
"""

import time

import numpy as np

from app.core.sizing.evaluation import evaluate
from app.core.sizing.registry import SIZING
from app.core.sizing.report import SizingRun
from app.core.sizing.scoring import score
from app.core.sizing.spec import VarSpec


class _Cancelled(Exception):
    pass


def optuna_available() -> bool:
    try:
        import optuna                                     # noqa: F401
        return True
    except ImportError:
        return False


def optimize(circuit: str, variables: list[VarSpec], budget: int = 60,
             progress=None, should_cancel=None, overrides: dict | None = None,
             algo: str = 'sobol_powell', workers: int = 1) -> SizingRun:
    """Bounded search, ≤ budget evaluations, optionally parallel.

    algo:
      'sobol_powell'    (built-in) — evaluate the default sizing plus a
                        scrambled-Sobol sample around it (parallel batch,
                        ~half the budget), then refine the best point with
                        bounded Powell (serial by nature).
      'diff_evolution'  scipy differential_evolution with a thread-pool map
                        (population 4x dims per generation — needs larger
                        budgets), polish disabled.
      'optuna'          TPE via batch ask/tell (if optuna is installed).
      'llm'             LLM-in-the-loop (needs an API key in Settings):
                        the model proposes candidates in physical units,
                        every candidate is measured by ngspice, costs are
                        fed back; malformed replies fall back to Sobol
                        points for that round (see llm_sizing.run_loop).

    workers > 1 runs evaluations concurrently (each in its own run
    sub-directory).  circuit-skills circuits are forced serial: their
    evaluation mutates process-global state (sys.modules isolation +
    module-global parameters).

    overrides: {metric_key: (target, hard)} — see score().
    progress(eval_no, best_cost, metrics) fires after every evaluation;
    should_cancel() → True stops dispatching (in-flight evals finish,
    best-so-far is kept).
    """
    import queue as _queue
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from scipy.optimize import minimize
    from scipy.stats import qmc

    spec = SIZING[circuit]
    if spec.kind == 'skill':
        workers = 1
    workers = max(1, int(workers))

    names = [v.name for v in variables]
    lo = np.array([v.lo for v in variables], float)
    hi = np.array([v.hi for v in variables], float)
    span = np.where(hi > lo, hi - lo, 1.0)
    is_int = np.array([v.is_int for v in variables])
    x0 = (np.array([v.default for v in variables], float) - lo) / span

    lock = threading.Lock()
    state = {'done': 0, 'dispatched': 0, 'best': None, 'best_x': None,
             'best_m': {}, 'best_xn': x0, 'history': [], 'cancel': False}
    slots = _queue.SimpleQueue()
    for i in range(workers):
        slots.put(i)
    t0 = time.time()

    def to_values(xn):
        x = np.clip(xn, 0, 1) * span + lo
        x = np.where(is_int, np.round(x), x)
        return dict(zip(names, x.tolist(), strict=True))

    def _cancelled():
        return should_cancel is not None and should_cancel()

    def _eval_one(xn):
        slot = slots.get()
        try:
            vals = to_values(xn)
            metrics = evaluate(circuit, vals, slot=slot,
                               single_thread=workers > 1)
        finally:
            slots.put(slot)
        c = score(circuit, metrics, overrides)
        with lock:
            state['done'] += 1
            if state['best'] is None or c < state['best']:
                state['best'], state['best_x'] = c, vals
                state['best_m'] = metrics
                state['best_xn'] = np.asarray(xn, float)
            n, best = state['done'], state['best']
            state['history'].append((n, best))
        if progress is not None:
            progress(n, best, metrics)
        return c

    def _safe_eval(xn):
        try:
            return _eval_one(xn)
        except Exception:                     # sim failure → worst cost
            return float('inf')

    def run_batch(points):
        """Evaluate ≤ remaining-budget points (parallel); rest stay +inf."""
        points = [np.asarray(p, float) for p in points]
        with lock:
            if _cancelled():
                state['cancel'] = True
            allowed = 0 if state['cancel'] else max(
                0, budget - state['dispatched'])
            todo = points[:allowed]
            state['dispatched'] += len(todo)
        out = [float('inf')] * len(points)
        if not todo:
            return out
        if workers == 1:
            for i, pt in enumerate(todo):
                if _cancelled():
                    with lock:
                        state['cancel'] = True
                        state['dispatched'] -= len(todo) - i   # refund
                    break
                out[i] = _safe_eval(pt)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_safe_eval, pt): i
                        for i, pt in enumerate(todo)}
                for f in as_completed(futs):
                    out[futs[f]] = f.result()
        return out

    def objective(xn):
        """Serial single evaluation (Powell refinement)."""
        with lock:
            if _cancelled():
                state['cancel'] = True
            if state['cancel'] or state['dispatched'] >= budget:
                raise _Cancelled
            state['dispatched'] += 1
        return _safe_eval(xn)

    def run_sobol_powell():
        n_sobol = min(max(budget // 2, 0), max(budget - 5, 0))
        run_batch([x0])                      # evaluation #1: default sizing
        if n_sobol > 1:
            # Sobol sample around the (literature-derived) default sizing:
            # ±25% of each bound span, clipped to the box
            import warnings
            sob = qmc.Sobol(len(names), scramble=True, seed=0)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                pts = sob.random(n_sobol - 1)
            run_batch([np.clip(x0 + (p - 0.5) * 0.5, 0.0, 1.0) for p in pts])
        if state['cancel'] or state['dispatched'] >= budget:
            return
        minimize(objective, state['best_xn'], method='Powell',
                 bounds=[(0.0, 1.0)] * len(names),
                 options={'maxfev': max(budget - state['dispatched'], 1),
                          'xtol': 1e-3, 'ftol': 1e-4})

    def run_de():
        from scipy.optimize import differential_evolution
        dims = len(names)
        popsize = 4                          # individuals = 4 x dims
        maxiter = max(1, budget // (popsize * dims))
        differential_evolution(
            lambda xn: run_batch([xn])[0],   # only used if scipy bypasses map
            bounds=[(0.0, 1.0)] * dims, x0=x0, init='sobol',
            popsize=popsize, maxiter=maxiter, polish=False, tol=0.0,
            seed=0, updating='deferred',
            workers=lambda func, xs: run_batch(list(xs)),
            callback=lambda xk, convergence=0.0:
                state['cancel'] or state['dispatched'] >= budget)

    def run_optuna():
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(
            direction='minimize',
            sampler=optuna.samplers.TPESampler(seed=0))
        study.enqueue_trial(
            {n: float(x) for n, x in zip(names, x0, strict=True)})
        while not state['cancel'] and state['dispatched'] < budget:
            k = min(workers, budget - state['dispatched'])
            trials = [study.ask() for _ in range(k)]
            xs = [np.array([t.suggest_float(n, 0.0, 1.0) for n in names])
                  for t in trials]
            costs = run_batch(xs)
            for t, c in zip(trials, costs, strict=True):
                study.tell(t, c if np.isfinite(c) else 1e12)

    def run_llm():
        from app.core import llm_sizing
        llm_sizing.run_loop(circuit, variables, overrides,
                            state=state, run_batch=run_batch,
                            budget=budget, workers=workers)

    try:
        if algo == 'optuna':
            run_optuna()
        elif algo == 'diff_evolution':
            run_de()
        elif algo == 'llm':
            run_llm()
        else:
            run_sobol_powell()
    except _Cancelled:
        pass
    verified = None
    if (spec.verify_key and state['best_x'] is not None
            and not state['cancel']):
        print(f'verifying best point with a full {spec.verify_key} '
              'evaluation ...')
        try:
            verified = evaluate(spec.verify_key, state['best_x'])
        except Exception as exc:                 # keep the proxy result
            print(f'verification failed: {exc}')
    initial_cost = state['history'][0][1] if state['history'] else float('inf')
    return SizingRun(circuit=circuit,
                     best_values=state['best_x'] or to_values(x0),
                     best_metrics=state['best_m'],
                     best_cost=state['best'] if state['best'] is not None
                     else float('inf'),
                     initial_cost=initial_cost, history=state['history'],
                     evals=state['done'], cancelled=state['cancel'],
                     elapsed=time.time() - t0, overrides=overrides,
                     verified=verified)

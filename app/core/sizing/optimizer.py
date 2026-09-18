"""The optimization loop: evaluate -> score -> propose, under a budget.

Ten algorithms share one driver (budget accounting, cancellation and
parallel evaluation slots): the built-in Sobol+Powell search, SciPy
differential evolution and four things built on it (a Powell polish, a
constrained formulation, a seed portfolio, and the LLM finish), CMA-ES
with restarts, Optuna TPE, and the two LLM-driven loops in
:mod:`app.core.llm_sizing`.
"""

import time

import numpy as np

from app.core.sizing.evaluation import evaluate
from app.core.sizing.registry import SIZING
from app.core.sizing.report import DE_ALGOS, SizingRun
from app.core.sizing.scoring import _MISSING_PENALTY, score, score_detail, slack
from app.core.sizing.spec import VarSpec


class _Cancelled(Exception):
    pass


def optuna_available() -> bool:
    try:
        import optuna                                     # noqa: F401
        return True
    except ImportError:
        return False


def cmaes_available() -> bool:
    try:
        import cma                                        # noqa: F401
        return True
    except ImportError:
        return False


#: seeds a portfolio runs before continuing the best of them
PORTFOLIO_SEEDS = 3

#: share of the budget de_powell keeps for the polish.  Powell in 30
#: dimensions spends ~4 evaluations per dimension per pass; a quarter of
#: 600 is about one pass, serial.
POLISH_SHARE = 0.25


def optimize(circuit: str, variables: list[VarSpec], budget: int = 60,
             progress=None, should_cancel=None, overrides: dict | None = None,
             algo: str = 'sobol_powell', workers: int = 1,
             seed: int = 0, resume: SizingRun | None = None) -> SizingRun:
    """Bounded search, ≤ budget evaluations, optionally parallel.

    algo:
      'sobol_powell'    (built-in) — evaluate the default sizing plus a
                        scrambled-Sobol sample around it (parallel batch,
                        ~half the budget), then refine the best point with
                        bounded Powell (serial by nature).
      'llm_agent'       hands the model a tool and one prompt and lets it
                        drive: it chooses what to simulate, how many at a
                        time, and when to change its mind, instead of
                        answering a fixed question each round.  Needs the
                        Claude Code provider.  Not measured as better than
                        'llm' — a different control loop, not a better one.
      'diff_evolution'  scipy differential_evolution with a thread-pool map
                        (population 4x dims per generation — needs larger
                        budgets), polish disabled.
      'de_powell'       'diff_evolution' for 1 - POLISH_SHARE of the
                        budget, then bounded Powell from its best point
                        with the rest (serial).  The finish's line search
                        without the model: a local polish DE never does.
      'de_constrained'  DE with every metric as a constraint under
                        SciPy's feasibility rules (Lampinen): an
                        infeasible trial replaces its parent only if it
                        is no worse on *every* metric — a trade that
                        fixes one target by breaking another is refused,
                        where the summed cost would take it — feasible
                        points compete on the summed margin inside the
                        targets, so the search keeps widening margins
                        after the first feasible point.  Each generation
                        is one parallel batch; the objective reads the
                        metrics the constraint call cached.
      'de_portfolio'    PORTFOLIO_SEEDS independent DE populations for
                        the first half of the budget, then the best of
                        them continued with the second half.  Needs
                        seven generations of budget (4 x dims each);
                        below that it is plain DE and the notes say so.
                        Built on the measured fact that seeds disagree
                        on every circuit DE does not finish outright.
      'cmaes'           CMA-ES (pycma) with IPOP restarts: when a run
                        stalls, restart with twice the population from a
                        fresh point until the budget is spent.  Batches
                        of max(workers, 4 + 3 ln dims) per generation.
      'de_llm_finish'   'diff_evolution' for all but the last few
                        evaluations, then up to FINISH_ROUNDS rounds of:
                        one LLM call to name the fix for whatever is
                        still missed, and a line search along the
                        model's proposal (see llm_sizing.run_finish).
                        Any LLM provider.
                        Measured: DE alone converges short of the phase
                        margin target and stays there; the model picks
                        the right variables and the wrong amounts; the
                        line search supplies the amounts.
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
    seed: for the Sobol sample, DE's population and Optuna's sampler.  A
    run is repeatable at a given seed; on this problem DE's endpoint
    depends on it a great deal (five seeds at 60 evaluations spanned
    0.66-3.31), so a second seed is the cheapest second opinion.
    progress(eval_no, best_cost, metrics) fires after every evaluation;
    should_cancel() → True stops dispatching (in-flight evals finish,
    best-so-far is kept).

    resume: a DE-based run to carry on from.  Its last population seeds
    this search and its members' costs are served from memory, so the
    `budget` here is all new evaluations — re-running at twice the budget
    replays the first half, which is what this exists to avoid.  The run
    must be the same circuit and variables and one of DE_ALGOS; the
    previous best is this run's starting point.  Raises ValueError
    otherwise.
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
    # 'cap' is the ceiling a phase may dispatch up to (<= budget); the
    # two-phase algorithm lowers it for the search so the finish is left
    # something to spend.
    state = {'done': 0, 'dispatched': 0, 'best': None, 'best_x': None,
             'best_m': {}, 'best_xn': x0, 'history': [], 'cancel': False,
             'cap': budget, 'notes': '', 'population': None,
             'pop_costs': None}
    # known costs, normalized point -> cost: a continued run's inherited
    # population.  Hits cost nothing and count nothing.
    memo: dict[tuple, float] = {}
    init_pop = 'sobol'
    if resume is not None:
        if algo not in DE_ALGOS:
            raise ValueError(f'{algo} has no population to continue')
        if (not resume.continuable or resume.circuit != circuit
                or list(resume.best_values) != names):
            raise ValueError('this run cannot be continued: it has no '
                             'population, or the circuit or variables '
                             'differ')
        rows = (np.array(resume.population, float) - lo) / span
        init_pop = np.clip(rows, 0.0, 1.0)
        for row, c in zip(init_pop, resume.population_costs, strict=True):
            if c is not None and np.isfinite(c):
                memo[tuple(np.round(row, 12))] = float(c)
        state['best'] = resume.best_cost
        state['best_x'], state['best_m'] = (dict(resume.best_values),
                                            dict(resume.best_metrics))
        state['best_xn'] = np.clip((np.array(
            [resume.best_values[n] for n in names]) - lo) / span, 0, 1)
        state['history'].append((0, resume.best_cost))
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
        return c, metrics

    def _safe_eval(xn):
        try:
            return _eval_one(xn)
        except Exception:                     # sim failure → worst cost
            return float('inf'), None

    def run_batch(points, with_metrics=False):
        """Evaluate ≤ remaining-budget points (parallel); rest stay +inf.

        with_metrics returns (costs, metric_dicts) instead of costs — the
        LLM loop needs them to tell the model *which* target it missed, and
        every other algorithm only ever wanted the scalar.
        """
        points = [np.asarray(p, float) for p in points]
        out = [float('inf')] * len(points)
        mets: list[dict | None] = [None] * len(points)
        fresh = []                              # indices still to simulate
        for i, p in enumerate(points):
            known = memo.get(tuple(np.round(p, 12))) if memo else None
            if known is None:
                fresh.append(i)
            else:
                out[i] = known
        with lock:
            if _cancelled():
                state['cancel'] = True
            allowed = 0 if state['cancel'] else max(
                0, min(budget, state['cap']) - state['dispatched'])
            todo = fresh[:allowed]
            state['dispatched'] += len(todo)
        if todo:
            if workers == 1:
                for k, i in enumerate(todo):
                    if _cancelled():
                        with lock:
                            state['cancel'] = True
                            state['dispatched'] -= len(todo) - k   # refund
                        break
                    out[i], mets[i] = _safe_eval(points[i])
            else:
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = {ex.submit(_safe_eval, points[i]): i
                            for i in todo}
                    for f in as_completed(futs):
                        out[futs[f]], mets[futs[f]] = f.result()
        return (out, mets) if with_metrics else out

    def objective(xn):
        """Serial single evaluation (Powell refinement)."""
        with lock:
            if _cancelled():
                state['cancel'] = True
            if (state['cancel']
                    or state['dispatched'] >= min(budget, state['cap'])):
                raise _Cancelled
            state['dispatched'] += 1
        return _safe_eval(xn)[0]      # Powell minimizes a scalar

    def run_sobol_powell():
        n_sobol = min(max(budget // 2, 0), max(budget - 5, 0))
        run_batch([x0])                      # evaluation #1: default sizing
        if n_sobol > 1:
            # Sobol sample around the (literature-derived) default sizing:
            # ±25% of each bound span, clipped to the box
            import warnings
            sob = qmc.Sobol(len(names), scramble=True, seed=seed)
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

    dims = len(names)
    generation = 4 * dims                    # DE individuals per generation

    def keep_population(res):
        """The last generation, in physical units, is what a continued
        run starts from; scipy hands it back whether the loop ran out of
        iterations, budget or was cancelled."""
        pop = np.clip(np.asarray(res.population, float), 0, 1) * span + lo
        pop = np.where(is_int, np.round(pop), pop)
        state['population'] = pop.tolist()
        state['pop_costs'] = [float(c) if np.isfinite(c) else None
                              for c in res.population_energies]

    def run_de(limit: int = budget, seed_: int = seed, init=None,
               evals: int | None = None, objective_fn=None,
               constraints=()):
        """One DE search up to `limit` dispatched evaluations.  `init` is a
        population to start from (else the resumed run's, else Sobol);
        `evals` sizes the generation count when `limit` includes earlier
        phases.  Returns scipy's result, population included."""
        from scipy.optimize import differential_evolution
        init = init_pop if init is None else init
        maxiter = max(1, (evals if evals is not None else limit)
                      // generation)
        # scipy batches a constraint call only in vectorized mode, and
        # vectorized excludes workers — so the constrained form supplies
        # a (N, S) objective of its own and the plain form keeps the map
        par = ({'vectorized': True} if constraints
               else {'workers': lambda func, xs: run_batch(list(xs))})
        res = differential_evolution(
            objective_fn or (lambda xn: run_batch([xn])[0]),
            bounds=[(0.0, 1.0)] * dims,
            x0=x0 if isinstance(init, str) else None, init=init,
            popsize=4, maxiter=maxiter, polish=False, tol=0.0,
            seed=seed_, updating='deferred', constraints=constraints,
            callback=lambda xk, convergence=0.0:
                state['cancel'] or state['dispatched'] >= limit, **par)
        keep_population(res)
        return res

    def run_de_powell():
        state['cap'] = max(int(budget * (1 - POLISH_SHARE)), budget // 2)
        run_de(state['cap'])
        state['cap'] = budget
        if state['cancel'] or state['dispatched'] >= budget:
            return
        before, at = state['best'], state['dispatched']
        minimize(objective, state['best_xn'], method='Powell',
                 bounds=[(0.0, 1.0)] * dims,
                 options={'maxfev': max(budget - state['dispatched'], 1),
                          'xtol': 1e-3, 'ftol': 1e-4})
        state['notes'] = (f'powell polish: {state["dispatched"] - at} '
                          f'evaluations, cost {before:.4f} -> '
                          f'{state["best"]:.4f}')

    def run_de_constrained():
        from scipy.optimize import NonlinearConstraint
        # the constraint call sees the whole trial population at once, so
        # it is where the parallel batch runs; the objective, which scipy
        # asks only for the feasible members, reads what that call cached
        cache: dict[tuple, tuple] = {}
        n_con = len(spec.metrics)

        def key(xn):
            return tuple(np.round(np.asarray(xn, float), 12))

        def violations(xT):
            X = np.atleast_2d(np.asarray(xT, float).T)          # (S, N)
            todo = [x for x in X if key(x) not in cache]
            if todo:
                costs, mets = run_batch(todo, with_metrics=True)
                for x, c, m in zip(todo, costs, mets, strict=True):
                    cache[key(x)] = (c, m)
            rows = []
            for x in X:
                c, m = cache[key(x)]
                if m is None or not np.isfinite(c):
                    rows.append([_MISSING_PENALTY] * n_con)
                else:
                    rows.append([d.contribution for d in
                                 score_detail(circuit, m, overrides)])
            return np.asarray(rows).T                            # (M, S)

        def objective_fn(xT):
            # (N, S) in vectorized mode, (N,) when scipy asks for one;
            # every point here was just simulated by the constraint call
            X = np.atleast_2d(np.asarray(xT, float).T)
            out = []
            for x in X:
                hit = cache.get(key(x))
                if hit is None:
                    costs, mets = run_batch([x], with_metrics=True)
                    hit = cache[key(x)] = (costs[0], mets[0])
                c, m = hit
                out.append(1e12 if m is None else -slack(circuit, m, overrides))
            return np.asarray(out) if np.ndim(xT) == 2 else out[0]

        res = run_de(objective_fn=objective_fn, constraints=(
            NonlinearConstraint(violations, -np.inf, 0.0),))
        # scipy's answer is the best *feasible* member by objective; the
        # driver tracked the least-violating one, which among feasible
        # points is whichever came first.  Prefer scipy's when it is
        # feasible, so the report shows the widest margins, not the first.
        hit = cache.get(key(res.x))
        if hit and hit[1] is not None and hit[0] == 0.0:
            with lock:
                state['best'], state['best_m'] = 0.0, hit[1]
                state['best_x'] = to_values(res.x)
                state['best_xn'] = np.asarray(res.x, float)
            state['notes'] = (f'constrained: feasible, margin sum '
                              f'{slack(circuit, hit[1], overrides):.3f}')
        else:
            state['notes'] = 'constrained: no feasible point found'

    def run_de_portfolio():
        # half the budget split across the seeds, whole generations each,
        # at least two (an initial sample alone says nothing about a seed)
        per = (budget // 2 // PORTFOLIO_SEEDS) // generation * generation
        if per < 2 * generation:
            state['notes'] = (f'portfolio needs {4 * PORTFOLIO_SEEDS * generation} '
                              f'evaluations ({PORTFOLIO_SEEDS} seeds x 2 '
                              f'generations of {generation}, then as much '
                              f'again to continue); ran plain DE with {budget}')
            run_de()
            return
        tried = []
        for k in range(PORTFOLIO_SEEDS):
            if state['cancel']:
                return
            state['cap'] = state['dispatched'] + per
            res = run_de(state['cap'], seed_=seed + k, init='sobol',
                         evals=per)
            finite = np.isfinite(res.population_energies)
            best = float(res.population_energies[finite].min()) \
                if finite.any() else float('inf')
            tried.append((best, seed + k, res))
        state['cap'] = budget
        best, chosen, res = min(tried, key=lambda t: t[0])
        for row, c in zip(res.population, res.population_energies,
                          strict=True):
            if np.isfinite(c):
                memo[tuple(np.round(row, 12))] = float(c)
        state['notes'] = ('portfolio: ' + ', '.join(
            f'seed {s} {b:.4f}' for b, s, _ in tried)
            + f' after {per} evaluations each; continued seed {chosen}')
        if not state['cancel'] and state['dispatched'] < budget:
            run_de(budget, seed_=chosen, init=np.asarray(res.population),
                   evals=budget - state['dispatched'])

    def run_cmaes():
        import cma
        rng = np.random.default_rng(seed)
        lam = max(workers, 4 + int(3 * np.log(dims)))
        start, restarts, lines = x0, 0, []
        while not state['cancel'] and state['dispatched'] < budget:
            es = cma.CMAEvolutionStrategy(start, 0.25, {
                'bounds': [0.0, 1.0], 'popsize': lam,
                'seed': seed + restarts + 1,
                'maxfevals': budget - state['dispatched'],
                'tolfun': 1e-6, 'tolx': 1e-4,
                'verbose': -9, 'verb_disp': 0, 'verb_log': 0})
            at = state['dispatched']
            while (not es.stop() and not state['cancel']
                   and state['dispatched'] < budget):
                X = es.ask()
                costs = run_batch(X)
                es.tell(X, [c if np.isfinite(c) else 1e12 for c in costs])
            lines.append(f'run {restarts}: popsize {lam}, '
                         f'{state["dispatched"] - at} evaluations, best '
                         f'{es.best.f:.4f}, stopped on '
                         f'{", ".join(es.stop()) or "budget"}')
            # IPOP: a stalled run restarts with twice the population from
            # a fresh point; the larger population is what makes the next
            # basin reachable, the fresh point is what makes it different
            restarts += 1
            lam *= 2
            start = rng.uniform(0.0, 1.0, dims)
        state['notes'] = '\n'.join(lines)

    def run_optuna():
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(
            direction='minimize',
            sampler=optuna.samplers.TPESampler(seed=seed))
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

    def run_llm_agent():
        from app.core import llm_sizing
        note = llm_sizing.run_agent_loop(circuit, variables, overrides,
                                         state=state, run_batch=run_batch,
                                         budget=budget, workers=workers)
        if note:
            state['notes'] = str(note)
            print(f'llm agent: {str(note)[:600]}')

    def run_de_llm_finish():
        from app.core import llm_sizing
        # the reserve is a floor, not a share: the finish needs a fixed
        # handful of points, and a tiny budget still has to leave it some
        state['cap'] = max(budget - llm_sizing.finish_reserve(), budget // 2)
        run_de(state['cap'])
        state['cap'] = budget
        if state['cancel'] or state['dispatched'] >= budget:
            return
        note = llm_sizing.run_finish(circuit, variables, overrides,
                                     state=state, run_batch=run_batch,
                                     budget=budget, workers=workers)
        state['notes'] = note
        print(f'llm finish: {note}')

    try:
        if algo == 'optuna':
            run_optuna()
        elif algo == 'diff_evolution':
            run_de()
        elif algo == 'de_llm_finish':
            run_de_llm_finish()
        elif algo == 'de_powell':
            run_de_powell()
        elif algo == 'de_constrained':
            run_de_constrained()
        elif algo == 'de_portfolio':
            run_de_portfolio()
        elif algo == 'cmaes':
            run_cmaes()
        elif algo == 'llm':
            run_llm()
        elif algo == 'llm_agent':
            run_llm_agent()
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
                     verified=verified, algo=algo, seed=seed, budget=budget,
                     notes=state['notes'], population=state['population'],
                     population_costs=state['pop_costs'])

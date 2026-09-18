"""Persisting completed runs as JSON in the user-data store.

Saved runs survive app upgrades (see ``paths.user_data_dir``), so the
document carries a schema version.
"""

from pathlib import Path

from app.core.sizing.assets import _user_data_root
from app.core.sizing.registry import SIZING
from app.core.sizing.optimizer import cmaes_available
from app.core.sizing.report import DE_ALGOS, SizingRun
from app.core.sizing.scoring import feedback_line, score_detail


RUN_SCHEMA = 1


def runs_dir() -> Path:
    d = _user_data_root() / 'sizing_runs'
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_run(run: SizingRun, path: Path | None = None) -> Path:
    """Persist a completed run as JSON (auto-named into runs_dir())."""
    import dataclasses
    import json
    import time as _time
    from app import __version__
    if path is None:
        stamp = _time.strftime('%Y%m%d_%H%M%S')
        path = runs_dir() / f'{run.circuit}_{stamp}.json'
    doc = {'schema': RUN_SCHEMA,
           'saved_at': _time.strftime('%Y-%m-%d %H:%M:%S'),
           'app_version': __version__,
           'run': dataclasses.asdict(run)}
    path = Path(path)
    path.write_text(json.dumps(doc, indent=1))
    return path


def load_run(path: Path) -> SizingRun:
    import json
    doc = json.loads(Path(path).read_text())
    d = doc['run']
    d['history'] = [tuple(h) for h in d.get('history', [])]
    if d.get('overrides'):
        d['overrides'] = {k: tuple(v) for k, v in d['overrides'].items()}
    return SizingRun(**d)


def run_info(path: Path) -> dict:
    """Cheap summary of a saved run for list views."""
    import json
    doc = json.loads(Path(path).read_text())
    r = doc['run']
    return {'path': Path(path), 'saved_at': doc.get('saved_at', ''),
            'circuit': r['circuit'],
            'title': SIZING[r['circuit']].title
            if r['circuit'] in SIZING else r['circuit'],
            'evals': r['evals'], 'best_cost': r['best_cost'],
            'cancelled': r.get('cancelled', False),
            'algo': r.get('algo', ''), 'seed': r.get('seed', 0),
            'budget': r.get('budget', 0),
            'continuable': bool(r.get('population'))
            and r.get('algo', '') in DE_ALGOS}


def list_runs() -> list[Path]:
    return sorted(runs_dir().glob('*.json'))


#: seeds to try before concluding the budget is the problem
SEEDS_BEFORE_MORE_BUDGET = 3

#: "close": this many misses or fewer, none further off than this
CLOSE_MISSES, CLOSE_VIOLATION = 2, 0.10


def next_step(run: SizingRun, infos: list[dict],
              finish_available: bool = True) -> dict:
    """What to try next after `run`, from the evidence this project has.

    Sixteen runs over eight circuits at two seeds, plus one at twice the
    budget (cairn/pitfalls.md, "A second seed on every circuit"): seeds
    disagree on every circuit the search does not finish, in both
    directions; more budget moved the one nothing else could; and the
    finish turns "close" into "done" but is not a rescue from far away.
    Hence the order — finish if close and not yet tried, another seed
    while fewer than SEEDS_BEFORE_MORE_BUDGET have been, then twice the
    budget at the seed that did best.

    `infos` are run_info() dicts for saved runs (any circuit; filtered
    here).  Returns {'missed': str, 'text': str, 'action': None | 'finish'
    | 'seed' | 'budget', 'algo': str, 'seed': int, 'budget': int,
    'resume': bool}; the settings are what to run next, the text is for
    the status line.  'resume' means: continue *this* run from its
    population for `budget` more evaluations rather than start over —
    a DE run that kept its population never replays its first half.
    These are suggestions from a small sample, and the text says so.
    """
    missed = feedback_line(run.circuit, run.best_metrics, run.overrides)
    out = {'missed': missed, 'action': None, 'algo': run.algo,
           'seed': run.seed, 'budget': run.budget or run.evals,
           'resume': False}
    if run.best_cost == 0.0:
        return {**out, 'text': missed + '.'}
    if run.cancelled:
        return {**out, 'text': missed + '. Cancelled; best-so-far kept.'}
    detail = [d for d in score_detail(run.circuit, run.best_metrics,
                                      run.overrides) if not d.met]
    close = (len(detail) <= CLOSE_MISSES
             and all(d.violation <= CLOSE_VIOLATION for d in detail))
    finish = 'cmaes_llm_finish' if cmaes_available() else 'de_llm_finish'
    if close and finish_available and not run.algo.endswith('llm_finish'):
        return {**out, 'action': 'finish', 'algo': finish,
                'text': missed + '. Close — try the AI finish at the same '
                'seed and budget; that is the step measured to turn close '
                'into done.'}
    same = [i for i in infos
            if i['circuit'] == run.circuit and not i['cancelled']
            and i.get('budget', 0) >= out['budget']]
    seeds = {i.get('seed', 0) for i in same} | {run.seed}
    if len(seeds) < SEEDS_BEFORE_MORE_BUDGET:
        nxt = next(s for s in range(1000) if s not in seeds)
        return {**out, 'action': 'seed', 'seed': nxt,
                'text': missed + f'. Try seed {nxt} at the same budget — '
                'seeds disagree on every circuit the search does not '
                f'finish ({len(seeds)} of {SEEDS_BEFORE_MORE_BUDGET} tried).'}
    best = min(same, key=lambda i: i['best_cost'], default=None)
    if run.continuable and not (best and best['best_cost'] < run.best_cost):
        return {**out, 'action': 'budget', 'resume': True,
                'text': missed + f'. {len(seeds)} seeds tried; continue '
                f'this run for {out["budget"]} more evaluations from its '
                'population — on one circuit more budget was what moved '
                'it.'}
    seed = best['seed'] if best and best['best_cost'] < run.best_cost \
        else run.seed
    return {**out, 'action': 'budget', 'seed': seed,
            'budget': 2 * out['budget'],
            'text': missed + f'. {len(seeds)} seeds tried; try twice the '
            f'budget at seed {seed}, the best so far — on one circuit that '
            'was what moved it.'}

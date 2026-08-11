"""Persisting completed runs as JSON in the user-data store.

Saved runs survive app upgrades (see ``paths.user_data_dir``), so the
document carries a schema version.
"""

from pathlib import Path

from app.core.sizing.assets import _user_data_root
from app.core.sizing.registry import SIZING
from app.core.sizing.report import SizingRun


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
            'cancelled': r.get('cancelled', False)}


def list_runs() -> list[Path]:
    return sorted(runs_dir().glob('*.json'))

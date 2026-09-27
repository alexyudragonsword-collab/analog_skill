"""Every point a circuit was ever evaluated at, kept on disk.

Measured 2026-09-21 (cairn/pitfalls.md): the stored evaluations of a
circuit, re-scored under new targets with no model at all, beat a cold
search at 200 evaluations on six of eight target sets, and a warm start
from the best of them won seven.  The optimizer appends every
evaluation here — one JSON line, values and metrics — and the Sizing
tab offers the best known point under the current targets as a start.
Failed evaluations are kept too (empty metrics): they say where the
box does not simulate.
"""

import json
import threading
from pathlib import Path

from app import paths
from app.core.sizing.assets import _user_data_root
from app.core.sizing.scoring import score

_lock = threading.Lock()


def archive_dir() -> Path:
    d = _user_data_root() / 'sizing_archive'
    d.mkdir(parents=True, exist_ok=True)
    return d


def archive_path(circuit: str) -> Path:
    return archive_dir() / f'{circuit}.jsonl'


def record(circuit: str, values: dict, metrics: dict) -> None:
    """Append one evaluation.  Never raises: a full disk must not end a
    search that is otherwise fine."""
    line = json.dumps({'values': {k: float(v) for k, v in values.items()},
                       'metrics': {k: float(v) for k, v in metrics.items()}})
    try:
        with _lock, open(archive_path(circuit), 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def load(circuit: str) -> list[dict]:
    """All recorded evaluations, oldest first; a torn last line (the app
    died mid-write) is skipped."""
    p = archive_path(circuit)
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding='utf-8').splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def size(circuit: str) -> int:
    return len(load(circuit))


def starter_dir() -> Path:
    """The starter archive shipped with the app (tools/build_starter_
    archive.py): the best archived evaluations per built-in circuit."""
    return paths.resources_dir() / 'starter_archive'


def seed_starter() -> list[str]:
    """Copy the starter rows into the user store for every circuit that
    has no archive of its own yet; returns the circuits seeded.

    Measured reason (cairn/pitfalls.md): on amp_leung_nmcf, amp_ramos_pfc,
    ldo_2 and ldo_simple a cold 600-evaluation search does not reach the
    shipped targets at most seeds, while a warm start from the archive's
    best point does — and a fresh installation had no archive.  A user's
    own rows are never touched: a circuit with any archive keeps it.
    Never raises; a read-only install or a full disk must not stop the
    app from starting."""
    seeded = []
    try:
        src = starter_dir()
        if not src.is_dir():
            return seeded
        for f in sorted(src.glob('*.jsonl')):
            dst = archive_path(f.stem)
            if dst.exists():
                continue
            with _lock:
                dst.write_bytes(f.read_bytes())
            seeded.append(f.stem)
    except OSError:
        pass
    return seeded


def best(circuit: str, names: list[str],
         overrides: dict | None = None) -> dict | None:
    """The recorded point with the lowest cost under the given targets,
    among those whose variables are exactly `names` (an imported circuit
    or an edited variable set leaves older rows behind).  None when
    nothing qualifies.  {'cost', 'values', 'metrics', 'n'} — n is how
    many rows qualified."""
    want = set(names)
    out, n = None, 0
    for row in load(circuit):
        if set(row['values']) != want:
            continue
        n += 1
        c = score(circuit, row['metrics'], overrides)
        if out is None or c < out['cost']:
            out = {'cost': c, 'values': row['values'],
                   'metrics': row['metrics']}
    if out is not None:
        out['n'] = n
    return out

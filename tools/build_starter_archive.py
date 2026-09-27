"""Build the starter archive shipped in app/resources/starter_archive.

    python tools/build_starter_archive.py [<user-data dir>]

For every registered built-in circuit, take the archived evaluations
in <user-data dir>/sizing_archive (default: this checkout's own store)
and keep the ROWS best under the circuit's current targets, plus the
PER_METRIC best under each metric alone so a user who edits one target
still finds a point near it.  Rows are written in the archive's own JSONL
form; a fresh installation copies them into its user store on first
start (archive.seed_starter), which is what lets "Try next" offer the
warm start before any search has run — on four circuits a cold
600-evaluation search does not reach the targets and the warm start
from these rows does (cairn/pitfalls.md, "A starter archive").
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ROWS, PER_METRIC = 30, 5


def _take(keep: dict, ranked: list, n: int) -> None:
    for r in ranked[:n]:
        keep.setdefault(json.dumps(r['values'], sort_keys=True), r)


def main() -> int:
    if len(sys.argv) > 1:
        os.environ['ANALOG_USER_DATA_DIR'] = sys.argv[1]
    from app.core import sizing
    from app.core.sizing import archive, scoring
    out = ROOT / 'app' / 'resources' / 'starter_archive'
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for key, spec in sizing.SIZING.items():
        if spec.pkg == 'user':
            continue
        names = {v.name for v in sizing.parse_variables(key)}
        rows = [r for r in archive.load(key)
                if r['metrics'] and set(r['values']) == names]
        if not rows:
            print(f'{key}: nothing archived, skipped')
            continue
        keep: dict[str, dict] = {}
        _take(keep, sorted(rows, key=lambda r: scoring.score(
            key, r['metrics'])), ROWS)
        for ms in spec.metrics:
            # best on this metric alone, among rows that have it: every
            # other target relaxed to where it cannot bind
            relaxed = {o.key: (1e30 if o.direction != 'max' else -1e30,
                               False) for o in spec.metrics if o is not ms}
            have = [r for r in rows if ms.key in r['metrics']]
            _take(keep, sorted(have, key=lambda r: scoring.score(
                key, r['metrics'], relaxed)), PER_METRIC)
        text = ''.join(json.dumps(r) + '\n' for r in keep.values())
        (out / f'{key}.jsonl').write_text(text, encoding='utf-8')
        total += len(keep)
        print(f'{key}: {len(keep)} rows from {len(rows)}')
    (out / 'README.md').write_text(
        '# Starter archive\n\nOne JSONL file per built-in circuit: the '
        'best archived evaluations under the shipped targets and under '
        'each metric alone, in the archive\'s own row form.  Copied into '
        'the user store on first start (app.core.sizing.archive.'
        'seed_starter) so the warm start has something to start from.  '
        'Regenerate with tools/build_starter_archive.py; never edit by '
        'hand.\n')
    print(f'{total} rows written to {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Run the gmoverid physical self-checks from the GUI.

Reuses the five importable check functions in validate_gmoverid.py without
touching its main()/sys.exit().  test1/2/4 operate on an already-built
GmIdTable (fast); test3/5 build extra tables internally (cached when the
params were seen before).  Runs inside the SimWorker thread.
"""

import io
import re
from contextlib import redirect_stdout

_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def run_validation(model: str, L: float, vds: float | None, tbl) -> list[dict]:
    """Return [{name, ok, detail}] for the 5 checks on (model, L)."""
    import validate_gmoverid as V

    if vds is None:
        from simulate_gmoverid import MODEL_INFO
        vds = round(float(MODEL_INFO[model].get('vdd', 1.8)) / 2.0, 3)

    checks = [
        ('Weak-inversion limit', lambda: V.test1_weak_inversion(tbl)),
        ('Id/W monotonicity',    lambda: V.test2_idw_monotonicity(tbl)),
        ('L-scaling (gm*ro/fT)', lambda: V.test3_length_scaling(model, L, vds)),
        ('fT x gm/ID peak',      lambda: V.test4_ft_gmid_peak(tbl)),
        ('Vds sensitivity',      lambda: V.test5_vds_sensitivity(model, L)),
    ]

    results = []
    for name, fn in checks:
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                ok = bool(fn())
            detail = _ANSI.sub('', buf.getvalue()).strip()
        except Exception as exc:               # a check may raise on bad data
            ok, detail = False, f'{name}: error — {exc}'
        # echo to the (worker-captured) real stdout so it reaches the log panel
        print(detail or f'{name}: {"PASS" if ok else "FAIL"}')
        results.append(dict(name=name, ok=ok, detail=detail))
    return results

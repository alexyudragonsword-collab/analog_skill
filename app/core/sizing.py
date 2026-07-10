"""Sizing optimizer over the vendored AnalogGym benchmark circuits.

Each registered circuit is an AnalogGym SKY130 topology (subckt netlist +
.PARAM design-variable file + characterization testbench).  ``evaluate()``
renders the testbench with workspace paths, runs ngspice in batch mode and
extracts the metrics; ``score()`` folds them into a single cost against the
circuit's target specs (lower is better, 0 = every target met);
``optimize()`` minimizes that cost with a bounded, budget-limited Powell
search from the shipped default sizing.

Runs entirely offline — no dependency beyond scipy (already shipped).
The FoM shown in the GUI is ``-cost`` (higher is better).
"""

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app import paths
from app.core.ngspice_locator import locate

_UNIT = {'t': 1e12, 'g': 1e9, 'meg': 1e6, 'k': 1e3, 'm': 1e-3,
         'u': 1e-6, 'n': 1e-9, 'p': 1e-12, 'f': 1e-15}


def _parse_num(text: str) -> float:
    """Parse a SPICE-style number ('18p', '20u', '1.5e-06', '5')."""
    m = re.fullmatch(r'([-+0-9.eE]+)\s*(meg|[tgkmunpf])?.*', text.strip(),
                     re.IGNORECASE)
    if not m:
        raise ValueError(f'cannot parse SPICE number: {text!r}')
    val = float(m.group(1))
    if m.group(2):
        val *= _UNIT[m.group(2).lower()]
    return val


def _fmt_num(val: float) -> str:
    return f'{val:.6g}'


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class MetricSpec:
    key: str
    label: str
    unit: str
    target: float
    direction: str        # 'max' | 'min' | 'target' | 'absmin' (|m| ≤ target)
    weight: float = 1.0


@dataclass
class SizingSpec:
    title: str
    kind: str                     # 'amp' | 'ldo'
    netlist: str                  # under analoggym/<kind>/netlist/
    variables: str                # under analoggym/<kind>/variables/
    testbench: str                # under analoggym/<kind>/testbench/
    metrics: list = field(default_factory=list)
    fixed: tuple = ()             # .PARAM names kept at default (TB conditions)
    schematic: str | None = None
    eval_seconds: float = 4.0     # rough single-evaluation cost (UI estimate)


SIZING: dict[str, SizingSpec] = {
    'amp_hoilee_affc': SizingSpec(
        title='3-stage AFFC op amp — HoiLee_AFFC (SKY130, 1.8 V)',
        kind='amp',
        netlist='HoiLee_AFFC_Pin_3', variables='HoiLee_AFFC_Pin_3',
        testbench='TB_Amplifier_ACDC.cir',
        schematic='HoiLee_AFFC_Pin_3.png',
        # targets from AnalogGym's spec dicts (ckt_graphs.py / README FoM)
        metrics=[
            MetricSpec('dcgain', 'DC gain', 'dB', 100.0, 'max', 2.0),
            MetricSpec('gain_bandwidth_product', 'GBW', 'Hz', 1.2e6, 'max', 2.0),
            MetricSpec('phase_in_deg', 'Phase margin', 'deg', 60.0,
                       'target', 1.5),
            MetricSpec('dcpsrp', 'PSRR+ (dc)', 'dB', -60.0, 'min', 1.0),
            MetricSpec('dcpsrn', 'PSRR- (dc)', 'dB', -60.0, 'min', 1.0),
            MetricSpec('cmrrdc', 'CMRR (dc)', 'dB', -60.0, 'min', 1.0),
            MetricSpec('power', 'Power', 'W', 0.5e-3, 'min', 1.0),
            MetricSpec('vos25', 'Offset (25C)', 'V', 0.1e-3, 'absmin', 0.5),
            MetricSpec('tc', 'Temp. coeff.', 'V/°C', 10e-6, 'absmin', 0.5),
        ],
        fixed=('CLOAD', 'VCM'),
        eval_seconds=3.5,
    ),
    'ldo_basic': SizingSpec(
        title='Basic LDO (SKY130, 1.8 V, 5–55 mA)',
        kind='ldo',
        netlist='LDO_netlist.txt', variables='LDO_variables.txt',
        testbench='TB_LDO_ACDC.cir',
        metrics=[
            MetricSpec('pm_maxload', 'Phase margin (55 mA)', 'deg', 60.0,
                       'target', 1.5),
            MetricSpec('pm_minload', 'Phase margin (5 mA)', 'deg', 60.0,
                       'target', 1.5),
            MetricSpec('gbw_maxload', 'Loop GBW (55 mA)', 'Hz', 2e6,
                       'max', 1.5),
            MetricSpec('lnr', 'Line regulation', 'V/V', 0.01, 'absmin', 1.0),
            MetricSpec('lr', 'Load regulation', 'V/A', 0.1, 'absmin', 1.0),
            MetricSpec('psrr_maxload', 'PSRR (dc, 55 mA)', 'dB', -40.0,
                       'min', 1.0),
            MetricSpec('vos_maxload', 'Vout error (55 mA)', 'V', 2e-3,
                       'absmin', 1.0),
            MetricSpec('iq', 'Quiescent current', 'A', 1e-3, 'min', 1.0),
        ],
        fixed=('M_CL',),          # output cap is a board-level condition
        eval_seconds=8.0,
    ),
}


@dataclass
class VarSpec:
    name: str
    default: float
    lo: float
    hi: float
    is_int: bool


def _default_bounds(name: str, default: float) -> tuple[float, float, bool]:
    """Heuristic bounds per AnalogGym naming convention (see the upstream
    TB_Amplifier_ACDC objective for the ranges these are modeled on)."""
    n = name.lower()
    if '_m_' in n or n.startswith('m_'):          # device multiplier
        return max(1.0, default / 4), max(default * 4, 8.0), True
    if '_w_' in n or n.startswith('w_'):          # width (um)
        return 0.5, max(default * 4, 10.0), False
    if '_l_' in n or n.startswith('l_'):          # length (um)
        return 0.15, max(default * 3, 4.0), False
    if 'capacitor' in n or n.startswith('c_'):    # F
        return default / 4, default * 4, False
    if 'current' in n:                            # A
        return default / 4, default * 4, False
    return default / 4 if default > 0 else default * 4, \
        default * 4 if default > 0 else default / 4, False


def _variables_path(spec: SizingSpec) -> Path:
    return (paths.analoggym_dir() / spec.kind / 'variables' / spec.variables)


def parse_variables(circuit: str) -> list[VarSpec]:
    """Parse the shipped .PARAM file into editable variable specs.

    Continuation lines (`+ name=value name=value`) and `.param n=v n=v`
    forms are both handled; `fixed` names and expression-valued params
    (e.g. `W_M2=W_M1`) are excluded from the optimizable set.
    """
    spec = SIZING[circuit]
    text = _variables_path(spec).read_text()
    out = []
    fixed_lower = {f.lower() for f in spec.fixed}
    for name, value in re.findall(r'([A-Za-z_][\w]*)\s*=\s*([^\s]+)', text):
        if name.lower() in fixed_lower:
            continue
        try:
            default = _parse_num(value)
        except ValueError:
            continue                      # expression ref (W_M2=W_M1) — skip
        lo, hi, is_int = _default_bounds(name, default)
        lo = min(lo, default)
        hi = max(hi, default)
        out.append(VarSpec(name, default, lo, hi, is_int))
    return out


def schematic_path(circuit: str) -> Path | None:
    spec = SIZING[circuit]
    if not spec.schematic:
        return None
    p = paths.analoggym_dir() / spec.kind / 'schematic' / spec.schematic
    return p if p.is_file() else None


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────────────────
def _run_dir(circuit: str) -> Path:
    d = Path(os.environ.get('ANALOG_WORK_DIR',
                            Path.home() / '.analog_studio')) \
        / 'sizing' / circuit
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_params(spec: SizingSpec, values: dict, dst: Path):
    """Write the full .PARAM file: optimized values + fixed/expression
    params taken verbatim from the shipped defaults."""
    text = _variables_path(spec).read_text()
    for name, val in values.items():
        if re.search(rf'\b{re.escape(name)}\s*=', text):
            text = re.sub(rf'\b{re.escape(name)}\s*=\s*[^\s]+',
                          f'{name}={_fmt_num(val)}', text)
    dst.write_text(text)


def _render_testbench(spec: SizingSpec, run: Path) -> Path:
    """Rewrite the vendored testbench's include lines with absolute paths
    (netlist / generated params / extracted PDK) and drop interactive
    `plot` commands.  Paths are quoted (may contain spaces)."""
    src = paths.analoggym_dir() / spec.kind / 'testbench' / spec.testbench
    netlist = paths.analoggym_dir() / spec.kind / 'netlist' / spec.netlist
    pdk = paths.sky130_pdk_dir()
    out_lines = []
    for line in src.read_text().splitlines():
        ls = line.strip().lower()
        if ls.startswith('.include'):
            inc = line.split(None, 1)[1].strip().strip('"')
            if '/spice_netlist/' in inc:
                line = f'.include "{netlist}"'
            elif '/design_variables/' in inc:
                line = f'.include "{run / "params.spice"}"'
            elif 'mosfet_model/sky130_pdk/' in inc:
                rel = inc.split('mosfet_model/sky130_pdk/', 1)[1]
                line = f'.include "{pdk / rel}"'
        elif ls.startswith('plot ') or ls == 'plot':
            continue
        out_lines.append(line)
    tb = run / spec.testbench
    tb.write_text('\n'.join(out_lines) + '\n')
    return tb


def _parse_meas_log(log: Path) -> dict[str, float]:
    """Collect `name = value` measure lines from an ngspice batch log
    (last occurrence wins)."""
    out = {}
    if not log.is_file():
        return out
    for line in log.read_text(errors='replace').splitlines():
        m = re.match(r'\s*([a-zA-Z_][\w]*)\s*=\s*([-+0-9.eE]+)\s*$', line)
        if m:
            try:
                out[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                pass
    return out


def _read_wrdata(path: Path, n_values: int) -> list[float] | None:
    """AnalogGym wrdata files interleave (x, value) column pairs with the
    value constant down the rows — read the first row, odd columns."""
    try:
        row = np.loadtxt(path, ndmin=2)[0]
    except Exception:
        return None
    vals = row[1::2]
    if len(vals) < n_values:
        return None
    return [float(v) for v in vals[:n_values]]


def _ngspice_cmd() -> str:
    st = locate()
    if not st.ok:
        raise RuntimeError('ngspice not found')
    return st.exe


def evaluate(circuit: str, values: dict) -> dict:
    """One full testbench evaluation → metric dict (missing metrics absent)."""
    spec = SIZING[circuit]
    paths.ensure_sky130()
    run = _run_dir(circuit)
    _write_params(spec, values, run / 'params.spice')
    tb = _render_testbench(spec, run)
    log = run / 'log.txt'
    if log.exists():
        log.unlink()
    subprocess.run([_ngspice_cmd(), '-o', str(log), '-b', str(tb)],
                   cwd=run, capture_output=True, timeout=300)
    metrics = _parse_meas_log(log)
    if spec.kind == 'ldo':
        metrics = _ldo_metrics(run, metrics)
    return metrics


def _ldo_metrics(run: Path, meas: dict) -> dict:
    """Fold the LDO testbench's wrdata outputs into named metrics."""
    out = {}
    v = _read_wrdata(run / 'LDO_TB_ACDC_LR_Power_vos', 5)
    if v:
        lr, p_max, p_min, vos_max, vos_min = v
        out.update(lr=lr, power_maxload=p_max, power_minload=p_min,
                   vos_maxload=vos_max, vos_minload=vos_min,
                   # quiescent current = supply current at min load − 5 mA
                   iq=max(p_min / 1.8 - 5e-3, 0.0))
    v = _read_wrdata(run / 'LDO_TB_ACDC_LNR_maxload', 1)
    if v:
        out['lnr'] = v[0]
    v = _read_wrdata(run / 'LDO_TB_ACDC_LNR_minload', 1)
    if v:
        out['lnr_minload'] = v[0]
    for load in ('maxload', 'minload'):
        v = _read_wrdata(run / f'LDO_TB_ACDC_GBW_PM_{load}', 2)
        if v:
            out[f'gbw_{load}'], out[f'pm_{load}'] = v
        v = _read_wrdata(run / f'LDO_TB_ACDC_PSRR_dcgain_{load}', 2)
        if v:
            out[f'psrr_{load}'], out[f'dcgain_{load}'] = v
    out.update(meas)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────
_MISSING_PENALTY = 10.0


def score(circuit: str, metrics: dict) -> float:
    """Weighted violation cost against the target specs (0 = all met).

    max:    penalize (target − m)/|target| when below target
    min:    penalize (m − target)/|target| when above target
    absmin: like min on |m|
    target: |m − target|/|target|  (e.g. phase margin 60°)
    """
    cost = 0.0
    for ms in SIZING[circuit].metrics:
        m = metrics.get(ms.key)
        if m is None or not np.isfinite(m):
            cost += ms.weight * _MISSING_PENALTY
            continue
        t = ms.target
        if ms.direction == 'max':
            r = max(0.0, (t - m) / abs(t))
        elif ms.direction == 'min':
            r = max(0.0, (m - t) / abs(t))
        elif ms.direction == 'absmin':
            r = max(0.0, (abs(m) - t) / abs(t))
        else:                                    # 'target'
            r = abs(m - t) / abs(t)
        cost += ms.weight * min(r, _MISSING_PENALTY)
    return cost


# ─────────────────────────────────────────────────────────────────────────────
# Optimization
# ─────────────────────────────────────────────────────────────────────────────
class _Cancelled(Exception):
    pass


@dataclass
class SizingRun:
    circuit: str
    best_values: dict
    best_metrics: dict
    best_cost: float
    initial_cost: float
    history: list                 # [(eval_no, best_cost_so_far)]
    evals: int
    cancelled: bool
    elapsed: float

    def report(self) -> str:
        spec = SIZING[self.circuit]
        lines = [spec.title, '',
                 f'evaluations: {self.evals}'
                 + ('  (cancelled)' if self.cancelled else '')
                 + f'   elapsed: {self.elapsed:.0f}s',
                 f'cost: {self.initial_cost:.4f}  ->  {self.best_cost:.4f}'
                 f'   (FoM {-self.best_cost:.4f})', '',
                 f'{"metric":<22}{"value":>14}   target']
        for ms in spec.metrics:
            m = self.best_metrics.get(ms.key)
            val = f'{m:.4g}' if m is not None else 'n/a'
            lines.append(f'{ms.label:<22}{val:>14} {ms.unit:<5}'
                         f' {ms.direction} {ms.target:g}')
        lines += ['', 'best design variables:']
        for k, v in self.best_values.items():
            lines.append(f'  {k} = {_fmt_num(v)}')
        return '\n'.join(lines)

    def params_text(self) -> str:
        """Best sizing as a .PARAM file (same shape as the shipped one)."""
        spec = SIZING[self.circuit]
        buf = Path(_run_dir(self.circuit) / 'best_params.spice')
        _write_params(spec, self.best_values, buf)
        return buf.read_text()


def optimize(circuit: str, variables: list[VarSpec], budget: int = 60,
             progress=None, should_cancel=None) -> SizingRun:
    """Global + local search within bounds, ≤ budget evaluations.

    Phase 1 evaluates the default sizing plus a scrambled-Sobol sample of
    the box (~half the budget — Powell alone explores one coordinate at a
    time and is nearly blind on 20–30-dim spaces at these budgets);
    phase 2 refines the best point with bounded Powell.

    progress(eval_no, best_cost, metrics) fires after every evaluation;
    should_cancel() → True stops between evaluations (best-so-far kept).
    """
    from scipy.optimize import minimize
    from scipy.stats import qmc

    spec = SIZING[circuit]
    names = [v.name for v in variables]
    lo = np.array([v.lo for v in variables], float)
    hi = np.array([v.hi for v in variables], float)
    span = np.where(hi > lo, hi - lo, 1.0)
    is_int = np.array([v.is_int for v in variables])
    x0 = (np.array([v.default for v in variables], float) - lo) / span

    state = {'n': 0, 'best': None, 'best_x': None, 'best_m': {},
             'history': [], 'cancel': False}
    t0 = time.time()

    def to_values(xn):
        x = np.clip(xn, 0, 1) * span + lo
        x = np.where(is_int, np.round(x), x)
        return dict(zip(names, x.tolist()))

    def objective(xn):
        if should_cancel is not None and should_cancel():
            state['cancel'] = True
            raise _Cancelled
        if state['n'] >= budget:
            raise _Cancelled
        vals = to_values(xn)
        metrics = evaluate(circuit, vals)
        c = score(circuit, metrics)
        state['n'] += 1
        if state['best'] is None or c < state['best']:
            state['best'], state['best_x'] = c, vals
            state['best_m'] = metrics
        state['history'].append((state['n'], state['best']))
        if progress is not None:
            progress(state['n'], state['best'], metrics)
        return c

    state['best_xn'] = x0

    def objective_track(xn):
        c = objective(xn)
        if c <= state['best']:
            state['best_xn'] = np.asarray(xn, float)
        return c

    n_sobol = min(max(budget // 2, 0), max(budget - 5, 0))
    try:
        objective_track(x0)                  # evaluation #1: default sizing
        if n_sobol > 1:
            # Sobol sample around the (literature-derived) default sizing:
            # ±25% of each bound span, clipped to the box
            import warnings
            sob = qmc.Sobol(len(names), scramble=True, seed=0)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                pts = sob.random(n_sobol - 1)
            for p in pts:
                objective_track(np.clip(x0 + (p - 0.5) * 0.5, 0.0, 1.0))
        minimize(objective_track, state['best_xn'], method='Powell',
                 bounds=[(0.0, 1.0)] * len(names),
                 options={'maxfev': max(budget - state['n'], 1),
                          'xtol': 1e-3, 'ftol': 1e-4})
    except _Cancelled:
        pass
    initial_cost = state['history'][0][1] if state['history'] else float('inf')
    return SizingRun(circuit=circuit,
                     best_values=state['best_x'] or to_values(x0),
                     best_metrics=state['best_m'],
                     best_cost=state['best'] if state['best'] is not None
                     else float('inf'),
                     initial_cost=initial_cost, history=state['history'],
                     evals=state['n'], cancelled=state['cancel'],
                     elapsed=time.time() - t0)


def render_convergence(run: SizingRun) -> Path:
    """Draw the convergence curve (GUI thread — matplotlib policy)."""
    import matplotlib
    matplotlib.use('Agg', force=False)
    import matplotlib.pyplot as plt
    xs = [h[0] for h in run.history]
    ys = [-h[1] for h in run.history]
    fig, ax = plt.subplots(figsize=(6.4, 4.2), constrained_layout=True)
    ax.plot(xs, ys, '-o', ms=3, color='#2874a6')
    ax.set_xlabel('evaluation')
    ax.set_ylabel('best FoM (= -cost, higher is better)')
    title = SIZING[run.circuit].title
    ax.set_title(f'Sizing convergence — {title}', fontsize=10)
    ax.grid(alpha=0.3)
    out = _run_dir(run.circuit) / 'convergence.png'
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out

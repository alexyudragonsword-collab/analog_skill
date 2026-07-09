"""Adapters for the vendored analog-circuit-skills collection (circuit-skills/).

Five block-level circuit skills (StrongArm comparator, LDO, bootstrapped
switch, 5T OTA, two-stage op amp) share one architecture: parameter globals
in ``*_common.py``, no-argument ``simulate_*()`` functions returning result
dicts, and ``plot_*(result)`` renderers writing PNGs under the skill's
PLOT_DIR.  All their outputs are routed through the ``ANALOG_WORK_DIR``
environment variable, which paths.init_runtime() points at the app workspace
— the skill trees themselves stay read-only.

Import isolation: every skill ships its own ``ngspice_common.py`` (and the
gmoverid/examples workspace has yet another), so circuit modules are imported
inside :func:`skill_context`, which puts the skill's scripts dir first on
sys.path and gives the managed module names a clean slot, restoring the
previous state afterwards.  The serial SimWorker guarantees no two jobs
overlap; render closures only call already-bound functions, never import.

Thread policy (same as examples/browser_service): ``run_circuit`` executes
ngspice sweeps on the worker thread and returns a CircuitResult whose
``render()`` closure does ALL matplotlib work — the tab calls it on the GUI
thread and receives (png_paths, report_text).
"""

import io
import os
import sys
import time
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app import paths


# ─────────────────────────────────────────────────────────────────────────────
# Import isolation
# ─────────────────────────────────────────────────────────────────────────────
def _managed_module_names() -> set[str]:
    """Module names that may collide across skills (each skill's .py stems
    plus the shared ngspice_common)."""
    names = {'ngspice_common'}
    root = paths.circuit_skills_dir()
    if root.is_dir():
        for sub in ('comparator/scripts', 'LDO/scripts',
                    'five_transistor_ota/scripts', 'two_stage_opamp/scripts',
                    'bootstrap_switch/assets'):
            d = root / sub
            if d.is_dir():
                names.update(p.stem for p in d.glob('*.py'))
    return names


@contextmanager
def skill_context(scripts_dir: Path):
    """Import a circuit skill in isolation and restore sys state afterwards.

    Modules imported inside stay alive through the references the caller
    keeps (render closures), but are removed from sys.modules so the next
    skill – or the gmoverid/examples code – re-imports its own versions.
    """
    managed = _managed_module_names()
    snapshot = {n: sys.modules.pop(n) for n in managed if n in sys.modules}
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        for n in managed:
            sys.modules.pop(n, None)
        sys.modules.update(snapshot)
        # some skill entry modules sys.path.insert their own dir at import
        # time — drop EVERY circuit-skills entry, not just the one we added,
        # so no skill dir stays importable outside a context
        root = str(paths.circuit_skills_dir())
        sys.path[:] = [p for p in sys.path
                       if not str(p).startswith(root)]


# ─────────────────────────────────────────────────────────────────────────────
# Registry model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Param:
    attr: str                    # global in the common module; 'W.key' → dict entry
    label: str
    default: float
    unit: str = ''
    advanced: bool = False
    decimals: int = 3
    minv: float = 0.0
    maxv: float = 1e12
    kind: str = 'float'          # 'float' | 'int'


@dataclass
class Analysis:
    label: str
    params: list | None = None   # None → use the circuit's param list
    note: str = ''               # shown in the status line before running


@dataclass
class CircuitSpec:
    title: str
    subdir: str                  # scripts dir, relative to circuit_skills_dir()
    common_mod: str
    params: list = field(default_factory=list)
    analyses: dict = field(default_factory=dict)


@dataclass
class CircuitResult:
    render: Callable[[], tuple[list[Path], str]]


def _apply_params(common, values: dict):
    for attr, val in values.items():
        if '.' in attr:                       # dict entry, e.g. 'W.tail'
            dname, key = attr.split('.', 1)
            getattr(common, dname)[key] = val
        else:
            setattr(common, attr, val)


def _snapshot_pngs(plot_dir: Path) -> dict:
    if not plot_dir.is_dir():
        return {}
    return {p: p.stat().st_mtime for p in plot_dir.glob('*.png')}


def _new_pngs(plot_dir: Path, before: dict) -> list[Path]:
    if not plot_dir.is_dir():
        return []
    out = [p for p in sorted(plot_dir.glob('*.png'))
           if p not in before or p.stat().st_mtime > before[p]]
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Circuit registry (defaults mirror the *_common.py globals — see SKILL.md)
# ─────────────────────────────────────────────────────────────────────────────
CIRCUITS: dict[str, CircuitSpec] = {
    'comparator': CircuitSpec(
        title='StrongArm comparator (45nm, 1.0 V)',
        subdir='comparator/scripts', common_mod='comparator_common',
        params=[
            Param('W.inp',   'W input pair',  4.0, 'um'),
            Param('W.tail',  'W tail',        4.0, 'um'),
            Param('W.lat_n', 'W latch NMOS',  1.0, 'um', advanced=True),
            Param('W.lat_p', 'W latch PMOS',  2.0, 'um', advanced=True),
            Param('W.rst',   'W reset PMOS',  1.0, 'um', advanced=True),
            Param('NOISE_VIN_MV', 'Noise Vin', 0.35, 'mV', advanced=True),
        ],
        analyses={
            'full':  Analysis('Full characterization (wave + noise + ramp)',
                              note='noise runs 3x1000 clock cycles — expect ~2 min'),
            'wave':  Analysis('Transient waveform (internal nodes)'),
            'noise': Analysis('Input-referred noise (probit, 1000 cycles)',
                              note='three 1000-cycle transient-noise runs — ~2 min'),
            'ramp':  Analysis('Ramp transfer curve'),
            'sweep_amp': Analysis('Sweep: input amplitude vs P(1)',
                                  note='many transient-noise points — several minutes'),
            'sweep_vcm': Analysis('Sweep: common-mode voltage',
                                  note='several transient-noise points — minutes'),
            'sweep_k':   Analysis('Sweep: valid-K window',
                                  note='several transient-noise points — minutes'),
            'sweep_bw':  Analysis('Sweep: noise bandwidth',
                                  note='several transient-noise points — minutes'),
            'selfcheck': Analysis('Self-check (5 physics assertions)',
                                  note='runs wave + noise + ramp, then checks '
                                       'quantitative bounds — ~2 min'),
        }),
    'ldo': CircuitSpec(
        title='LDO regulator (180nm, 1.8 V out)',
        subdir='LDO/scripts', common_mod='ldo_common',
        params=[
            Param('R_LOAD_DEFAULT', 'R load', 18.0, 'ohm', minv=0.1),
            Param('C_OUT',  'C out',  1e-6,   'F', decimals=9, advanced=True),
            Param('R_COMP', 'R comp', 2000.0, 'ohm', advanced=True),
            Param('C_COMP', 'C comp', 160e-12, 'F', decimals=15, advanced=True),
            Param('IBIAS_UA', 'I bias', 100.0, 'uA', advanced=True),
        ],
        analyses={
            'full':  Analysis('Full characterization (DC + AC + noise + tran)',
                              note='four simulations run in parallel'),
            'dc':    Analysis('DC regulation'),
            'ac':    Analysis('AC loop gain / PSRR / Zout'),
            'noise': Analysis('Output noise'),
            'tran':  Analysis('Load/line transient'),
            'sweep_ccomp': Analysis('Sweep: C_COMP (PM / GBW)',
                                    note='7 AC runs'),
            'sweep_rcomp': Analysis('Sweep: R_COMP (PM / GBW)',
                                    note='several AC runs'),
            'sweep_cout':  Analysis('Sweep: C_OUT (PM / GBW)',
                                    note='several AC runs'),
            'theory': Analysis('Theory vs simulation (poles/zero/PSRR/Zout)'),
            'auto':  Analysis('Auto-design from specs', params=[
                Param('vout',     'VOUT target', 1.8,   'V',  minv=0.5, maxv=3.0),
                Param('vin',      'VIN',         2.3,   'V',  minv=0.8, maxv=5.0),
                Param('iload_ma', 'ILOAD max',   100.0, 'mA', minv=0.1),
                Param('vref',     'VREF',        0.9,   'V',  advanced=True),
                Param('gbw_khz',  'GBW target',  1284.0, 'kHz', advanced=True),
                Param('fz_frac',  'fz / GBW',    0.4,   '',   advanced=True),
            ], note='computes sizing, applies it, then verifies with an AC run'),
        }),
    'ota5t': CircuitSpec(
        title='Five-transistor OTA (180nm)',
        subdir='five_transistor_ota/scripts', common_mod='ota_common',
        params=[
            Param('W_IN_UM',   'W input pair', 20.0, 'um'),
            Param('W_LOAD_UM', 'W load',       16.0, 'um'),
            Param('W_TAIL_UM', 'W tail',       12.0, 'um'),
            Param('C_LOAD',    'C load',       1e-12, 'F', decimals=15),
            Param('VBIAS',     'V bias',       0.72, 'V', advanced=True),
            Param('VCM',       'V cm',         0.9,  'V', advanced=True),
        ],
        analyses={
            'full':  Analysis('Full characterization (DC + AC + noise)'),
            'dc':    Analysis('DC transfer'),
            'ac':    Analysis('AC open-loop response'),
            'noise': Analysis('Output noise'),
        }),
    'opamp2': CircuitSpec(
        title='Two-stage Miller op amp (180nm)',
        subdir='two_stage_opamp/scripts', common_mod='opamp_common',
        params=[
            Param('CC', 'C compensation', 12e-12, 'F', decimals=15),
            Param('CL', 'C load',          1.2e-12, 'F', decimals=15),
            Param('IBIAS', 'I bias',       120e-6, 'A', decimals=9, advanced=True),
            Param('W_M0_M1_UM', 'W input pair', 160.0, 'um', advanced=True),
            Param('W_M2_UM',    'W 2nd stage',  720.0, 'um', advanced=True),
        ],
        analyses={
            'full':  Analysis('Full characterization (DC + AC + PZ + noise)'),
            'dc':    Analysis('DC operating point'),
            'ac':    Analysis('AC gain / phase'),
            'pz':    Analysis('Pole-zero analysis'),
            'noise': Analysis('Noise (open/closed loop)'),
        }),
    'bootstrap': CircuitSpec(
        title='Bootstrapped switch (180nm)',
        subdir='bootstrap_switch/assets', common_mod='bootstrap_common',
        params=[
            Param('FCLK', 'F clock', 50e6, 'Hz', decimals=0, advanced=True),
        ],
        analyses={
            'full': Analysis('Full characterization (waveform + Ron)'),
            'wave': Analysis('Bootstrap waveform'),
            'ron':  Analysis('On-resistance comparison'),
        }),
}


# ─────────────────────────────────────────────────────────────────────────────
# Per-circuit runners — execute on the WORKER thread; the returned closure
# does all plotting and must run on the GUI thread.
# ─────────────────────────────────────────────────────────────────────────────
def run_circuit(circuit: str, analysis: str, values: dict) -> CircuitResult:
    spec = CIRCUITS[circuit]
    scripts = paths.circuit_skills_dir() / spec.subdir
    if not scripts.is_dir():
        raise RuntimeError(f'circuit-skills not found at {scripts}')
    runner = _RUNNERS[circuit]
    with skill_context(scripts):
        return runner(analysis, values)


def _fmt(v, nd=2):
    try:
        return f'{float(v):.{nd}f}'
    except (TypeError, ValueError):
        return 'nan'


def _run_ota(analysis, values):
    import ota_common as common
    _apply_params(common, values)
    from ngspice_common import PLOT_DIR
    import simulate_ota_dc, simulate_ota_ac, simulate_ota_noise
    import plot_ota

    res = {}
    if analysis in ('full', 'dc'):
        res['dc'] = simulate_ota_dc.simulate_dc()
    if analysis in ('full', 'ac'):
        res['ac'] = simulate_ota_ac.simulate_ac()
    if analysis in ('full', 'noise'):
        res['noise'] = simulate_ota_noise.simulate_noise()

    m_ac = res.get('ac', {}).get('metrics', {})
    m_n = res.get('noise', {}).get('metrics', {})
    dc = res.get('dc', {}).get('dc', {})
    lines = ['Five-Transistor OTA Summary', '=' * 28]
    if 'ac' in res:
        lines += [f"DC gain       : {_fmt(m_ac.get('dc_gain_db'))} dB",
                  f"UGB           : {_fmt(m_ac.get('ugb_hz', float('nan')) / 1e6, 3)} MHz",
                  f"Phase @ UGB   : {_fmt(m_ac.get('phase_ugb_deg'))} deg"]
    if 'noise' in res:
        lines += [f"Vn @ 1 kHz    : {_fmt(m_n.get('vn_1k_nvrtHz'))} nV/rtHz",
                  f"Vn rms        : {_fmt(m_n.get('vn_rms_uv'))} uV_rms"]
    if 'dc' in res:
        lines += [f"DC local gain : {_fmt(dc.get('gain_mid'))} V/V",
                  f"Vout bias     : {_fmt(dc.get('vout_mid'), 4)} V"]
    report = '\n'.join(lines)

    def render():
        before = _snapshot_pngs(PLOT_DIR)
        if 'dc' in res:
            plot_ota.plot_dc(res['dc'])
        if 'ac' in res:
            plot_ota.plot_ac(res['ac'])
        if 'noise' in res:
            plot_ota.plot_noise(res['noise'])
        return _new_pngs(PLOT_DIR, before), report
    return CircuitResult(render)


def _run_opamp(analysis, values):
    import opamp_common as common
    _apply_params(common, values)
    from ngspice_common import PLOT_DIR
    import simulate_opamp_dc, simulate_opamp_ac, simulate_opamp_pz, \
        simulate_opamp_noise
    import plot_opamp

    res = {}
    if analysis in ('full', 'dc'):
        res['dc'] = simulate_opamp_dc.simulate_dc()
    if analysis in ('full', 'ac'):
        res['ac'] = simulate_opamp_ac.simulate_ac()
    if analysis in ('full', 'pz'):
        res['pz'] = simulate_opamp_pz.simulate_pz()
    if analysis in ('full', 'noise'):
        res['noise'] = simulate_opamp_noise.simulate_noise()

    nodes = res.get('dc', {}).get('dc', {}).get('nodes', {})
    m_ac = res.get('ac', {}).get('metrics', {})
    m_n = res.get('noise', {}).get('metrics', {})
    m_pz = res.get('pz', {}).get('pz', {})
    lines = ['Two-Stage Op Amp Summary', '=' * 26]
    if 'dc' in res:
        d = res['dc'].get('dc', {})
        lines += [f"Vout bias     : {_fmt(nodes.get('out'), 4)} V",
                  f"IDD           : {_fmt(d.get('idd_a', float('nan')) * 1e6)} uA",
                  f"Power         : {_fmt(d.get('power_w', float('nan')) * 1e6)} uW"]
    if 'ac' in res:
        lines += [f"DC gain       : {_fmt(m_ac.get('dc_gain_db'))} dB",
                  f"UGB           : {_fmt(m_ac.get('ugb_hz', float('nan')) / 1e6, 3)} MHz",
                  f"Est. PM       : {_fmt(m_ac.get('phase_margin_deg'))} deg"]
    if 'pz' in res:
        ugb = m_ac.get('ugb_hz', float('nan'))
        nd = m_pz.get('nondominant_pole_hz', float('nan'))
        rz = m_pz.get('first_rhp_zero_hz', float('nan'))
        lines += [f"Dominant pole : {_fmt(m_pz.get('dominant_pole_hz', float('nan')) / 1e3, 3)} kHz",
                  f"Non-dom pole  : {_fmt(nd / 1e6, 3)} MHz ({_fmt(nd / ugb)} x UGB)",
                  f"First RHP zero: {_fmt(rz / 1e6, 3)} MHz ({_fmt(rz / ugb)} x UGB)"]
    if 'noise' in res:
        lines += [f"OL Vn @1kHz   : {_fmt(m_n.get('vn_1k_nvrtHz'))} nV/rtHz",
                  f"Input en @1kHz: {_fmt(m_n.get('en_1k_nvrtHz'))} nV/rtHz",
                  f"CL Vn rms     : {_fmt(m_n.get('cl_vn_rms_uv'))} uV_rms"]
    if 'pz' in res:
        lines += ['', 'Pole-zero table (ngspice PZ analysis)',
                  f'{"#":>3s} {"type":<5s} {"re [Hz]":>13s} {"im [Hz]":>13s} '
                  f'{"|f| ":>12s}']
        for kind, pts in (('pole', m_pz.get('poles', [])),
                          ('zero', m_pz.get('zeros', []))):
            for p in pts:
                lines.append(
                    f'{p["idx"]:>3d} {kind:<5s} {p["real"]:>13.4g} '
                    f'{p["imag"]:>13.4g} {p["hz"]:>10.4g} Hz')
    report = '\n'.join(lines)

    def render():
        before = _snapshot_pngs(PLOT_DIR)
        if 'dc' in res:
            plot_opamp.plot_dc_nodes(res['dc'])
        if 'ac' in res:
            plot_opamp.plot_ac(res['ac'])
        if 'noise' in res:
            plot_opamp.plot_noise(res['noise'])
        return _new_pngs(PLOT_DIR, before), report
    return CircuitResult(render)


def _run_ldo(analysis, values):
    import ldo_common as common
    from ngspice_common import PLOT_DIR

    if analysis == 'auto':
        return _run_ldo_auto(values, PLOT_DIR)
    if analysis.startswith('sweep_'):
        _apply_params(common, values)
        return _run_ldo_sweep(analysis, PLOT_DIR)
    if analysis == 'theory':
        _apply_params(common, values)
        return _run_ldo_theory(PLOT_DIR)

    _apply_params(common, values)
    from simulate_ldo_dc import simulate_dc
    from simulate_ldo_ac import simulate_ac
    from simulate_ldo_noise import simulate_noise
    from simulate_ldo_tran import simulate_tran
    import plot_ldo_dc, plot_ldo_ac, plot_ldo_noise, plot_ldo_tran
    import run_ldo

    res = {}
    if analysis == 'full':
        # mirror the master: four independent ngspice runs in parallel
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = {k: pool.submit(fn) for k, fn in
                    (('dc', simulate_dc), ('ac', simulate_ac),
                     ('noise', simulate_noise), ('tran', simulate_tran))}
            res = {k: f.result() for k, f in futs.items()}
    else:
        fn = {'dc': simulate_dc, 'ac': simulate_ac,
              'noise': simulate_noise, 'tran': simulate_tran}[analysis]
        res[analysis] = fn()

    if analysis == 'full':
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_ldo._print_report(res['dc'], res['ac'], res['noise'],
                                  res['tran'])
        report = buf.getvalue().strip()
    else:
        report = f'LDO {analysis.upper()} finished — see plot and log panel.'

    plotters = {'dc': plot_ldo_dc.plot_dc, 'ac': plot_ldo_ac.plot_ac,
                'noise': plot_ldo_noise.plot_noise,
                'tran': plot_ldo_tran.plot_tran}

    def render():
        before = _snapshot_pngs(PLOT_DIR)
        for key, r in res.items():
            plotters[key](r)
        return _new_pngs(PLOT_DIR, before), report
    return CircuitResult(render)


def _run_ldo_auto(values, plot_dir):
    import run_auto_design as ad
    from simulate_ldo_ac import simulate_ac
    import plot_ldo_ac

    params = ad.design(values['vout'], values['vin'], values['iload_ma'],
                       values.get('vref', 0.9), values.get('gbw_khz', 1284.0),
                       values.get('fz_frac', 0.4))
    ad.apply_design(params)
    res = simulate_ac()
    m = res.get('metrics', {})
    sim_metrics = {'gbw_hz': m.get('gbw_hz', float('nan')),
                   'pm_deg': m.get('phase_margin_deg', float('nan')),
                   'dc_gain_db': m.get('dc_gain_db', float('nan')),
                   'psrr_dc_db': m.get('psrr_dc_db', float('nan'))}
    report = ad._build_report(params, sim_metrics)

    def render():
        before = _snapshot_pngs(plot_dir)
        plot_ldo_ac.plot_ac(res)
        return _new_pngs(plot_dir, before), report
    return CircuitResult(render)


def _run_comparator(analysis, values):
    import comparator_common as common
    _apply_params(common, values)
    from ngspice_common import PLOT_DIR

    if analysis.startswith('sweep_'):
        return _run_comparator_sweep(analysis, PLOT_DIR)

    import simulate_tran_strongarm_wave as sim_wave
    import simulate_tran_strongarm_noise as sim_noise
    import simulate_tran_strongarm_ramp as sim_ramp
    import plot_tran_strongarm_wave as p_wave
    import plot_tran_strongarm_noise as p_noise
    import plot_tran_strongarm_ramp as p_ramp

    res = {}
    if analysis in ('full', 'selfcheck'):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as pool:
            futs = {'wave': pool.submit(sim_wave.simulate_wave),
                    'noise': pool.submit(sim_noise.simulate_noise),
                    'ramp': pool.submit(sim_ramp.simulate_ramp)}
            res = {k: f.result() for k, f in futs.items()}
    elif analysis == 'wave':
        res['wave'] = sim_wave.simulate_wave()
    elif analysis == 'noise':
        res['noise'] = sim_noise.simulate_noise()
    elif analysis == 'ramp':
        res['ramp'] = sim_ramp.simulate_ramp()

    fom = None
    lines = ['StrongArm Comparator Summary', '=' * 29]
    if 'noise' in res:
        fom = sim_noise.compute_fom(res['noise'])
        npt = res['noise']['noise_pt']
        e_cycle_fj = fom['p_avg_uw'] / (res['noise']['params']['FCLK'] / 1e9)
        lines += [f"sigma_n       : {_fmt(npt.get('sigma_uv'), 1)} uV (input-referred RMS)",
                  f"P(1) @ {_fmt(npt.get('vin_mv'), 2)} mV : {_fmt(npt.get('p1', 0) * 100, 1)} %",
                  f"Avg power     : {_fmt(fom.get('p_avg_uw'))} uW",
                  f"Energy/cycle  : {_fmt(e_cycle_fj)} fJ",
                  f"Tcmp          : {_fmt(fom.get('tcmp_ps'), 1)} ps",
                  f"FOM1 (E*s^2)  : {fom.get('fom1', float('nan')):.3e}",
                  f"FOM2 (FOM1*T) : {fom.get('fom2', float('nan')):.3e}"]
    if 'wave' in res:
        lines.append('Waveform      : internal nodes VXP/VXN, VLP/VLN, OUTP/OUTN')
    if 'ramp' in res:
        lines.append('Ramp          : transfer curve over slow differential ramp')
    if analysis == 'selfcheck':
        lines += ['', *_comparator_selfcheck(res, fom, common)]
    report = '\n'.join(lines)

    def render():
        before = _snapshot_pngs(PLOT_DIR)
        if 'wave' in res:
            p_wave.plot_wave(res['wave']['wave'], res['wave']['params'])
        if 'noise' in res:
            p_noise.plot_noise(res['noise']['noise_pt'],
                               res['noise']['params'], fom=fom)
        if 'ramp' in res:
            p_ramp.plot_ramp(res['ramp']['ramp'], res['ramp']['params'])
        return _new_pngs(PLOT_DIR, before), report
    return CircuitResult(render)


def _comparator_selfcheck(res, fom, common) -> list[str]:
    """Quantitative physics checks (bounds derived from the skill's
    evals.json assertions, widened for cross-ngspice-version headroom)."""
    import numpy as np
    checks = []

    def add(name, ok, detail):
        checks.append(f'  [{"PASS" if ok else "FAIL"}] {name:<22s} {detail}')

    npt = res['noise']['noise_pt']
    sigma = npt.get('sigma_uv', float('nan'))
    add('sigma_n band', 100.0 <= sigma <= 800.0,
        f'{_fmt(sigma, 1)} uV in [100, 800] (evals nominal 200-600)')
    p1 = npt.get('p1', float('nan'))
    add('probit operating pt', 0.55 < p1 < 0.999,
        f'P(1)={_fmt(p1 * 100, 1)}% at +{_fmt(npt.get("vin_mv", 0), 2)} mV')
    tau = res['wave'].get('wave', {}).get('tau_ps', float('nan'))
    add('latch tau sane', 1.0 < tau < 100.0, f'tau={_fmt(tau, 1)} ps')
    add('speed/power sane',
        1.0 < fom.get('tcmp_ps', 0) < 1000.0
        and 1.0 < fom.get('p_avg_uw', 0) < 10000.0,
        f"Tcmp={_fmt(fom.get('tcmp_ps'), 1)} ps, "
        f"P={_fmt(fom.get('p_avg_uw'))} uW")

    # ramp transition width: per-cycle decisions vs ramped input
    ramp = res['ramp']['ramp']
    width_ok, detail = False, 'no ramp data'
    t, vout, vin = ramp.get('time'), ramp.get('vout_diff'), ramp.get('vin_diff')
    if t is not None and vout is not None and vin is not None:
        tclk = common.TCLK
        ncyc = int(t[-1] / tclk)
        dec_v, dec_in = [], []
        for k in range(ncyc):
            m = (t >= k * tclk) & (t < (k + 1) * tclk)
            if not np.any(m):
                continue
            i = np.argmax(np.abs(vout[m]))
            dec_v.append(vout[m][i])
            dec_in.append(vin[m][i])
        dec_v, dec_in = np.array(dec_v), np.array(dec_in)
        strong = np.abs(dec_v) > 0.3 * np.nanmax(np.abs(dec_v))
        lows = dec_in[strong & (dec_v < 0)]
        highs = dec_in[strong & (dec_v > 0)]
        if len(lows) and len(highs):
            width = float(np.max(lows) - np.min(highs))
            width_ok = 0.0 <= width <= 3.0
            detail = f'noisy region ~{_fmt(width, 2)} mV wide (evals 0.5-2)'
    add('ramp transition', width_ok, detail)

    n_pass = sum('[PASS]' in c for c in checks)
    return [f'Self-check: {n_pass}/{len(checks)} passed', *checks]


def _run_comparator_sweep(analysis, plot_dir):
    """Comparator parameter sweeps (clean simulate/plot module pairs)."""
    t0 = time.time()
    if analysis == 'sweep_amp':
        from simulate_sweep_input_amplitude import sweep_input_amplitude
        from plot_sweep_input_amplitude import plot_input_amplitude
        results = sweep_input_amplitude()
        plot = lambda: plot_input_amplitude(results)
        title = 'Input-amplitude sweep'
    elif analysis == 'sweep_vcm':
        from simulate_sweep_vcm import sweep_vcm
        from plot_sweep_vcm import plot_vcm
        results = sweep_vcm()
        wall = time.time() - t0
        plot = lambda: plot_vcm(results, wall_s=wall)
        title = 'Common-mode sweep'
    elif analysis == 'sweep_k':
        from simulate_sweep_k_valid import sweep_k
        from plot_sweep_k_valid import plot_k_valid
        results = sweep_k()
        wall = time.time() - t0
        plot = lambda: plot_k_valid(results, wall_s=wall)
        title = 'Valid-K sweep'
    else:                                    # sweep_bw
        from simulate_sweep_noise_bw import sweep_noise_bw
        from plot_sweep_noise_bw import plot_noise_bw
        results = sweep_noise_bw()
        wall = time.time() - t0
        plot = lambda: plot_noise_bw(results, wall_s=wall)
        title = 'Noise-bandwidth sweep'

    report = (f'StrongArm Comparator — {title}\n'
              f'{"=" * (24 + len(title))}\n'
              f'{len(results)} points, {time.time() - t0:.1f}s wall.\n'
              'Numbers per point are in the log panel; see the plot.')

    def render():
        before = _snapshot_pngs(plot_dir)
        plot()
        return _new_pngs(plot_dir, before), report
    return CircuitResult(render)


def _run_ldo_sweep(analysis, plot_dir):
    """LDO compensation sweeps — replicate the tiny loop from the vendored
    run_*_sweep.main() (patch value → AC run → collect), then reuse the
    module's own _plot for the figure."""
    import math
    import ldo_common as ldo
    from simulate_ldo_ac import simulate_ac

    cfg = {
        'sweep_ccomp': ('run_ccomp_sweep', 'CCOMP_VALS', 'C_COMP',
                        lambda v: 1 / (2 * math.pi * ldo.R_COMP * v) / 1e3,
                        lambda v: f'{v * 1e12:.0f} pF'),
        'sweep_rcomp': ('run_rcomp_sweep', 'RCOMP_VALS', 'R_COMP',
                        lambda v: 1 / (2 * math.pi * v * ldo.C_COMP) / 1e3,
                        lambda v: f'{v:.0f} ohm'),
        'sweep_cout':  ('run_cout_sweep', 'COUT_VALS', 'C_OUT',
                        lambda v: 1 / (2 * math.pi * ldo.R_LOAD_DEFAULT * v) / 1e3,
                        lambda v: f'{v * 1e6:.3f} uF'),
    }[analysis]
    mod_name, vals_attr, attr, f_of, fmt = cfg
    import importlib
    mod = importlib.import_module(mod_name)
    vals = getattr(mod, vals_attr)

    orig = getattr(ldo, attr)
    results = []
    lines = [f'LDO {attr} sweep', '=' * 20,
             f'{attr:>10s}      PM [deg]   GBW [kHz]']
    try:
        for v in vals:
            setattr(ldo, attr, v)
            fk = f_of(v)
            print(f'  {attr} = {fmt(v)}  (f ~ {fk:.1f} kHz)', flush=True)
            try:
                m = simulate_ac()['metrics']
                pm = m.get('phase_margin_deg', float('nan'))
                gbw = m.get('gbw_hz', float('nan'))
            except Exception as exc:            # keep sweeping like upstream
                print(f'  WARN: sim failed ({exc})')
                pm, gbw = float('nan'), float('nan')
            results.append((v, pm, gbw, fk))
            lines.append(f'{fmt(v):>12s}   {_fmt(pm, 1):>8s}   '
                         f'{_fmt(gbw / 1e3, 1):>9s}')
    finally:
        setattr(ldo, attr, orig)
    report = '\n'.join(lines)

    def render():
        before = _snapshot_pngs(plot_dir)
        mod._plot(results)
        return _new_pngs(plot_dir, before), report
    return CircuitResult(render)


def _run_ldo_theory(plot_dir):
    """LDO theory-vs-simulation check — mirrors run_theory_verification.main()
    with the sim/analysis on the worker and the module's _plot deferred."""
    import math
    import numpy as np
    import ldo_common as ldo
    import run_theory_verification as tv
    from simulate_ldo_ac import simulate_ac

    res = simulate_ac()
    lg, psrr_d, zout_d, m = (res['loopgain'], res['psrr'], res['zout'],
                             res['metrics'])
    freq_lg, T_mag, T_phase = lg['freq'], lg['mag_db'], lg['phase_deg']
    gbw_hz = m.get('gbw_hz', float('nan'))
    pm_deg = m.get('phase_margin_deg', float('nan'))
    dc_gain = m.get('dc_gain_db', float('nan'))

    fz_th = 1 / (2 * math.pi * ldo.R_COMP * ldo.C_COMP)
    fp_th = 1 / (2 * math.pi * ldo.R_LOAD_DEFAULT * ldo.C_OUT)
    fp_sim = tv._find_fp(freq_lg, T_mag) if freq_lg is not None else float('nan')
    fz_sim = (tv._find_fz(freq_lg, T_phase, fp_sim, gbw_hz)
              if freq_lg is not None else float('nan'))

    psrr_sim, psrr_th, zout_sim, zout_th = {}, {}, {}, {}
    for f in tv.F_SPOTS:
        psrr_sim[f] = -tv._interp_log(f, psrr_d['freq'], psrr_d['mag_db'])
        zout_sim[f] = tv._interp_log(f, zout_d['freq'], zout_d['mag_db'])
        t_db = tv._interp_log(f, freq_lg, T_mag)
        if not np.isnan(t_db):
            t_lin = 10 ** (t_db / 20)
            psrr_th[f] = 20 * np.log10(1 + t_lin)
            zout_th[f] = 20 * np.log10(ldo.R_LOAD_DEFAULT / (1 + t_lin))
        else:
            psrr_th[f] = zout_th[f] = float('nan')

    report = tv._build_report(fz_th, fp_th, fz_sim, fp_sim, gbw_hz, pm_deg,
                              dc_gain, psrr_sim, psrr_th, zout_sim, zout_th)

    def render():
        before = _snapshot_pngs(plot_dir)
        tv._plot(freq_lg, T_mag, T_phase,
                 psrr_d['freq'], psrr_d['mag_db'],
                 zout_d['freq'], zout_d['mag_db'],
                 fz_th, fp_th, fz_sim, fp_sim, gbw_hz, pm_deg,
                 psrr_sim, psrr_th, zout_sim, zout_th)
        return _new_pngs(plot_dir, before), report
    return CircuitResult(render)


def _run_bootstrap(analysis, values):
    import bootstrap_common as common
    # the vendored skill expects the ngspice-skill models at a hardcoded
    # path that doesn't exist here — point it at the app's synced copy
    from ngspice_common import spath
    common.MODEL_DIR = paths.NGSPICE_ASSETS / 'models'
    common.MODEL_PATH = spath(common.MODEL_DIR / 'ptm180.lib')
    _apply_params(common, values)
    if 'FCLK' in values:
        common.TCLK = 1.0 / common.FCLK
    import simulate_tran_bts_wave as sim_wave
    import simulate_tran_bts_ron as sim_ron
    import plot_tran_bts_wave as p_wave
    import plot_tran_bts_ron as p_ron

    res = {}
    if analysis in ('full', 'wave'):
        res['wave'] = sim_wave.simulate_wave()
    if analysis in ('full', 'ron'):
        res['ron'] = sim_ron.simulate_ron()

    lines = ['Bootstrapped Switch Summary', '=' * 27]
    wave = res.get('wave')
    if wave and wave.get('vboost') is not None:
        import numpy as np
        clk = wave['clk']
        vboost = wave['vboost']
        sampling = clk > wave['params']['VDD'] / 2
        if np.any(sampling):
            vb = vboost[sampling]
            lines += [
                'Bootstrap voltage (VGATE-VIN) during sampling:',
                f"  Mean : {_fmt(np.mean(vb), 3)} V  "
                f"(ideal {wave['params']['VDD']:.1f} V)",
                f"  Min  : {_fmt(np.min(vb), 3)} V",
                f"  Max  : {_fmt(np.max(vb), 3)} V"]
    if 'ron' in res:
        lines.append('Ron comparison : NMOS vs CMOS vs bootstrapped (see plot)')
    report = '\n'.join(lines)

    plot_dir = common.PLOT_DIR

    def render():
        before = _snapshot_pngs(plot_dir)
        if 'wave' in res:
            p_wave.plot_wave(res['wave'])
        if 'ron' in res:
            p_ron.plot_ron(res['ron'])
        return _new_pngs(plot_dir, before), report
    return CircuitResult(render)


_RUNNERS = {
    'ota5t': _run_ota,
    'opamp2': _run_opamp,
    'ldo': _run_ldo,
    'comparator': _run_comparator,
    'bootstrap': _run_bootstrap,
}

"""Running one sizing through ngspice and reading the metrics back.

Renders the circuit's testbench with absolute workspace paths and the
candidate .PARAM values, runs ngspice in batch mode, and parses the .meas
log / wrdata files into the metric dict that :mod:`.scoring` turns into a
cost.  ``capture_waves`` is the same path with the swept curves kept.
"""

import os
import re
import subprocess
from pathlib import Path

import numpy as np

from app import paths
from app.core.ngspice_locator import locate
from app.core.sizing.assets import _pkg_root, _variables_path
from app.core.sizing.registry import SIZING
from app.core.sizing.spec import SizingSpec, _fmt_num


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


def _render_testbench(spec: SizingSpec, run: Path,
                      single_thread: bool = False,
                      dump_waves: bool = False) -> Path:
    """Rewrite the vendored testbench's include lines with absolute paths
    (netlist / generated params / extracted PDK), substitute the DUT subckt
    name (the shared amp TB is written against HoiLee_AFFC) and drop
    interactive `plot` commands.  Paths are quoted (may contain spaces).

    single_thread injects `set num_threads=1` into the control block:
    ngspice's internal threading spin-waits badly under concurrent
    instances (measured: 4 parallel runs 10.2 s → 4.5 s wall with it).

    dump_waves injects a `wrdata` after each analysis in the control block
    so the swept curves land next to the log — relative filenames, written
    into the run cwd, so spaced paths never bite:
      amp TB:  DC temp sweep -> waves_dc.dat  (v(vout6) vs temperature)
               ac sweep      -> waves_ac.dat  (ADM dB/phase, CM, PSRR±)
      ldo TBs: the vector names differ per circuit (vout1/ppsr1 vs
               Vreg1/Vreg2), but every `ac dec` is followed by a
               `plot <loop dB> <PSRR dB> <loop phase>` line — harvest those
               tokens into waves_ac_<n>.dat (n=0 maxload, n=1 minload).
               ldo_basic additionally gets waves_dc.dat after its first
               VDD sweep (the variants already write a _Vdrop_maxload
               sweep file the capture reads directly)."""
    src = _pkg_root(spec) / spec.kind / 'testbench' / spec.testbench
    netlist_dir = _pkg_root(spec) / spec.kind / 'netlist'
    netlist = netlist_dir / spec.netlist
    pdk = paths.sky130_pdk_dir()
    out_lines = []
    n_ac = 0                 # ldo: AC sweeps seen (0=maxload, 1=minload)
    pending_ac = False       # ldo: harvest the next plot line's vectors
    dc_injected = False      # ldo_basic: only the first VDD sweep
    for line in src.read_text().splitlines():
        ls = line.strip().lower()
        if ls.startswith('.include'):
            inc = line.split(None, 1)[1].strip().strip('"')
            base = inc.rsplit('/', 1)[-1]
            if '/spice_netlist/' in inc:
                line = f'.include "{netlist}"'
            elif '/design_variables/' in inc:
                line = f'.include "{run / "params.spice"}"'
            elif 'mosfet_model/sky130_pdk/' in inc:
                rel = inc.split('mosfet_model/sky130_pdk/', 1)[1]
                line = f'.include "{pdk / rel}"'
            elif '/simulations/' in inc:
                # LDO-variant layout: <v>.txt = netlist, <v>_vars.spice =
                # design variables, <v>_dev_params.spice = op-point probes
                if base == spec.variables:
                    line = f'.include "{run / "params.spice"}"'
                elif base.endswith('_dev_params.spice'):
                    line = f'.include "{netlist_dir / base}"'
                else:
                    line = f'.include "{netlist}"'
        elif ls.startswith('plot ') or ls == 'plot':
            if dump_waves and spec.kind == 'ldo' and pending_ac:
                vecs = line.strip()[4:].strip()
                out_lines.append(f'wrdata waves_ac_{n_ac}.dat {vecs}')
                n_ac += 1
                pending_ac = False
            continue
        elif ls == '.control' and single_thread:
            out_lines.append(line)
            line = '  set num_threads=1'
        elif spec.subckt and spec.subckt != 'HoiLee_AFFC_Pin_3':
            line = re.sub(r'\bHoiLee_AFFC_Pin_3\b', spec.subckt, line)
        out_lines.append(line)
        if not dump_waves:
            continue
        if spec.kind == 'amp':
            if ls.startswith('dc temp'):
                out_lines.append('wrdata waves_dc.dat v(vout6)')
            elif ls.startswith('ac dec'):
                out_lines.append('wrdata waves_ac.dat vdb(opout) vp(opout) '
                                 'vdb(cm3) vdb(ppsr1) vdb(npsr1)')
        elif spec.kind == 'ldo':
            if ls.startswith('ac dec'):
                pending_ac = True
            elif (ls.startswith('dc vvdd') and not dc_injected
                    and spec.wrdata_prefix == 'LDO_TB_ACDC'):
                out_lines.append('wrdata waves_dc.dat v(vout6)')
                dc_injected = True
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


def _evaluate_skill(spec: SizingSpec, values: dict) -> dict:
    """One evaluation of a circuit-skills circuit via its plot-free
    simulate_*() metric path (runs inside skill_context import isolation;
    values are applied as module globals, incl. the 'W.key' dict syntax)."""
    import importlib
    from app.core import circuits
    cspec = circuits.CIRCUITS[spec.skill_key]
    scripts = paths.circuit_skills_dir() / cspec.subdir
    with circuits.skill_context(scripts):
        common = importlib.import_module(cspec.common_mod)
        circuits._apply_params(common, values)
        # point the model dir at the space-free workspace copy before the
        # simulate_* modules load — see circuits._repoint_models (Windows
        # installs with a space in the path break ngspice's .include)
        circuits._repoint_models(
            common, 'ptm45hp.lib' if spec.skill_key == 'comparator'
            else 'ptm180.lib')
        if spec.skill_key == 'ota5t':
            import simulate_ota_ac
            m = dict(simulate_ota_ac.simulate_ac()['metrics'])
            if 'phase_ugb_deg' in m:
                # the OTA sweep reports phase from the inverting output:
                # positive phase at UGB IS the phase margin; a negative
                # value follows the usual 180+phase convention
                ph = m['phase_ugb_deg']
                m['phase_margin_deg'] = ph if ph > 0 else 180.0 + ph
            return m
        if spec.skill_key == 'opamp2':
            import simulate_opamp_ac
            import simulate_opamp_dc
            m = dict(simulate_opamp_ac.simulate_ac()['metrics'])
            m['power_w'] = simulate_opamp_dc.simulate_dc()['dc']['power_w']
            return m
        if spec.skill_key == 'ldo':
            import simulate_ldo_ac
            return dict(simulate_ldo_ac.simulate_ac()['metrics'])
        if spec.skill_key == 'comparator' and spec.mode == 'fast':
            import simulate_tran_strongarm_wave as wave_mod
            tau = float(wave_mod.simulate_wave()['wave']['tau_ps'])
            # weighted device widths of the StrongArm core (2x input pair,
            # 1x tail, 2x latch N, 2x latch P, 4x reset)
            w = common.W
            total = (2 * w['inp'] + w['tail'] + 2 * w['lat_n']
                     + 2 * w['lat_p'] + 4 * w['rst'])
            return {'tau_ps': tau, 'total_w_um': float(total)}
        if spec.skill_key == 'comparator':
            import simulate_tran_strongarm_noise as noise_mod
            return dict(noise_mod.compute_fom(noise_mod.simulate_noise()))
        if spec.skill_key == 'bootstrap':
            if 'FCLK' in values:
                common.TCLK = 1.0 / common.FCLK
            import simulate_tran_bts_ron as sim_ron
            cfg = dict(sim_ron.NODE_CONFIGS[0])
            # W.sw was applied to common.W by _apply_params; the same width
            # also sizes the reference switches in the ron testbench config
            cfg['W_sw'] = float(common.W['sw'])
            r = sim_ron.simulate_ron(cfg)
            rb = np.asarray(r['ron_bts'], float)
            rb = rb[np.isfinite(rb) & (rb > 0)]
            if rb.size == 0:
                return {}
            return {'ron_bts_max': float(rb.max()),
                    'ron_flat': float(rb.max() / rb.min())}
    raise KeyError(spec.skill_key)


def evaluate(circuit: str, values: dict, slot: int = 0,
             single_thread: bool = False) -> dict:
    """One full testbench evaluation → metric dict (missing metrics absent).

    slot: parallel-evaluation lane — each slot gets its own run
    sub-directory so params/log/wrdata files never collide (AnalogGym
    circuits only; skill circuits are serial and ignore the slot).
    single_thread: see _render_testbench (set when running concurrently).
    """
    spec = SIZING[circuit]
    if spec.kind == 'skill':
        return _evaluate_skill(spec, values)
    paths.ensure_sky130()
    run = _run_dir(circuit) if slot == 0 else _run_dir(circuit) / f'w{slot}'
    run.mkdir(parents=True, exist_ok=True)
    _write_params(spec, values, run / 'params.spice')
    tb = _render_testbench(spec, run, single_thread=single_thread)
    log = run / 'log.txt'
    if log.exists():
        log.unlink()
    subprocess.run([_ngspice_cmd(), '-o', str(log), '-b', str(tb)],
                   cwd=run, capture_output=True, timeout=300)
    metrics = _parse_meas_log(log)
    if spec.kind == 'ldo':
        metrics = _ldo_metrics(run, metrics, spec.wrdata_prefix)
    return metrics


def _read_wave_file(path: Path) -> list[np.ndarray] | None:
    """Parse a wrdata sweep file: interleaved (x, y) column pairs, one row
    per sweep point.  Returns [x, y1, y2, ...] or None."""
    try:
        a = np.loadtxt(path, ndmin=2)
    except Exception:
        return None
    if a.shape[0] < 2 or a.shape[1] < 2:
        return None
    return [a[:, 0]] + [a[:, i] for i in range(1, a.shape[1], 2)]


def capture_waves(circuit: str, values: dict, tag: str) -> dict:
    """One characterization run with the swept curves captured, for the
    before/after waveform comparison ('before' = shipped defaults,
    'after' = a run's best point).  The returned dict always carries
    'kind' (drives the comparison panels) and 'metrics'; wave keys are
    absent when a sweep failed to produce data.

      amp       freq/adm_db/adm_ph/cm_db/psrp_db/psrn_db + temp/vout
      ldo       lg_max, lg_min = {freq, gain_db, psrr_db, phase}
                (phase already in degrees — the LDO TBs `set units=degrees`)
                + vin/vout line-regulation sweep
      skill_ac  freq/gain_db/phase             (ota5t, opamp2)
      skill_ldo loopgain/psrr/zout = {freq, mag_db, phase_deg}
      skill_wave time/clk/vlp/vln/outp/outn + tau_ps   (comparator)
      skill_ron vin_pts/ron_bts/ron_cmos/ron_nmos/ron_pmos  (bootstrap)
    """
    spec = SIZING[circuit]
    if spec.kind == 'skill':
        return _capture_skill_waves(spec, values)
    paths.ensure_sky130()
    run = _run_dir(circuit) / f'waves_{tag}'
    run.mkdir(parents=True, exist_ok=True)
    _write_params(spec, values, run / 'params.spice')
    tb = _render_testbench(spec, run, dump_waves=True)
    log = run / 'log.txt'
    if log.exists():
        log.unlink()
    subprocess.run([_ngspice_cmd(), '-o', str(log), '-b', str(tb)],
                   cwd=run, capture_output=True, timeout=300)
    out: dict = {'kind': spec.kind, 'metrics': _parse_meas_log(log)}
    if spec.kind == 'amp':
        ac = _read_wave_file(run / 'waves_ac.dat')
        if ac and len(ac) >= 6:
            out.update(freq=ac[0], adm_db=ac[1], adm_ph=ac[2],
                       cm_db=ac[3], psrp_db=ac[4], psrn_db=ac[5])
        dc = _read_wave_file(run / 'waves_dc.dat')
        if dc and len(dc) >= 2:
            out.update(temp=dc[0], vout=dc[1])
        return out
    # ldo: two harvested AC sweeps (loop dB, PSRR dB, loop phase) ...
    out['metrics'] = _ldo_metrics(run, out['metrics'], spec.wrdata_prefix)
    for i, load in ((0, 'max'), (1, 'min')):
        ac = _read_wave_file(run / f'waves_ac_{i}.dat')
        if ac and len(ac) >= 4:
            out[f'lg_{load}'] = dict(freq=ac[0], gain_db=ac[1],
                                     psrr_db=ac[2], phase=ac[3])
    # ... plus the Vout-vs-VDD line-regulation sweep (the variant TBs write
    # a _Vdrop_maxload sweep themselves; ldo_basic gets waves_dc.dat)
    vd = _read_wave_file(run / f'{spec.wrdata_prefix}_Vdrop_maxload')
    if vd is None:
        vd = _read_wave_file(run / 'waves_dc.dat')
    if vd and len(vd) >= 2:
        out.update(vin=vd[0], vout=vd[1])
    return out


def _capture_skill_waves(spec: SizingSpec, values: dict) -> dict:
    """Swept curves for a circuit-skills circuit — the simulate_* modules
    already return the arrays, so this mirrors _evaluate_skill's import
    isolation and just picks them out (no netlist changes)."""
    import importlib
    from app.core import circuits
    cspec = circuits.CIRCUITS[spec.skill_key]
    scripts = paths.circuit_skills_dir() / cspec.subdir
    with circuits.skill_context(scripts):
        common = importlib.import_module(cspec.common_mod)
        circuits._apply_params(common, values)
        circuits._repoint_models(
            common, 'ptm45hp.lib' if spec.skill_key == 'comparator'
            else 'ptm180.lib')
        if spec.skill_key in ('ota5t', 'opamp2'):
            mod = importlib.import_module(
                'simulate_ota_ac' if spec.skill_key == 'ota5t'
                else 'simulate_opamp_ac')
            r = mod.simulate_ac()
            out = {'kind': 'skill_ac', 'metrics': dict(r['metrics'])}
            ac = r.get('ac') or {}
            if ac.get('freq') is not None:
                out.update(freq=np.asarray(ac['freq'], float),
                           gain_db=np.asarray(ac['gain_db'], float),
                           phase=np.asarray(ac['phase'], float))
            return out
        if spec.skill_key == 'ldo':
            import simulate_ldo_ac
            r = simulate_ldo_ac.simulate_ac()
            out = {'kind': 'skill_ldo', 'metrics': dict(r['metrics'])}
            for k in ('loopgain', 'psrr', 'zout'):
                s = r.get(k) or {}
                if s.get('freq') is not None and s.get('mag_db') is not None:
                    out[k] = {kk: np.asarray(s[kk], float)
                              for kk in ('freq', 'mag_db', 'phase_deg')
                              if s.get(kk) is not None}
            return out
        if spec.skill_key == 'comparator':
            import simulate_tran_strongarm_wave as wave_mod
            w = wave_mod.simulate_wave()['wave']
            out = {'kind': 'skill_wave',
                   'metrics': {'tau_ps': float(w['tau_ps'])}}
            for k in ('time', 'clk', 'vlp', 'vln', 'outp', 'outn'):
                if w.get(k) is not None:
                    out[k] = np.asarray(w[k], float)
            return out
        if spec.skill_key == 'bootstrap':
            if 'FCLK' in values:
                common.TCLK = 1.0 / common.FCLK
            import simulate_tran_bts_ron as sim_ron
            cfg = dict(sim_ron.NODE_CONFIGS[0])
            cfg['W_sw'] = float(common.W['sw'])
            r = sim_ron.simulate_ron(cfg)
            out = {'kind': 'skill_ron', 'metrics': {}}
            for k in ('vin_pts', 'ron_bts', 'ron_cmos', 'ron_nmos',
                      'ron_pmos'):
                if r.get(k) is not None:
                    out[k] = np.asarray(r[k], float)
            return out
    raise KeyError(spec.skill_key)


def _ldo_metrics(run: Path, meas: dict, prefix: str) -> dict:
    """Fold the LDO testbench's wrdata outputs into named metrics.

    The Basic-LDO testbench writes LDO_TB_ACDC_*; each variant testbench
    uses its own prefix (ldo_simple_*, ldo_1_*, ...)."""
    out = {}
    v = _read_wrdata(run / f'{prefix}_LR_Power_vos', 5)
    if v:
        lr, p_max, p_min, vos_max, vos_min = v
        out.update(lr=lr, power_maxload=p_max, power_minload=p_min,
                   vos_maxload=vos_max, vos_minload=vos_min,
                   # quiescent current = supply current at min load − 5 mA
                   iq=max(p_min / 1.8 - 5e-3, 0.0))
    v = _read_wrdata(run / f'{prefix}_LNR_maxload', 1)
    if v:
        out['lnr'] = v[0]
    v = _read_wrdata(run / f'{prefix}_LNR_minload', 1)
    if v:
        out['lnr_minload'] = v[0]
    for load in ('maxload', 'minload'):
        v = _read_wrdata(run / f'{prefix}_GBW_PM_{load}', 2)
        if v:
            out[f'gbw_{load}'], out[f'pm_{load}'] = v
        v = _read_wrdata(run / f'{prefix}_PSRR_dcgain_{load}', 2)
        if v:
            out[f'psrr_{load}'], out[f'dcgain_{load}'] = v
    out.update(meas)
    return out


def netlist_texts(circuit: str, values: dict | None = None) \
        -> list[tuple[str, str]]:
    """(title, text) pairs for the netlist viewer.

    amp/ldo circuits: the DUT netlist, the design-variables file (rendered
    with `values` when given, e.g. the table's current init column) and
    the fully rendered testbench (absolute includes, DUT substituted).
    skill circuits: every *.cir.tmpl template in the skill's tree.
    """
    spec = SIZING[circuit]
    if spec.kind == 'skill':
        from app.core import circuits
        cspec = circuits.CIRCUITS[spec.skill_key]
        skill_root = paths.circuit_skills_dir() / cspec.subdir
        out = []
        for p in sorted(skill_root.parent.rglob('*.cir.tmpl')):
            out.append((p.name, p.read_text(errors='replace')))
        return out or [('(no templates found)', '')]
    root = _pkg_root(spec) / spec.kind
    out = [(f'netlist ({spec.netlist})',
            (root / 'netlist' / spec.netlist).read_text(errors='replace'))]
    if values:
        run = _run_dir(circuit) / 'netlist_view'
        run.mkdir(parents=True, exist_ok=True)
        _write_params(spec, values, run / 'params.spice')
        out.append(('variables (with table values)',
                    (run / 'params.spice').read_text(errors='replace')))
        tb = _render_testbench(spec, run)
        out.append(('testbench (rendered)',
                    tb.read_text(errors='replace')))
    else:
        out.append((f'variables ({spec.variables})',
                    _variables_path(spec).read_text(errors='replace')))
    return out

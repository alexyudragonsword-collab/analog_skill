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
    hard: bool = False    # hard constraint: violations weigh 10x


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
    subckt: str | None = None     # DUT token to substitute into the TB
    wrdata_prefix: str = ''       # LDO wrdata file prefix (variant TBs differ)
    skill_key: str | None = None  # kind='skill': key into circuits.CIRCUITS
    mode: str = ''                # skill variant: '' | 'fast' | 'ron'
    verify_key: str | None = None # re-evaluate the best point on this circuit
    pkg: str = 'analoggym'        # asset tree: 'analoggym' | 'studio'


def _amp_metrics() -> list:
    # targets from AnalogGym's spec dicts (ckt_graphs.py / README FoM)
    return [
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
    ]


def _cm_ota_metrics() -> list:
    """Targets for the single-stage current-mirror OTA (studio_circuits).

    Same TB_Amplifier_ACDC metric keys as the AnalogGym amps, but the
    targets are calibrated for a single-stage topology on a 500 pF load
    (measured default: 42 dB / 0.37 MHz / PM 90° / 0.42 mW).  A single
    stage tops out near ~45 dB, and GBW trades directly against power and
    (weakly) against gain — so gain 44 dB and GBW 0.6 MHz are reachable
    but not simultaneously free, which is the whole point of the sizing."""
    return [
        MetricSpec('dcgain', 'DC gain', 'dB', 44.0, 'max', 2.0),
        MetricSpec('gain_bandwidth_product', 'GBW', 'Hz', 0.6e6, 'max', 2.0),
        # single-pole-dominated → naturally ~90°; require ≥ 55°, no penalty
        # for the extra stability
        MetricSpec('phase_in_deg', 'Phase margin', 'deg', 55.0, 'max', 1.0),
        MetricSpec('cmrrdc', 'CMRR (dc)', 'dB', -60.0, 'min', 1.0),
        MetricSpec('dcpsrp', 'PSRR+ (dc)', 'dB', -45.0, 'min', 1.0),
        MetricSpec('dcpsrn', 'PSRR- (dc)', 'dB', -50.0, 'min', 1.0),
        MetricSpec('power', 'Power', 'W', 1.0e-3, 'min', 1.0),
        MetricSpec('vos25', 'Offset (25C)', 'V', 5e-3, 'absmin', 0.5),
        MetricSpec('tc', 'Temp. coeff.', 'V/°C', 60e-6, 'absmin', 0.5),
    ]


def _ldo_metrics_spec() -> list:
    return [
        MetricSpec('pm_maxload', 'Phase margin (55 mA)', 'deg', 60.0,
                   'target', 1.5),
        MetricSpec('pm_minload', 'Phase margin (5 mA)', 'deg', 60.0,
                   'target', 1.5),
        MetricSpec('gbw_maxload', 'Loop GBW (55 mA)', 'Hz', 2e6, 'max', 1.5),
        MetricSpec('lnr', 'Line regulation', 'V/V', 0.01, 'absmin', 1.0),
        MetricSpec('lr', 'Load regulation', 'V/A', 0.1, 'absmin', 1.0),
        MetricSpec('psrr_maxload', 'PSRR (dc, 55 mA)', 'dB', -40.0,
                   'min', 1.0),
        MetricSpec('vos_maxload', 'Vout error (55 mA)', 'V', 2e-3,
                   'absmin', 1.0),
        MetricSpec('iq', 'Quiescent current', 'A', 1e-3, 'min', 1.0),
    ]


# 15 Miller multi-stage op amps validated with ngspice-42 at their default
# sizing.  Excluded upstream defects: Qu_LEC (netlist file ships empty) and
# Tan_CLIA (default W=0.253 um is below the SKY130 model-bin range →
# "could not find a valid modelname").  All share the 5-pin subckt contract
# gnda vdda vinn vinp vout and the TB_Amplifier_ACDC testbench (DUT name
# substituted at render time).
_AMP_NETLISTS = [
    'HoiLee_AFFC_Pin_3', 'Leung_NMCF_Pin_3', 'Leung_NMCNR_Pin_3',
    'Leung_DFCFC1_Pin_3', 'Leung_DFCFC2_Pin_3', 'Peng_ACBC_Pin_3',
    'Peng_IAC_Pin_3', 'Peng_TCFC_Pin_3', 'Qu2017_AZC_Pin_3',
    'Ramos_PFC_Pin_3', 'Sau_CFCC_Pin_3', 'Song_DACFC_Pin_3',
    'Yan_AZ_Pin_3', 'Fan_SMC_Pin_3', 'Alfio_RAFFC_Pin_3',
]

# LDO variants: each has its own testbench; wrdata files carry the prefix
# (ldo_1/ldo_2 insert an extra _ACDC infix).
_LDO_VARIANTS = {'ldo_simple': 'ldo_simple', 'ldo_1': 'ldo_1_ACDC',
                 'ldo_2': 'ldo_2_ACDC',
                 'ldo_folded_cascode': 'ldo_folded_cascode'}

# circuit-skills (PTM) circuits wired into the same optimizer via their
# plot-free simulate_*() metric paths.  The comparator additionally gets a
# fast τ-proxy entry (seconds per eval, probit-verified at the end via
# verify_key), and the bootstrap switch is optimizable through scalar Ron
# metrics post-processed from its gds-based ron testbench.
# Targets sit above the measured default-sizing values (see tests /
# ANALOG_REPOS_ANALYSIS) so the optimizer has headroom in each direction.
_SKILL_CIRCUITS: dict[str, dict] = {
    # targets calibrated against measured defaults on ngspice-42:
    # ota5t 34.3 dB / 85 MHz / PM 77.2°; opamp2 64.3 dB / 13.7 MHz /
    # PM 80.7° / 1.72 mW; ldo 51.7 dB / 1.18 MHz / PM 58.6° / PSRR 57.3 dB
    'ota5t': dict(
        title='5T OTA — circuit-skills (PTM 180 nm)',
        fixed=('C_LOAD',), eval_seconds=2.0,
        metrics=[
            MetricSpec('dc_gain_db', 'DC gain', 'dB', 40.0, 'max', 2.0),
            MetricSpec('ugb_hz', 'UGB', 'Hz', 100e6, 'max', 2.0),
            MetricSpec('phase_margin_deg', 'Phase margin', 'deg', 60.0,
                       'target', 1.5),
        ]),
    'opamp2': dict(
        title='Two-stage Miller op amp — circuit-skills (PTM 180 nm)',
        fixed=('CL',), eval_seconds=5.0,
        metrics=[
            MetricSpec('dc_gain_db', 'DC gain', 'dB', 70.0, 'max', 2.0),
            MetricSpec('ugb_hz', 'UGB', 'Hz', 40e6, 'max', 2.0),
            MetricSpec('phase_margin_deg', 'Phase margin', 'deg', 60.0,
                       'target', 1.5),
            MetricSpec('power_w', 'Power', 'W', 2e-3, 'min', 1.0),
        ]),
    'ldo': dict(
        title='LDO — circuit-skills (PTM 180 nm)',
        fixed=('R_LOAD_DEFAULT',), eval_seconds=5.0,
        metrics=[
            MetricSpec('dc_gain_db', 'Loop DC gain', 'dB', 55.0, 'max', 1.5),
            MetricSpec('gbw_hz', 'Loop GBW', 'Hz', 2e6, 'max', 1.5),
            MetricSpec('phase_margin_deg', 'Phase margin', 'deg', 60.0,
                       'target', 1.5),
            # circuit-skills LDO reports PSRR as positive rejection dB
            MetricSpec('psrr_dc_db', 'PSRR (dc)', 'dB', 60.0, 'max', 1.0),
        ]),
    # comparator defaults measured on ngspice-42: σ=178.6 µV,
    # P=104 µW, Tcmp=55.3 ps (162 s per evaluation, 3x1000 cycles)
    'comparator': dict(
        title='StrongArm comparator — circuit-skills (PTM 45 nm, '
              '~2 min/eval)',
        fixed=('NOISE_VIN_MV',), eval_seconds=160.0,
        metrics=[
            MetricSpec('sigma_uv', 'Input noise σ', 'uV', 150.0,
                       'absmin', 1.5),
            MetricSpec('p_avg_uw', 'Avg power', 'uW', 80.0, 'min', 1.0),
            MetricSpec('tcmp_ps', 'Decision time', 'ps', 50.0, 'min', 1.0),
        ]),
}


def _build_registry() -> dict[str, SizingSpec]:
    reg: dict[str, SizingSpec] = {}
    for name in _AMP_NETLISTS:
        short = name[:-6]                     # drop the _Pin_3 suffix
        key = 'amp_' + short.lower()
        sch = f'{name}.png'
        if not (paths.analoggym_dir() / 'amp' / 'schematic' / sch).is_file():
            sch = None
        reg[key] = SizingSpec(
            title=f'3-stage op amp — {short} (SKY130, 1.8 V)',
            kind='amp', netlist=name, variables=name,
            testbench='TB_Amplifier_ACDC.cir', metrics=_amp_metrics(),
            fixed=('CLOAD', 'VCM'), schematic=sch, eval_seconds=3.5,
            subckt=name)
    reg['ldo_basic'] = SizingSpec(
        title='Basic LDO (SKY130, 1.8 V, 5–55 mA)',
        kind='ldo', netlist='LDO_netlist.txt', variables='LDO_variables.txt',
        testbench='TB_LDO_ACDC.cir', metrics=_ldo_metrics_spec(),
        fixed=('M_CL',), eval_seconds=8.0, wrdata_prefix='LDO_TB_ACDC')
    for v, prefix in _LDO_VARIANTS.items():
        reg[v] = SizingSpec(
            title=f'LDO — {v} (SKY130, 1.8 V, 5–55 mA)',
            kind='ldo', netlist=f'{v}.txt', variables=f'{v}_vars.spice',
            testbench=f'{v}_acdc.cir', metrics=_ldo_metrics_spec(),
            fixed=('M_CL',), eval_seconds=8.0, wrdata_prefix=prefix)
    for key, cfg in _SKILL_CIRCUITS.items():
        reg[f'skill_{key}'] = SizingSpec(
            title=cfg['title'], kind='skill', netlist='', variables='',
            testbench='', metrics=cfg['metrics'], fixed=cfg['fixed'],
            eval_seconds=cfg['eval_seconds'], skill_key=key)
    # fast comparator proxy: seconds-per-eval latch-tau + total-width
    # objective; the best point is re-verified with one full probit run
    # (defaults measured on ngspice-42: tau=8.6 ps, weighted ΣW=22 um)
    reg['skill_comparator_fast'] = SizingSpec(
        title='StrongArm comparator — fast τ proxy, probit-verified '
              '(PTM 45 nm)',
        kind='skill', netlist='', variables='', testbench='',
        metrics=[
            MetricSpec('tau_ps', 'Latch τ (speed proxy)', 'ps', 6.0,
                       'min', 2.0),
            MetricSpec('total_w_um', 'Σ width (power proxy)', 'um', 18.0,
                       'min', 1.0),
        ],
        fixed=('NOISE_VIN_MV',), eval_seconds=1.0,
        skill_key='comparator', mode='fast',
        verify_key='skill_comparator')
    # bootstrapped switch: app-layer scalars from the ron arrays
    # (defaults measured on ngspice-42: Ron_max=86.3 ohm, flatness=1.25)
    reg['skill_bootstrap'] = SizingSpec(
        title='Bootstrapped switch — circuit-skills (PTM 180 nm)',
        kind='skill', netlist='', variables='', testbench='',
        metrics=[
            MetricSpec('ron_bts_max', 'Ron max (track)', 'ohm', 70.0,
                       'min', 1.5),
            MetricSpec('ron_flat', 'Ron max/min', '', 1.2, 'min', 1.5),
        ],
        fixed=(), eval_seconds=1.5, skill_key='bootstrap', mode='ron')
    # original studio_circuits (authored for this app, not vendored):
    # single-stage PMOS-input current-mirror OTA on SKY130, reusing the
    # AnalogGym amp testbench/harness for the full 9-metric report
    reg['studio_cm_ota'] = SizingSpec(
        title='Current-mirror OTA — Analog Studio (SKY130, 1.8 V)',
        kind='amp', netlist='CM_OTA_Pin_3', variables='CM_OTA_Pin_3',
        testbench='TB_Amplifier_ACDC.cir', metrics=_cm_ota_metrics(),
        fixed=('CLOAD', 'VCM'), eval_seconds=3.5,
        subckt='CM_OTA_Pin_3', pkg='studio', schematic='CM_OTA_Pin_3.png')
    return reg


SIZING: dict[str, SizingSpec] = _build_registry()


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
    if n.startswith('v'):                         # bias voltage (1.8 V rail)
        return max(0.1, default * 0.5), min(1.8, default * 1.5), False
    return default / 4 if default > 0 else default * 4, \
        default * 4 if default > 0 else default / 4, False


def _pkg_root(spec: SizingSpec) -> Path:
    """Asset tree for a netlist/variables/testbench circuit: the vendored
    AnalogGym subset or the original studio_circuits tree (both share the
    <root>/<kind>/{netlist,variables,testbench} layout)."""
    return (paths.studio_circuits_dir() if spec.pkg == 'studio'
            else paths.analoggym_dir())


def _variables_path(spec: SizingSpec) -> Path:
    return (_pkg_root(spec) / spec.kind / 'variables' / spec.variables)


def _skill_variables(spec: SizingSpec) -> list[VarSpec]:
    """VarSpecs from circuits.CIRCUITS[...].params (module-global params).

    Registry min/max are mostly UI placeholders (0 / 1e12), so bounds fall
    back to unit-aware heuristics: widths ≥ 0.5 um, voltages capped at the
    1.8 V rail, everything else a factor-4 window around the default."""
    from app.core import circuits
    out = []
    if spec.skill_key == 'bootstrap' and spec.mode == 'ron':
        # the bootstrapped DUT's sampling switch is W['sw'] in
        # bootstrap_common (render_dut); the dotted name goes through
        # _apply_params' dict syntax and is mirrored into the ron
        # testbench's node config by _evaluate_skill
        out.append(VarSpec('W.sw', 10.0, 2.0, 40.0, False))
    for p in circuits.CIRCUITS[spec.skill_key].params:
        if p.attr in spec.fixed:
            continue
        d = p.default
        if 0.0 < p.minv and p.maxv < 1e11:
            lo, hi = p.minv, p.maxv
        elif p.unit == 'um' or p.attr.startswith('W'):
            lo, hi = max(0.5, d / 4), d * 4
        elif p.unit == 'V':
            lo, hi = d * 0.5, min(d * 1.5, 1.8)
        else:
            lo, hi = d / 4, d * 4
        lo, hi = min(lo, d), max(hi, d)
        out.append(VarSpec(p.attr, d, lo, hi, p.kind == 'int'))
    return out


def parse_variables(circuit: str) -> list[VarSpec]:
    """Parse the shipped .PARAM file into editable variable specs.

    Continuation lines (`+ name=value name=value`) and `.param n=v n=v`
    forms are both handled; `fixed` names and expression-valued params
    (e.g. `W_M2=W_M1`) are excluded from the optimizable set.
    """
    spec = SIZING[circuit]
    if spec.kind == 'skill':
        return _skill_variables(spec)
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
    if spec.kind == 'skill':
        from app.core import circuits
        return circuits.schematic_path(spec.skill_key)
    if not spec.schematic:
        return None
    p = _pkg_root(spec) / spec.kind / 'schematic' / spec.schematic
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

    dump_waves (amp TB only) injects a `wrdata` after each analysis in the
    control block so the swept curves land next to the log — relative
    filenames, written into the run cwd, so spaced paths never bite:
      DC temp sweep -> waves_dc.dat  (v(vout6) vs temperature)
      ac sweep      -> waves_ac.dat  (ADM dB/phase, CM, PSRR± vs freq)"""
    src = _pkg_root(spec) / spec.kind / 'testbench' / spec.testbench
    netlist_dir = _pkg_root(spec) / spec.kind / 'netlist'
    netlist = netlist_dir / spec.netlist
    pdk = paths.sky130_pdk_dir()
    out_lines = []
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
            continue
        elif ls == '.control' and single_thread:
            out_lines.append(line)
            line = '  set num_threads=1'
        elif spec.subckt and spec.subckt != 'HoiLee_AFFC_Pin_3':
            line = re.sub(r'\bHoiLee_AFFC_Pin_3\b', spec.subckt, line)
        out_lines.append(line)
        if dump_waves and ls.startswith('dc temp'):
            out_lines.append('wrdata waves_dc.dat v(vout6)')
        elif dump_waves and ls.startswith('ac dec'):
            out_lines.append('wrdata waves_ac.dat vdb(opout) vp(opout) '
                             'vdb(cm3) vdb(ppsr1) vdb(npsr1)')
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
    """One characterization run of an amp-testbench circuit with the swept
    curves captured (see _render_testbench dump_waves).  Returns
    {freq, adm_db, adm_ph, cm_db, psrp_db, psrn_db, temp, vout, metrics};
    wave keys are absent when a sweep failed to produce data.

    Used for the before/after waveform comparison — 'before' is the shipped
    default sizing, 'after' a run's best point.  Only kind='amp' circuits
    share the TB_Amplifier_ACDC node names this relies on.
    """
    spec = SIZING[circuit]
    if spec.kind != 'amp':
        raise ValueError(f'waveform capture supports amp circuits only, '
                         f'not {circuit} (kind={spec.kind})')
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
    out: dict = {'metrics': _parse_meas_log(log)}
    ac = _read_wave_file(run / 'waves_ac.dat')
    if ac and len(ac) >= 6:
        out.update(freq=ac[0], adm_db=ac[1], adm_ph=ac[2],
                   cm_db=ac[3], psrp_db=ac[4], psrn_db=ac[5])
    dc = _read_wave_file(run / 'waves_dc.dat')
    if dc and len(dc) >= 2:
        out.update(temp=dc[0], vout=dc[1])
    return out


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


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────
_MISSING_PENALTY = 10.0
_HARD_FACTOR = 10.0


def _violation(ms: MetricSpec, m: float, target: float) -> float:
    if ms.direction == 'max':
        return max(0.0, (target - m) / abs(target))
    if ms.direction == 'min':
        return max(0.0, (m - target) / abs(target))
    if ms.direction == 'absmin':
        return max(0.0, (abs(m) - target) / abs(target))
    return abs(m - target) / abs(target)         # 'target'


def score(circuit: str, metrics: dict, overrides: dict | None = None) -> float:
    """Weighted violation cost against the target specs (0 = all met).

    max:    penalize (target − m)/|target| when below target
    min:    penalize (m − target)/|target| when above target
    absmin: like min on |m|
    target: |m − target|/|target|  (e.g. phase margin 60°)

    overrides: {metric_key: (target, hard)} — GUI-edited targets; a hard
    constraint multiplies its violation by 10.
    """
    overrides = overrides or {}
    cost = 0.0
    for ms in SIZING[circuit].metrics:
        target, hard = overrides.get(ms.key, (ms.target, ms.hard))
        w = ms.weight * (_HARD_FACTOR if hard else 1.0)
        m = metrics.get(ms.key)
        if m is None or not np.isfinite(m):
            cost += w * _MISSING_PENALTY
            continue
        cost += w * min(_violation(ms, m, target), _MISSING_PENALTY)
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
    overrides: dict | None = None
    verified: dict | None = None  # full re-evaluation of the best point

    def report(self) -> str:
        spec = SIZING[self.circuit]
        ov = self.overrides or {}
        lines = [spec.title, '',
                 f'evaluations: {self.evals}'
                 + ('  (cancelled)' if self.cancelled else '')
                 + f'   elapsed: {self.elapsed:.0f}s',
                 f'cost: {self.initial_cost:.4f}  ->  {self.best_cost:.4f}'
                 f'   (FoM {-self.best_cost:.4f})', '',
                 f'{"metric":<22}{"value":>14}   target']
        for ms in spec.metrics:
            target, hard = ov.get(ms.key, (ms.target, ms.hard))
            m = self.best_metrics.get(ms.key)
            if m is None:
                mark, val = '✗', 'n/a'
            else:
                mark = '✓' if _violation(ms, m, target) <= 1e-9 else '✗'
                val = f'{m:.4g}'
            lines.append(f'{ms.label:<22}{val:>14} {ms.unit:<6}'
                         f'{mark} {ms.direction} {target:g}'
                         + ('  [HARD]' if hard else ''))
        if self.verified is not None:
            vkey = SIZING[self.circuit].verify_key
            lines += ['', f'verified (full evaluation, {vkey}):']
            for ms in SIZING[vkey].metrics:
                m = self.verified.get(ms.key)
                val = f'{m:.4g}' if m is not None else 'n/a'
                lines.append(f'  {ms.label:<20}{val:>14} {ms.unit}')
        lines += ['', 'device changes vs default '
                      '(W/L um, M multiplier; before->after):',
                  change_summary(self.circuit, self.best_values)]
        lines += ['', 'best design variables:']
        for k, v in self.best_values.items():
            lines.append(f'  {k} = {_fmt_num(v)}')
        return '\n'.join(lines)

    def params_text(self) -> str:
        """Best sizing as a .PARAM file (same shape as the shipped one);
        skill circuits export a plain name = value listing instead."""
        spec = SIZING[self.circuit]
        if spec.kind == 'skill':
            return '\n'.join(f'{k} = {_fmt_num(v)}'
                             for k, v in self.best_values.items()) + '\n'
        buf = Path(_run_dir(self.circuit) / 'best_params.spice')
        _write_params(spec, self.best_values, buf)
        return buf.read_text()


_MOS_VAR = re.compile(r'^(MOSFET_\d+_\d+)_([WLM])_(\w+)$')


def change_summary(circuit: str, best_values: dict) -> str:
    """Per-device summary of the best sizing vs the shipped defaults.

    AnalogGym variables (MOSFET_<i>_<j>_{W,L,M}_<role>) are grouped into
    one line per device showing its W/L/M before -> after; everything else
    (capacitors, bias currents, skill W.xxx dict entries) gets a flat line.
    Devices are ordered by how much they changed (largest |log ratio|
    first); unchanged variables collapse into a trailing count.
    """
    defaults = {v.name: v.default for v in parse_variables(circuit)}

    def fmt(a: float, b: float) -> str:
        if a == b:
            return _fmt_num(a)
        return f'{_fmt_num(a)}->{_fmt_num(b)}'

    def ratio(a: float, b: float) -> float:
        if a == b:
            return 0.0
        if a == 0 or b == 0:
            return float('inf')
        return abs(np.log(abs(b / a)))

    groups: dict[str, dict] = {}      # device -> {'role':…, 'W':(a,b), …}
    flat: list[tuple[str, float, float]] = []
    unchanged = 0
    for name, a in defaults.items():
        b = best_values.get(name, a)
        m = _MOS_VAR.match(name)
        if m:
            dev, dim, role = m.groups()
            g = groups.setdefault(dev, {'role': role})
            g[dim] = (a, b)
        elif a == b:
            unchanged += 1
        else:
            flat.append((name, a, b))

    lines = []
    dev_rows = []
    for dev, g in groups.items():
        r = max(ratio(*g[d]) for d in 'WLM' if d in g)
        if r == 0.0:
            unchanged += sum(1 for d in 'WLM' if d in g)
            continue
        cell = '  '.join(f'{d} {fmt(*g[d])}' for d in 'WLM' if d in g)
        dev_rows.append((r, f'  {dev:<14}{g["role"]:<18}{cell}'))
    for r, row in sorted(dev_rows, key=lambda t: -t[0]):
        lines.append(row)
    for name, a, b in sorted(flat, key=lambda t: -ratio(t[1], t[2])):
        lines.append(f'  {name:<32}{fmt(a, b)}')
    if unchanged:
        lines.append(f'  ({unchanged} variable(s) unchanged)')
    if not lines:
        lines.append('  (no changes vs default)')
    return '\n'.join(lines)


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
        return dict(zip(names, x.tolist()))

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
        study.enqueue_trial({n: float(x) for n, x in zip(names, x0)})
        while not state['cancel'] and state['dispatched'] < budget:
            k = min(workers, budget - state['dispatched'])
            trials = [study.ask() for _ in range(k)]
            xs = [np.array([t.suggest_float(n, 0.0, 1.0) for n in names])
                  for t in trials]
            costs = run_batch(xs)
            for t, c in zip(trials, costs):
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


def render_wave_comparison(circuit: str, before: dict, after: dict) -> Path:
    """Overlay the default-sizing vs best-sizing characterization sweeps
    (GUI thread — matplotlib policy).  2x2: differential gain / phase /
    PSRR± vs frequency, and Vout vs temperature."""
    import matplotlib
    matplotlib.use('Agg', force=False)
    import matplotlib.pyplot as plt
    B_STY = dict(color='#95a5a6', ls='--', lw=1.6)
    A_STY = dict(color='#2874a6', lw=1.8)
    fig, axes = plt.subplots(2, 2, figsize=(9.6, 7.0), constrained_layout=True)
    (ax_g, ax_p), (ax_r, ax_t) = axes
    have_ac = 'freq' in before and 'freq' in after

    if have_ac:
        ax_g.semilogx(before['freq'], before['adm_db'],
                      label='default', **B_STY)
        ax_g.semilogx(after['freq'], after['adm_db'],
                      label='optimized', **A_STY)
        ax_g.axhline(0, color='#c0392b', ls=':', lw=1)
        # ngspice's vp() reports radians — plot in degrees
        ax_p.semilogx(before['freq'], np.degrees(before['adm_ph']), **B_STY)
        ax_p.semilogx(after['freq'], np.degrees(after['adm_ph']), **A_STY)
        ax_r.semilogx(before['freq'], before['psrp_db'],
                      label='PSRR+ default', **B_STY)
        ax_r.semilogx(after['freq'], after['psrp_db'],
                      label='PSRR+ optimized', **A_STY)
        ax_r.semilogx(before['freq'], before['psrn_db'], color='#95a5a6',
                      ls=':', lw=1.6, label='PSRR− default')
        ax_r.semilogx(after['freq'], after['psrn_db'], color='#148f77',
                      lw=1.8, label='PSRR− optimized')
        ax_r.legend(fontsize=7)
    ax_g.set_xlabel('frequency (Hz)'); ax_g.set_ylabel('|Adm| (dB)')
    ax_g.set_title('Differential gain', fontsize=10)
    ax_g.legend(fontsize=8)
    ax_p.set_xlabel('frequency (Hz)'); ax_p.set_ylabel('phase (deg)')
    ax_p.set_title('Phase', fontsize=10)
    ax_r.set_xlabel('frequency (Hz)'); ax_r.set_ylabel('PSRR (dB)')
    ax_r.set_title('Supply rejection', fontsize=10)

    if 'temp' in before and 'temp' in after:
        ax_t.plot(before['temp'], before['vout'] * 1e3, **B_STY)
        ax_t.plot(after['temp'], after['vout'] * 1e3, **A_STY)
    ax_t.set_xlabel('temperature (°C)'); ax_t.set_ylabel('Vout (mV)')
    ax_t.set_title('Output vs temperature (offset drift)', fontsize=10)

    for ax in axes.flat:
        ax.grid(alpha=0.3, which='both')
    fig.suptitle(f'Before/after characterization — {SIZING[circuit].title}',
                 fontsize=11)
    out = _run_dir(circuit) / 'wave_compare.png'
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Run persistence: save / load / list / compare
# ─────────────────────────────────────────────────────────────────────────────
RUN_SCHEMA = 1


def runs_dir() -> Path:
    d = Path(os.environ.get('ANALOG_WORK_DIR',
                            Path.home() / '.analog_studio')) / 'sizing_runs'
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


def render_comparison(runs: list[SizingRun]) -> Path:
    """Overlay the convergence curves of several saved runs
    (GUI thread — matplotlib policy)."""
    import matplotlib
    matplotlib.use('Agg', force=False)
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.4, 4.2), constrained_layout=True)
    for run in runs:
        xs = [h[0] for h in run.history]
        ys = [-h[1] for h in run.history]
        ax.plot(xs, ys, '-o', ms=3,
                label=f'{run.circuit}  ({run.evals} evals, '
                      f'FoM {-run.best_cost:.3f})')
    ax.set_xlabel('evaluation')
    ax.set_ylabel('best FoM (= -cost, higher is better)')
    ax.set_title('Sizing runs — convergence comparison', fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    out = runs_dir() / 'comparison.png'
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out

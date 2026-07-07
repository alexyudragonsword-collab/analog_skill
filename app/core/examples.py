"""Declarative registry of the nine ngspice teaching examples.

Parameters live as module-level constants inside each simulate_* module and
``simulate_all()`` takes no arguments, so the runner temporarily monkey-
patches the module globals (restored in ``finally``) — the skill files
themselves are never modified.

Some constants come in (spice-string, SI-float) pairs (e.g. IREF="100u" /
IREF_SI=1e-4); a ParamSpec's ``to_attrs`` maps one form value onto all the
attrs that must stay consistent.
"""

import copy
import importlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_PREFIXES = [
    (1e9, 'G'), (1e6, 'Meg'), (1e3, 'k'), (1.0, ''),
    (1e-3, 'm'), (1e-6, 'u'), (1e-9, 'n'), (1e-12, 'p'), (1e-15, 'f'),
]


def si_to_spice(value: float) -> str:
    """1e3 → '1k', 1e-12 → '1p', 2.2e-6 → '2.2u'."""
    if value == 0:
        return '0'
    for scale, suffix in _PREFIXES:
        if abs(value) >= scale:
            num = value / scale
            txt = f'{num:.6g}'
            return txt + suffix
    return f'{value:.6g}'


_SUFFIX_SI = {
    'g': 1e9, 'meg': 1e6, 'k': 1e3, '': 1.0,
    'm': 1e-3, 'u': 1e-6, 'n': 1e-9, 'p': 1e-12, 'f': 1e-15,
}


def _spice_to_si(text) -> float:
    """Parse a SPICE magnitude string: '1Meg' → 1e6, '10G' → 1e10, '1p' → 1e-12."""
    s = str(text).strip().lower()
    for suffix in ('meg', 'g', 'k', 'm', 'u', 'n', 'p', 'f'):
        if s.endswith(suffix):
            return float(s[:-len(suffix)]) * _SUFFIX_SI[suffix]
    return float(s)


@dataclass
class ParamSpec:
    key: str                        # form-field id
    label: str
    kind: str                       # 'float' | 'int' | 'floatlist'
    unit: str = ''
    default: Any = None             # static value or callable(module) -> value
    minimum: float = 0.0
    maximum: float = 1e12
    decimals: int = 3
    to_attrs: Callable[[Any], dict] | None = None   # value -> module attrs
    advanced: bool = False          # place under a collapsible "Advanced" group
    override_only: bool = False      # consumed solely by build_overrides;
                                     # do not apply as a direct module attr

    def resolve_default(self, module):
        return self.default(module) if callable(self.default) else self.default

    def attrs_for(self, value) -> dict:
        if self.to_attrs is not None:
            return self.to_attrs(value)
        return {self.key: value}


@dataclass
class ExampleSpec:
    key: str
    title: str
    description: str
    sim_module: str
    plot_module: str
    params: list[ParamSpec] = field(default_factory=list)
    # optional hook for CONFIGS-style modules: (values, module) -> attr dict
    build_overrides: Callable[[dict, Any], dict] | None = None

    def overrides(self, values: dict, module) -> dict:
        # direct params first (skip those consumed only by build_overrides),
        # then let build_overrides augment/override
        out = {}
        for p in self.params:
            if p.key in values and not p.override_only:
                out.update(p.attrs_for(values[p.key]))
        if self.build_overrides is not None:
            out.update(self.build_overrides(values, module))
        return out


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGS-rewrite helpers (R/C pairs must stay consistent with *_spice strings)
# ─────────────────────────────────────────────────────────────────────────────
def _rc_charging_overrides(values, module):
    configs = copy.deepcopy(module.CONFIGS)
    for i, cfg in enumerate(configs, start=1):
        r = values[f'R{i}']
        c = values[f'C{i}'] * 1e-12          # form is in pF
        cfg['R'], cfg['C'] = r, c
        cfg['R_spice'], cfg['C_spice'] = si_to_spice(r), si_to_spice(c)
        tau = r * c
        cfg['label'] = (f'R={si_to_spice(r)}, C={si_to_spice(c)}  '
                        f'(tau={si_to_spice(tau)}s)')
    return {'CONFIGS': configs}


def _rc_filter_overrides(values, module):
    configs = copy.deepcopy(module.CONFIGS)
    for i, cfg in enumerate(configs, start=1):
        r = values[f'R{i}']
        c = values[f'C{i}'] * 1e-12
        cfg['R'], cfg['C'] = r, c
        cfg['R_spice'], cfg['C_spice'] = si_to_spice(r), si_to_spice(c)
        cfg['label'] = f'R={si_to_spice(r)}Ohm, C={si_to_spice(c)}F'
    return {'CONFIGS': configs}


def _rc_pair_params(unit_r='Ohm', c_defaults=(1.0, 1.0), r_defaults=(1e3, 1e4)):
    out = []
    for i in (1, 2):
        out.append(ParamSpec(f'R{i}', f'R (config {i})', 'float', unit_r,
                             default=r_defaults[i - 1], minimum=1,
                             maximum=1e9, decimals=0, override_only=True))
        out.append(ParamSpec(f'C{i}', f'C (config {i})', 'float', 'pF',
                             default=c_defaults[i - 1], minimum=0.001,
                             maximum=1e6, decimals=3, override_only=True))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────
REGISTRY: dict[str, ExampleSpec] = {}


def _reg(spec: ExampleSpec):
    REGISTRY[spec.key] = spec


_reg(ExampleSpec(
    key='tran_rc_charging',
    title='1 · Tran — RC charging',
    description='RC charging voltage and current; two R/C configs.',
    sim_module='simulate_tran_rc_charging',
    plot_module='plot_tran_rc_charging',
    params=_rc_pair_params() + [
        ParamSpec('VIN', 'Input step Vin', 'float', 'V',
                  lambda m: m.VIN, 0.01, 10, 3, advanced=True),
    ],
    build_overrides=_rc_charging_overrides,
))

_reg(ExampleSpec(
    key='dc_nmos_iv',
    title='2 · DC — NMOS Id-Vds family',
    description='PTM 180nm NMOS output characteristics.',
    sim_module='simulate_dc_nmos_iv',
    plot_module='plot_dc_nmos_iv',
    params=[
        ParamSpec('W_UM', 'W', 'float', 'um', lambda m: m.W_UM, 0.1, 1000, 2),
        ParamSpec('L_UM', 'L', 'float', 'um', lambda m: m.L_UM, 0.018, 10, 3),
        ParamSpec('VGS_LIST', 'Vgs list', 'floatlist', 'V',
                  lambda m: list(m.VGS_LIST), 0, 1.8),
        ParamSpec('VDS_STOP', 'Vds sweep stop', 'float', 'V',
                  lambda m: m.VDS_STOP, 0.1, 5, 2, advanced=True),
        ParamSpec('VDS_STEP', 'Vds sweep step', 'float', 'V',
                  lambda m: m.VDS_STEP, 0.001, 0.5, 3, advanced=True),
    ],
))

_reg(ExampleSpec(
    key='ac_rc_filter',
    title='3+4 · AC/Noise — RC low-pass filter',
    description='Frequency response and output noise density.',
    sim_module='simulate_ac_rc_filter',
    plot_module='plot_ac_rc_filter',
    params=_rc_pair_params() + [
        ParamSpec('FREQ_START', 'Freq start', 'float', 'Hz',
                  lambda m: _spice_to_si(m.FREQ_START), 1, 1e12, 0,
                  to_attrs=lambda v: {'FREQ_START': si_to_spice(v)},
                  advanced=True),
        ParamSpec('FREQ_STOP', 'Freq stop', 'float', 'Hz',
                  lambda m: _spice_to_si(m.FREQ_STOP), 1, 1e12, 0,
                  to_attrs=lambda v: {'FREQ_STOP': si_to_spice(v)},
                  advanced=True),
    ],
    build_overrides=_rc_filter_overrides,
))

def _sample_hold_overrides(values, module):
    # SIMS[0]'s label bakes in W_UM at import time — refresh it too.
    sims = copy.deepcopy(module.SIMS)
    sims[0]['label'] = (f"180 nm NMOS  (W={values['W_UM']}um, Ron~400 Ohm)")
    return {'W_UM': values['W_UM'], 'L_UM': values['L_UM'], 'SIMS': sims}


_reg(ExampleSpec(
    key='tran_sample_hold',
    title='5 · Tran — sample-and-hold switches',
    description='180nm NMOS switch vs ideal switch.',
    sim_module='simulate_tran_sample_hold',
    plot_module='plot_tran_sample_hold',
    params=[
        ParamSpec('W_UM', 'Switch W', 'float', 'um',
                  lambda m: m.W_UM, 0.2, 100, 2),
        ParamSpec('L_UM', 'Switch L', 'float', 'um',
                  lambda m: m.L_UM, 0.18, 10, 3),
        ParamSpec('VDD', 'VDD', 'float', 'V', lambda m: m.VDD, 0.3, 5, 2,
                  advanced=True),
        ParamSpec('RON_IDEAL', 'Ideal switch Ron', 'float', 'Ohm',
                  lambda m: m.RON_IDEAL, 1, 10000, 0, advanced=True),
        ParamSpec('CSAMP', 'Sample cap', 'float', 'F',
                  lambda m: _spice_to_si(m.CSAMP), 1e-15, 1e-9, 15,
                  to_attrs=lambda v: {'CSAMP': si_to_spice(v)}, advanced=True),
        ParamSpec('FIN', 'Input freq', 'float', 'Hz',
                  lambda m: _spice_to_si(m.FIN), 1e3, 1e10, 0,
                  to_attrs=lambda v: {'FIN': si_to_spice(v)}, advanced=True),
        ParamSpec('FCLK', 'Clock freq', 'float', 'Hz',
                  lambda m: _spice_to_si(m.FCLK), 1e3, 1e10, 0,
                  to_attrs=lambda v: {'FCLK': si_to_spice(v)}, advanced=True),
        ParamSpec('TSTOP', 'Sim stop time', 'float', 's',
                  lambda m: _spice_to_si(m.TSTOP), 1e-9, 1e-3, 12,
                  to_attrs=lambda v: {'TSTOP': si_to_spice(v)}, advanced=True),
    ],
    build_overrides=_sample_hold_overrides,
))

def _ktc_caps_override(values, module):
    caps_ff = values.get('CAPS_FF')
    if not caps_ff:
        return {}
    configs = []
    for c_ff in caps_ff:
        c_si = c_ff * 1e-15
        cval = si_to_spice(c_si)
        configs.append({
            'label':  f'C = {cval}',
            'C_val':  cval,
            'C_si':   c_si,
            'color':  None,          # plot module assigns if None-safe; keep key
            'log':    module.LOG_DIR / f'tran_ktc_{cval}.log',
            'wrdata': module.LOG_DIR / f'tran_ktc_{cval}.txt',
        })
    # preserve original colors where possible
    for i, cfg in enumerate(configs):
        cfg['color'] = module.CONFIGS[i % len(module.CONFIGS)]['color']
    return {'CONFIGS': configs}


_reg(ExampleSpec(
    key='tran_ktc_noise',
    title='6 · Tran — kT/C noise statistics',
    description='Time-domain sampling of kT/C noise; histogram + Gaussian fit.',
    sim_module='simulate_tran_ktc_noise',
    plot_module='plot_tran_ktc_noise',
    params=[
        ParamSpec('N_SAMPLES', 'Samples', 'int', '',
                  lambda m: m.N_SAMPLES, 100, 100000),
        ParamSpec('T', 'Temperature', 'float', 'K',
                  lambda m: m.T, 4, 500, 1, advanced=True),
        ParamSpec('VDC', 'DC input', 'float', 'V',
                  lambda m: m.VDC, 0, 5, 3, advanced=True),
        ParamSpec('TAU_TARGET_PS', 'RC tau', 'float', 'ps',
                  lambda m: m.TAU_TARGET * 1e12, 1, 10000, 1,
                  to_attrs=lambda v: {'TAU_TARGET': v * 1e-12}, advanced=True),
        ParamSpec('CAPS_FF', 'Sample caps', 'floatlist', 'fF',
                  lambda m: [c['C_si'] * 1e15 for c in m.CONFIGS],
                  advanced=True, override_only=True),
    ],
    build_overrides=_ktc_caps_override,
))

_reg(ExampleSpec(
    key='dc_current_mirror',
    title='7 · DC — NMOS current mirror',
    description='1:1 mirror output characteristics, Iout vs Vout.',
    sim_module='simulate_dc_current_mirror',
    plot_module='plot_dc_current_mirror',
    params=[
        ParamSpec('W_UM', 'W', 'float', 'um', lambda m: m.W_UM, 0.5, 500, 2),
        ParamSpec('L_UM', 'L', 'float', 'um', lambda m: m.L_UM, 0.18, 10, 3),
        ParamSpec('IREF_UA', 'Iref', 'float', 'uA', 100.0, 1, 10000, 1,
                  to_attrs=lambda v: {'IREF': si_to_spice(v * 1e-6),
                                      'IREF_SI': v * 1e-6}),
        ParamSpec('VDD', 'VDD', 'float', 'V', lambda m: m.VDD, 0.3, 5, 2,
                  advanced=True),
        ParamSpec('VOUT_STOP', 'Vout sweep stop', 'float', 'V',
                  lambda m: m.VOUT_STOP, 0.1, 5, 2, advanced=True),
        ParamSpec('VOUT_STEP', 'Vout sweep step', 'float', 'V',
                  lambda m: m.VOUT_STEP, 0.001, 0.5, 3, advanced=True),
    ],
))

_reg(ExampleSpec(
    key='ac_cs_amp',
    title='8 · AC — common-source amplifier',
    description='Bode magnitude/phase of a resistive-load CS stage.',
    sim_module='simulate_ac_cs_amp',
    plot_module='plot_ac_cs_amp',
    params=[
        ParamSpec('W_UM', 'W', 'float', 'um', lambda m: m.W_UM, 0.5, 500, 2),
        ParamSpec('L_UM', 'L', 'float', 'um', lambda m: m.L_UM, 0.18, 10, 3),
        ParamSpec('VGS_BIAS', 'Vgs bias', 'float', 'V',
                  lambda m: m.VGS_BIAS, 0.3, 1.8),
        ParamSpec('RD_K', 'Rd', 'float', 'kOhm', 2.0, 0.05, 1000, 2,
                  to_attrs=lambda v: {'RD': si_to_spice(v * 1e3),
                                      'RD_SI': v * 1e3}),
        ParamSpec('CL_PF', 'CL', 'float', 'pF', 1.0, 0.01, 1000, 2,
                  to_attrs=lambda v: {'CL': si_to_spice(v * 1e-12),
                                      'CL_SI': v * 1e-12}),
        ParamSpec('VDD', 'VDD', 'float', 'V', lambda m: m.VDD, 0.3, 5, 2,
                  advanced=True),
        ParamSpec('FREQ_START', 'Freq start', 'float', 'Hz',
                  lambda m: _spice_to_si(m.FREQ_START), 1, 1e12, 0,
                  to_attrs=lambda v: {'FREQ_START': si_to_spice(v)},
                  advanced=True),
        ParamSpec('FREQ_STOP', 'Freq stop', 'float', 'Hz',
                  lambda m: _spice_to_si(m.FREQ_STOP), 1, 1e12, 0,
                  to_attrs=lambda v: {'FREQ_STOP': si_to_spice(v)},
                  advanced=True),
    ],
))

_reg(ExampleSpec(
    key='dc_tgate_ron',
    title='9 · DC — transmission-gate Ron',
    description='On-resistance vs pass voltage across 180/45/22nm nodes.',
    sim_module='simulate_dc_tgate_ron',
    plot_module='plot_dc_tgate_ron',
    params=[
        ParamSpec('WL_RATIO', 'W/L ratio', 'int', '',
                  lambda m: m.WL_RATIO, 1, 10000),
        ParamSpec('DELTA_V', 'Test voltage', 'float', 'V',
                  lambda m: m.DELTA_V, 0.001, 0.1, 3, advanced=True),
    ],
))


# ─────────────────────────────────────────────────────────────────────────────
# Runner (executed inside the SimWorker thread)
# ─────────────────────────────────────────────────────────────────────────────
@contextmanager
def patched(module, overrides: dict):
    saved = {k: getattr(module, k) for k in overrides}
    try:
        for k, v in overrides.items():
            setattr(module, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(module, k, v)


def run_example(key: str, values: dict) -> list[Path]:
    """Import, patch, simulate, plot; return the produced PNG paths."""
    spec = REGISTRY[key]
    sim = importlib.import_module(spec.sim_module)
    plot = importlib.import_module(spec.plot_module)
    overrides = spec.overrides(values, sim)
    with patched(sim, overrides):
        results = sim.simulate_all()
    plot.plot_all(results)
    return [Path(plot.OUT_PNG)]


def example_log_dir() -> Path:
    from ngspice_common import LOG_DIR
    return Path(LOG_DIR)

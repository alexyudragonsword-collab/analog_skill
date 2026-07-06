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
        if self.build_overrides is not None:
            return self.build_overrides(values, module)
        out = {}
        for p in self.params:
            if p.key in values:
                out.update(p.attrs_for(values[p.key]))
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
                             maximum=1e9, decimals=0))
        out.append(ParamSpec(f'C{i}', f'C (config {i})', 'float', 'pF',
                             default=c_defaults[i - 1], minimum=0.001,
                             maximum=1e6, decimals=3))
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
    params=_rc_pair_params(),
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
    ],
))

_reg(ExampleSpec(
    key='ac_rc_filter',
    title='3+4 · AC/Noise — RC low-pass filter',
    description='Frequency response and output noise density.',
    sim_module='simulate_ac_rc_filter',
    plot_module='plot_ac_rc_filter',
    params=_rc_pair_params(),
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
    ],
    build_overrides=_sample_hold_overrides,
))

_reg(ExampleSpec(
    key='tran_ktc_noise',
    title='6 · Tran — kT/C noise statistics',
    description='Time-domain sampling of kT/C noise; histogram + Gaussian fit.',
    sim_module='simulate_tran_ktc_noise',
    plot_module='plot_tran_ktc_noise',
    params=[
        ParamSpec('N_SAMPLES', 'Samples', 'int', '',
                  lambda m: m.N_SAMPLES, 100, 100000),
    ],
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

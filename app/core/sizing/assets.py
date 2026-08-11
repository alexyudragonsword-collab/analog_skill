"""Locating and parsing a circuit's design files.

Where a circuit's netlist / .PARAM / testbench / schematic live (the
vendored AnalogGym tree, the studio tree, or the user-data store), and how
a .PARAM file becomes the design-variable table the GUI edits.
"""

import os
import re
from pathlib import Path

from app import paths
from app.core.sizing.registry import SIZING
from app.core.sizing.spec import SizingSpec, VarSpec, _parse_num


def _user_data_root() -> Path:
    """Root for data the *user* created (saved runs, imported circuits).

    init_runtime() points ANALOG_USER_DATA_DIR at a location outside the
    versioned workspace, so an app upgrade — which wipes old workspaces —
    cannot delete it.  The ANALOG_WORK_DIR fallback keeps tests and any
    caller that sets only the work dir self-contained.
    """
    d = os.environ.get('ANALOG_USER_DATA_DIR') \
        or os.environ.get('ANALOG_WORK_DIR')
    return Path(d) if d else Path.home() / '.analog_studio'


def user_circuits_dir() -> Path:
    """Writable tree for user-imported circuits — same
    <root>/amp/{netlist,variables,testbench} layout as analoggym/studio,
    persisted like runs_dir()."""
    d = _user_data_root() / 'user_circuits'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pkg_root(spec: SizingSpec) -> Path:
    """Asset tree for a netlist/variables/testbench circuit: the vendored
    AnalogGym subset, the original studio_circuits tree, or the workspace
    user_circuits tree (all share <root>/<kind>/{netlist,variables,
    testbench})."""
    if spec.pkg == 'studio':
        return paths.studio_circuits_dir()
    if spec.pkg == 'user':
        return user_circuits_dir()
    return paths.analoggym_dir()


def _variables_path(spec: SizingSpec) -> Path:
    return (_pkg_root(spec) / spec.kind / 'variables' / spec.variables)


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


def parse_param_file(path: Path) -> dict[str, float]:
    """`name = value` / .PARAM file -> {name: float}; expression-valued
    entries (W_M2=W_M1) are skipped, same as parse_variables."""
    out = {}
    for name, value in re.findall(r'([A-Za-z_][\w]*)\s*=\s*([^\s]+)',
                                  Path(path).read_text(errors='replace')):
        try:
            out[name] = _parse_num(value)
        except ValueError:
            continue
    return out


def schematic_path(circuit: str) -> Path | None:
    spec = SIZING[circuit]
    if spec.kind == 'skill':
        from app.core import circuits
        return circuits.schematic_path(spec.skill_key)
    # schemdraw redraws (tools/gen_sizing_schematics.py) take precedence —
    # the vendored AnalogGym PNGs are low-res screenshots and stay untouched
    p = paths.resources_dir() / 'schematics' / 'sizing' / f'{circuit}.png'
    if p.is_file():
        return p
    if not spec.schematic:
        return None
    p = _pkg_root(spec) / spec.kind / 'schematic' / spec.schematic
    return p if p.is_file() else None

"""Importing the user's own amplifier designs.

A netlist following the AnalogGym amp contract plus its .PARAM file is
copied into the version-independent user-data store and registered in
``SIZING``, after which it gets the same pipeline as a built-in circuit.
"""

import re
from pathlib import Path

from app import paths
from app.core.sizing.assets import parse_param_file, user_circuits_dir
from app.core.sizing.registry import SIZING, _amp_metrics
from app.core.sizing.spec import SizingSpec


#: The captured name becomes a *filename* (user_circuits/amp/netlist/<name>)
#: and part of a registry key, so it is restricted to a SPICE-identifier
#: charset — `\S+` would happily match "../../../evil" and let a crafted
#: netlist write outside the workspace.
_USER_SUBCKT = re.compile(
    r'(?im)^\s*\.subckt\s+([A-Za-z_][A-Za-z0-9_]*)'
    r'\s+gnda\s+vdda\s+vinn\s+vinp\s+vout\b')


def _register_user_circuit(subckt: str) -> str:
    key = f'user_{subckt.lower()}'
    SIZING[key] = SizingSpec(
        title=f'{subckt} — user import (SKY130, 1.8 V)',
        kind='amp', netlist=subckt, variables=subckt,
        testbench='TB_Amplifier_ACDC.cir', metrics=_amp_metrics(),
        fixed=('CLOAD', 'VCM'), eval_seconds=3.5,
        subckt=subckt, pkg='user')
    return key


def import_user_circuit(netlist_path: Path, vars_path: Path) -> str:
    """Copy a user's amp design into the workspace and register it.

    The netlist must follow the AnalogGym amplifier contract the shared
    testbench is written against:
        .subckt <name> gnda vdda vinn vinp vout
    on SKY130 devices, self-biased (no extra bias pins).  vars_path is the
    matching .PARAM design-variables file.  Returns the new circuit key.
    """
    import shutil
    text = Path(netlist_path).read_text(errors='replace')
    m = _USER_SUBCKT.search(text)
    if not m:
        raise ValueError(
            'netlist does not match the amplifier contract — it must '
            'declare ".subckt <name> gnda vdda vinn vinp vout" (SKY130, '
            'self-biased; see the AnalogGym amp netlists for examples)')
    subckt = m.group(1)
    # belt-and-braces: the regex already constrains the charset, but this is
    # the point where the name turns into a path — never let it escape.
    if subckt != Path(subckt).name or subckt in ('.', '..'):
        raise ValueError(f'invalid subcircuit name: {subckt!r}')
    key = f'user_{subckt.lower()}'
    if key in SIZING:
        raise ValueError(f'a circuit named {subckt} is already imported — '
                         'remove it first (Netlist… dialog)')
    if not parse_param_file(vars_path):
        raise ValueError('the design-variables file contains no '
                         'name=value parameters')
    root = user_circuits_dir() / 'amp'
    for sub in ('netlist', 'variables', 'testbench'):
        (root / sub).mkdir(parents=True, exist_ok=True)
    shutil.copy(netlist_path, root / 'netlist' / subckt)
    shutil.copy(vars_path, root / 'variables' / subckt)
    tb = root / 'testbench' / 'TB_Amplifier_ACDC.cir'
    if not tb.is_file():        # shared harness, copied once (studio-style)
        shutil.copy(paths.analoggym_dir() / 'amp' / 'testbench'
                    / 'TB_Amplifier_ACDC.cir', tb)
    return _register_user_circuit(subckt)


def load_user_circuits() -> list[str]:
    """(Re-)register every circuit found in the workspace user_circuits
    tree — called at GUI start so imports persist across sessions."""
    nl = user_circuits_dir() / 'amp' / 'netlist'
    keys = []
    if nl.is_dir():
        for p in sorted(nl.iterdir()):
            if p.is_file() and f'user_{p.name.lower()}' not in SIZING:
                keys.append(_register_user_circuit(p.name))
    return keys


def remove_user_circuit(key: str):
    """Unregister an imported circuit and delete its workspace files."""
    spec = SIZING.get(key)
    if spec is None or spec.pkg != 'user':
        raise ValueError(f'{key} is not a user-imported circuit')
    root = user_circuits_dir() / 'amp'
    for sub in ('netlist', 'variables'):
        f = root / sub / spec.netlist
        if f.is_file():
            f.unlink()
    del SIZING[key]

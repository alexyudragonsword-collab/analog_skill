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

#: Directives an imported file must not carry.  Two distinct problems:
#:
#: * ngspice runs `.control ... .endc` blocks in batch mode, and a control
#:   block may call `shell` — so an imported design carrying one would run
#:   arbitrary commands on the very first evaluation while every metric
#:   still came back looking normal.
#: * `.include` / `.inc` / `.lib` make ngspice read another file into the
#:   simulation.  That is far weaker than shell execution (the deck usually
#:   fails to parse), but the contents reach the run log the user sees —
#:   `.include /etc/hostname` comes back as `Error in line   <contents>` —
#:   so an imported design can read any file its reader can.
#:
#: Both matter because the netlist *and* the design-variables file are
#: `.include`d verbatim into the rendered testbench (see
#: evaluation._render_testbench and _write_params), and a directive inside
#: an included file behaves exactly as if it were inline.
#:
#: The amplifier contract is a plain `.subckt` needing no includes at all,
#: and none of the 27 shipped circuits uses either kind (the vendored
#: *testbenches* do include the netlist, the variables and the SKY130
#: corner — but those are ours, not user input).  Measured against
#: ngspice-42: every form folds case and tolerates leading space or tab,
#: and `.include` takes its path bare or in either quote style, but
#: splitting a directive across a `+` continuation does not work — so
#: matching at line start catches every form that actually acts.
_UNSAFE_DIRECTIVE = re.compile(
    r'(?im)^[ \t]*(\.(?:control|include|inc|lib))\b')

_WHY_INCLUDE = ('ngspice would read that file into the simulation, and its '
                'contents can surface in the run log — an imported design '
                'can use that to read any file you can read')
_WHY = {
    '.control': ('ngspice executes those, so importing this design could '
                 'run arbitrary commands on your machine'),
    '.include': _WHY_INCLUDE,
    '.inc': _WHY_INCLUDE,
    '.lib': _WHY_INCLUDE,
}


def _reject_unsafe_directives(text: str, path: Path, role: str):
    """Raise ValueError if `text` carries a directive ngspice would act on."""
    m = _UNSAFE_DIRECTIVE.search(text)
    if m is None:
        return
    directive = m.group(1).lower()
    line = text.count('\n', 0, m.start()) + 1
    raise ValueError(
        f'{role} "{Path(path).name}" contains a "{directive}" directive '
        f'(line {line}). {_WHY[directive]}. The amplifier contract is a '
        f'plain .subckt — remove it first.')


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
    _reject_unsafe_directives(text, netlist_path, 'netlist')
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
    _reject_unsafe_directives(Path(vars_path).read_text(errors='replace'),
                          vars_path, 'design-variables file')
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
    tree — called at GUI start so imports persist across sessions.

    Files on disk are re-checked for unsafe directives rather than
    trusted: a design imported before that check existed, or dropped into
    the store by hand, must not become runnable just because it is
    already there.
    An unsafe file is skipped with a message and left in place for the
    user to inspect — deleting someone's netlist behind their back would
    be worse than leaving it unregistered.
    """
    root = user_circuits_dir() / 'amp'
    nl = root / 'netlist'
    keys = []
    if nl.is_dir():
        for p in sorted(nl.iterdir()):
            if not p.is_file() or f'user_{p.name.lower()}' in SIZING:
                continue
            try:
                for path, role in ((p, 'netlist'),
                                   (root / 'variables' / p.name,
                                    'design-variables file')):
                    if path.is_file():
                        _reject_unsafe_directives(
                            path.read_text(errors='replace'), path, role)
            except ValueError as exc:
                print(f'skipping user circuit {p.name}: {exc}')
                continue
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

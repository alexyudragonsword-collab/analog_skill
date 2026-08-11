"""Plain data shared by the whole sizing package.

The circuit / metric / design-variable specs and the SPICE number parsing
they use.  Depends on nothing but the standard library, so every other
module here can import it without worrying about ordering.
"""

import re
from dataclasses import dataclass, field


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


@dataclass
class VarSpec:
    name: str
    default: float
    lo: float
    hi: float
    is_int: bool

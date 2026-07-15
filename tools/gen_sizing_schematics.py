#!/usr/bin/env python3
"""Redraw the Sizing-tab schematics with schemdraw, device-by-device from
the AnalogGym netlists.

The vendored AnalogGym schematic PNGs are low-res screenshots (and the
Alfio amp + all five LDOs ship none at all); these drawings replace them
in the GUI via app/core/sizing.py::schematic_path(), which prefers
app/resources/schematics/sizing/<circuit_key>.png over the vendored file.
The vendored tree itself stays untouched (repo policy: archived as-is).

Fidelity is enforced programmatically: every drawing registers the netlist
device names it draws; after drawing, the generator parses the real
netlist and errors out on any missing or unknown device.

Drawing conventions (dense 20-40 device sheets):
- bias voltages (net013 / VB3 / VB4 ...) are distributed as LABELLED GATE
  STUBS, not routed buses — textbook style, keeps 6+ mirror legs readable;
- one MOS symbol per xm line, M multipliers noted in the device label;
- PMOS anchored at source on the VDDA rail row, NMOS anchored at drain;
  signal wiring is fully drawn (stages, mirrors, cascodes, comp caps).

Regenerate with:  python tools/gen_sizing_schematics.py [--only KEY]
(schemdraw is a dev-only dependency; the app ships the PNGs.)
"""

import argparse
import re
import sys
from pathlib import Path

import schemdraw
import schemdraw.elements as elm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_schematics import (          # noqa: E402  (shared style/primitives)
    FET_H, NODE, TINTS, dot, drawing, nmos, node_label, pmos, port, rail,
    tint, title, wire,
)

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / 'app' / 'resources' / 'schematics' / 'sizing'
AMP_NL = REPO / 'analoggym' / 'amp' / 'netlist'
LDO_NL = REPO / 'analoggym' / 'ldo' / 'netlist'

_DEV = re.compile(r'(?im)^\s*(x?[mcri][\w]*)\s')

# shared row geometry (VDD rail at 10, GND at 0)
Y_VDD, Y_GND = 10.0, 0.0
Y_PD = Y_VDD - FET_H              # PMOS drain row            8.33
Y_SRC = 8.0                       # diff-pair source bus
Y_PR2 = Y_SRC                     # second PMOS row (stacked pairs)
Y_PD2 = Y_SRC - FET_H             # diff-pair drain row       6.33
Y_CT = 5.0                        # cascode top drain row
Y_CM = Y_CT - FET_H               # cascode mid junction      3.33
Y_ND = Y_CM                       # single-NMOS drain row     3.33
Y_NS = Y_ND - FET_H               # NMOS source row           1.67


def netlist_devices(path: Path) -> set[str]:
    """Every drawable device name in a netlist (xm*/c*/r*/i*, lowercase)."""
    return {m.group(1).lower()
            for m in _DEV.finditer(path.read_text(errors='replace'))}


class Sheet:
    """One drawing + the set of netlist devices it claims to have drawn."""

    def __init__(self, netlist: Path):
        self.d = drawing()
        self.netlist = netlist
        self.drawn: set[str] = set()

    def pfet(self, name, x, label=None, left=False, bias=None, y=Y_VDD):
        """PMOS with source on the VDD rail row (or y); optional labelled
        bias-gate stub (e.g. 'net013')."""
        self.drawn.add(name.lower())
        e = pmos(self.d, (x, y), label or name.upper(), '', left=left)
        if bias:
            self._bias_stub(e, bias, left)
        return e

    def nfet(self, name, x, y, label=None, left=False, bias=None,
             to_gnd=False):
        self.drawn.add(name.lower())
        e = nmos(self.d, (x, y), label or name.upper(), '', left=left)
        if to_gnd:
            s = e.absanchors['source']
            wire(self.d, s, (s.x, Y_GND))
        if bias:
            self._bias_stub(e, bias, left)
        return e

    def _bias_stub(self, e, bias_name, left):
        g = e.absanchors['gate']
        dx = -0.35 if left else 0.35
        wire(self.d, (g.x, g.y), (g.x + dx, g.y))
        node_label(self.d, (g.x + dx, g.y - 0.32), bias_name,
                   halign='right' if left else 'left')

    def diode_tie(self, e, col_x):
        """Gate-to-drain tie for a mirror reference (dot on the channel
        column at gate height — reads as the standard diode connection)."""
        g = e.absanchors['gate']
        wire(self.d, (g.x, g.y), (col_x, g.y))
        dot(self.d, (col_x, g.y))

    def cap(self, name, a, b, label=None, loc='top'):
        self.drawn.add(name.lower())
        self.d.add(elm.Capacitor().at(a).to(b)
                   .label(label or name.upper(), fontsize=8, loc=loc))

    def res(self, name, a, b, label=None, loc='top'):
        self.drawn.add(name.lower())
        self.d.add(elm.Resistor().at(a).to(b)
                   .label(label or name.upper(), fontsize=8, loc=loc))

    def isrc(self, name, x, y_top, y_bot, label=None):
        self.drawn.add(name.lower())
        self.d.add(elm.SourceI().at((x, y_top)).theta(-90)
                   .length(y_top - y_bot)
                   .label(label or name.upper(), fontsize=8, loc='bot'))

    def check(self):
        real = netlist_devices(self.netlist)
        missing = sorted(real - self.drawn)
        extra = sorted(self.drawn - real)
        if missing or extra:
            raise SystemExit(f'{self.netlist.name}: '
                             f'missing={missing} extra={extra}')

    def save(self, key: str):
        self.check()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f'{key}.png'
        self.d.save(str(out), dpi=200, transparent=False)
        print(f'  saved {out.relative_to(REPO)}')


# ─────────────────────────────────────────────────────────────────────────────
# building blocks shared by the NMC-family amps
# ─────────────────────────────────────────────────────────────────────────────
def bias_column(sh, x, iname='i0'):
    """Iref sink + PMOS diode reference (net013)."""
    m = sh.pfet('xm0', x, 'M0')
    g = m.absanchors['gate']
    wire(sh.d, m.absanchors['drain'], (x, g.y))
    sh.diode_tie(m, x)
    node_label(sh.d, (x - 0.25, g.y - 0.4), 'net013', halign='right')
    sh.isrc(iname, x, g.y - 0.55, Y_GND, 'I0')
    wire(sh.d, (x, g.y), (x, g.y - 0.55))


def vb_gen(sh, x, top_leg, top_lbl, names, labels):
    """PMOS leg feeding a stacked NMOS pair that generates VB3/VB4
    (m_top gate=VB3, m_bot gate=VB4 -> node VB4 at the top drain)."""
    sh.pfet(top_leg, x, top_lbl, bias='net013')
    wire(sh.d, (x, Y_PD), (x, Y_CT))
    t = sh.nfet(names[0], x, Y_CT, labels[0], left=True, bias='VB3')
    sh.nfet(names[1], x, Y_CM, labels[1], left=True, bias='VB4',
            to_gnd=True)
    node_label(sh.d, (x + 0.15, Y_CT + 0.9), 'VB4')
    return t


def vb3_diode(sh, x, top_leg, top_lbl, name, label):
    """PMOS leg over an NMOS diode -> VB3 reference."""
    sh.pfet(top_leg, x, top_lbl, bias='net013')
    wire(sh.d, (x, Y_PD), (x, Y_ND))
    e = sh.nfet(name, x, Y_ND, label, left=True, to_gnd=True)
    sh.diode_tie(e, x)
    node_label(sh.d, (x + 0.15, Y_ND + 0.9), 'VB3')


def replica_column(sh, x, top_leg, top_lbl, names, labels, node='DM_1'):
    """PMOS leg over a cascode NMOS sink (replica/dummy branch)."""
    sh.pfet(top_leg, x, top_lbl, bias='net013')
    wire(sh.d, (x, Y_PD), (x, Y_CT))
    sh.nfet(names[0], x, Y_CT, labels[0], bias='VB3')
    sh.nfet(names[1], x, Y_CM, labels[1], bias='VB4', to_gnd=True)
    node_label(sh.d, (x + 0.15, Y_CT + 0.9), node)


def diff_pair(sh, xt, xl, xr, tail, tail_lbl, pl, pl_lbl, pr, pr_lbl,
              inn='VINN', inp='VINP'):
    """PMOS tail + PMOS input pair on a shared source bus; returns the
    (left, right) drain points at Y_PD2."""
    sh.pfet(tail, xt, tail_lbl, bias='net013')
    wire(sh.d, (xt, Y_PD), (xt, Y_SRC))
    wire(sh.d, (xl, Y_SRC), (xr, Y_SRC))
    dot(sh.d, (xt, Y_SRC))
    l = sh.pfet(pl, xl, pl_lbl, left=True, y=Y_SRC)
    r = sh.pfet(pr, xr, pr_lbl, y=Y_SRC)
    gl, gr = l.absanchors['gate'], r.absanchors['gate']
    wire(sh.d, (gl.x, gl.y), (gl.x - 0.7, gl.y))
    port(sh.d, (gl.x - 0.7, gl.y), inn)
    wire(sh.d, (gr.x, gr.y), (gr.x + 0.7, gr.y))
    port(sh.d, (gr.x + 0.7, gr.y), inp, 'right')
    return (xl, Y_PD2), (xr, Y_PD2)


def gate_feed(sh, tap, gx, gy, tap_y=None):
    """Route a signal node to a gate: tap -> horizontal -> vertical -> gate."""
    tx, ty = tap
    tap_y = ty if tap_y is None else tap_y
    wire(sh.d, (tx, ty), (tx, tap_y)) if tap_y != ty else None
    wire(sh.d, (tx, tap_y), (gx, tap_y))
    if abs(gy - tap_y) > 1e-9:
        wire(sh.d, (gx, tap_y), (gx, gy))
    dot(sh.d, (tx, ty)) if tap_y == ty else dot(sh.d, (tx, tap_y))


# per-circuit drawings live in tools/sizing_drawings/<key>.py, each
# exporting KEY and draw(); discovered automatically so parallel authors
# never touch this hub file.
def _discover():
    import importlib
    out = {}
    pkg_dir = Path(__file__).resolve().parent / 'sizing_drawings'
    sys.path.insert(0, str(pkg_dir))
    for p in sorted(pkg_dir.glob('*.py')):
        mod = importlib.import_module(p.stem)
        out[mod.KEY] = mod.draw
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only')
    args = ap.parse_args()
    drawers = _discover()
    keys = [args.only] if args.only else list(drawers)
    for k in keys:
        print(f'rendering {k} ...')
        drawers[k]()


if __name__ == '__main__':
    main()

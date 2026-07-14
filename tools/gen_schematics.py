#!/usr/bin/env python3
"""Pre-render the Circuits-tab schematics with schemdraw.

The five drawings follow the vendored DUT netlists in circuit-skills/
device-by-device (names, connectivity and default sizes match the
``*.cir.tmpl`` templates).  Output: app/resources/schematics/<key>.png,
where <key> matches app.core.circuits.CIRCUITS.

Regenerate with:  python tools/gen_schematics.py [--only KEY]
(schemdraw is a dev-only dependency; the app ships the PNGs.)

Geometry notes (schemdraw 0.23, AnalogNFet/PFet, offset_gate=False):
  NFet anchored at 'drain': drain top, source 1.67 below, gate mid-height
  0.92 to the RIGHT; PFet anchored at 'source': source top, drain below.
  ``.reverse()`` mirrors horizontally (gate to the LEFT); ``.flip()``
  mirrors vertically — never use it for left/right symmetry.
"""

import argparse
from pathlib import Path

import schemdraw
import schemdraw.elements as elm

OUT_DIR = Path(__file__).resolve().parent.parent / 'app' / 'resources' / 'schematics'
# studio_circuits Sizing entries keep their schematic next to the netlist,
# matching the AnalogGym amp layout (<tree>/amp/schematic/<name>.png)
STUDIO_SCH_DIR = (Path(__file__).resolve().parent.parent
                  / 'studio_circuits' / 'amp' / 'schematic')

INK = '#1c2833'
NODE = '#5d6d7e'
TINTS = {
    'input':  '#e8f1fb',
    'mirror': '#eaf7ec',
    'bias':   '#fdf3e3',
    'latch':  '#fbeaea',
    'comp':   '#f3ecfa',
    'out':    '#eef7f9',
}
GATE_DX = 0.92      # gate anchor x-offset from the channel column
FET_H = 1.67        # drain→source vertical extent


def drawing():
    d = schemdraw.Drawing(show=False)
    d.config(fontsize=10, lw=1.6, color=INK)
    return d


def tint(d, x1, y1, x2, y2, color, label=None, label_at='bottom',
         label_xy=None, label_align='left'):
    """Tinted background box; caption sits inside the box corner so it never
    collides with the rails.  label_xy overrides the caption position."""
    d += elm.Rect(corner1=(x1, y1), corner2=(x2, y2), fill=color, lw=0)
    if label:
        if label_xy is not None:
            xy, va = label_xy, 'center'
        elif label_at == 'top':
            xy, va = (x1 + 0.18, y2 - 0.12), 'top'
        else:
            xy, va = (x1 + 0.18, y1 + 0.12), 'bottom'
        d += (elm.Label().at(xy)
              .label(label, fontsize=8.5, color='#85929e',
                     halign=label_align, valign=va))


def _fet_label(d, top, name, size, left, label_at):
    if label_at is not None:
        x, y, ha = label_at
    else:
        x = top[0] + (0.55 if left else -0.55)
        y = top[1] - FET_H / 2
        ha = 'left' if left else 'right'
    d += (elm.Label().at((x, y))
          .label(f'{name}\n{size}', fontsize=8.5, halign=ha))


def nmos(d, drain, name, size, left=False, label_at=None):
    """NFet with drain at `drain`; gate faces right unless left=True.
    theta(0) pins the orientation (elements otherwise inherit the current
    drawing direction of the previous wire).  label_at=(x, y, halign)
    overrides the default name/size label placement."""
    f = elm.AnalogNFet(offset_gate=False).theta(0)
    if left:
        f = f.reverse()
    e = d.add(f.anchor('drain').at(drain))
    _fet_label(d, drain, name, size, left, label_at)
    return e


def pmos(d, source, name, size, left=False, label_at=None):
    """PFet with source at `source`; gate faces right unless left=True."""
    f = elm.AnalogPFet(offset_gate=False).theta(0)
    if left:
        f = f.reverse()
    e = d.add(f.anchor('source').at(source))
    _fet_label(d, source, name, size, left, label_at)
    return e


def wire(d, *pts):
    for a, b in zip(pts, pts[1:]):
        d += elm.Line().at(a).to(b)


def dot(d, xy):
    d += elm.Dot(radius=0.06).at(xy)


def port(d, xy, name, side='left'):
    d += elm.Dot(open=True, radius=0.09).at(xy)
    off = -0.22 if side == 'left' else 0.22
    d += (elm.Label().at((xy[0] + off, xy[1]))
          .label(name, fontsize=10, halign='right' if side == 'left' else 'left',
                 valign='center', color=INK))


def node_label(d, xy, text, halign='left'):
    d += elm.Label().at(xy).label(text, fontsize=8, color=NODE, halign=halign)


def rail(d, x1, x2, y, name, label_side='left'):
    wire(d, (x1, y), (x2, y))
    if label_side == 'left':
        d += elm.Label().at((x1 - 0.15, y)).label(name, halign='right',
                                                  fontsize=10)
    else:
        d += elm.Label().at((x2 + 0.15, y)).label(name, halign='left',
                                                  fontsize=10)


def title(d, x, y, text):
    d += elm.Label().at((x, y)).label(text, fontsize=12.5, halign='center')


def save(d, key):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f'{key}.png'
    d.save(str(path), dpi=200, transparent=False)
    print(f'  saved {path.name}')


# ─────────────────────────────────────────────────────────────────────────────
# 1) Five-transistor OTA
# ─────────────────────────────────────────────────────────────────────────────
def draw_ota5t():
    d = drawing()
    XL, XR = 0.0, 4.6
    XT = (XL + XR) / 2
    Y_VDD, Y_VSS = 8.0, 0.0
    Y_PD = Y_VDD - FET_H            # PMOS drains
    Y_ND = 4.6                      # NMOS diff-pair drains
    Y_NETD = Y_ND + 0.55            # NETD / OUT junction row
    Y_TAILD = 2.1                   # tail drain

    tint(d, XL - 2.2, Y_ND - FET_H - 0.45, XR + 2.2, Y_NETD + 0.02,
         TINTS['input'], 'input pair')
    tint(d, XL - 2.2, Y_PD - 0.5, XR + 2.2, Y_VDD - 0.15,
         TINTS['mirror'], 'current-mirror load',
         label_xy=(XT, Y_PD + 0.35), label_align='center')
    tint(d, XT - 2.7, Y_VSS + 0.15, XT + 2.7, Y_TAILD + 0.5,
         TINTS['bias'], 'tail current source')

    rail(d, XL - 2.8, XR + 2.8, Y_VDD, 'VDD')
    rail(d, XL - 2.8, XR + 2.8, Y_VSS, 'VSS')

    # PMOS mirror, gates facing inward; M4 is the diode (drain = NETD)
    m4 = pmos(d, (XL, Y_VDD), 'M4', '16u/1u')
    m3 = pmos(d, (XR, Y_VDD), 'M3', '16u/1u', left=True)
    g4, g3 = m4.absanchors['gate'], m3.absanchors['gate']
    wire(d, (g4.x, g4.y), (g3.x, g3.y))                 # shared gate bus
    dot(d, (g4.x, g4.y))
    wire(d, (g4.x, g4.y), (g4.x, Y_NETD))               # M4 diode tie

    # diff pair M1 (INN, left, NETD) / M0 (INP, right, OUT)
    m1 = nmos(d, (XL, Y_ND), 'M1', '20u/1u', left=True)
    m0 = nmos(d, (XR, Y_ND), 'M0', '20u/1u')
    wire(d, (XL, Y_PD), (XL, Y_ND))
    wire(d, (XR, Y_PD), (XR, Y_ND))
    wire(d, (g4.x, Y_NETD), (XL, Y_NETD))
    dot(d, (XL, Y_NETD))
    node_label(d, (XL - 0.25, Y_NETD + 0.18), 'NETD', halign='right')

    g1, g0 = m1.absanchors['gate'], m0.absanchors['gate']
    wire(d, (g1.x, g1.y), (XL - 2.5, g1.y))
    port(d, (XL - 2.5, g1.y), 'INN')
    wire(d, (g0.x, g0.y), (XR + 2.5, g0.y))
    port(d, (XR + 2.5, g0.y), 'INP', 'right')

    # OUT
    dot(d, (XR, Y_NETD))
    wire(d, (XR, Y_NETD), (XR + 2.5, Y_NETD))
    port(d, (XR + 2.5, Y_NETD), 'OUT', 'right')

    # tail
    s1, s0 = m1.absanchors['source'], m0.absanchors['source']
    yj = Y_TAILD + 0.35
    wire(d, (s1.x, s1.y), (XL, yj), (XT, yj))
    wire(d, (s0.x, s0.y), (XR, yj), (XT, yj))
    dot(d, (XT, yj))
    wire(d, (XT, yj), (XT, Y_TAILD))
    m5 = nmos(d, (XT, Y_TAILD), 'M5', '12u/1u')
    wire(d, m5.absanchors['source'], (XT, Y_VSS))
    node_label(d, (XT - 0.22, yj + 0.2), 'TAIL', halign='right')
    g5 = m5.absanchors['gate']
    wire(d, (g5.x, g5.y), (XT + 3.0, g5.y))
    port(d, (XT + 3.0, g5.y), 'VBIAS', 'right')

    title(d, XT, Y_VDD + 0.75,
          'Five-Transistor OTA   (PTM 180 nm, VDD = 1.8 V)')
    save(d, 'ota5t')


# ─────────────────────────────────────────────────────────────────────────────
# 2) Two-stage Miller op amp
# ─────────────────────────────────────────────────────────────────────────────
def draw_opamp2():
    d = drawing()
    XB = -4.6                     # bias column (M7 + IBIAS)
    XL, XR = 0.0, 4.6             # first-stage columns (A / B)
    XO = 8.6                      # output stage column
    XT = (XL + XR) / 2
    Y_VDD, Y_VSS = 9.0, 0.0
    Y_C = 6.2                     # node C (tail drain / pair sources)
    Y_PIN = Y_C - 0.35            # input-pair source row
    Y_A = Y_PIN - FET_H           # nodes A/B (input drains)
    Y_NM = 2.2                    # NMOS mirror drains
    Y_BUS = 7.0                   # PBIAS distribution bus
    Y_B = 3.1                     # B → M2-gate corridor
    Y_OUT = 4.4

    tint(d, XB - 1.9, Y_VSS + 0.2, XB + 1.4, Y_VDD - 0.2, TINTS['bias'],
         'bias')
    tint(d, XL - 1.9, Y_A - 0.5, XR + 1.9, Y_C + 0.5, TINTS['input'],
         'PMOS input pair')
    tint(d, XL - 1.9, Y_VSS + 0.2, XR + 1.9, Y_NM + 0.5, TINTS['mirror'],
         'mirror load', label_xy=(XT, 0.5), label_align='center')
    tint(d, XO - 1.6, Y_VSS + 0.2, XO + 2.6, Y_VDD - 0.2, TINTS['out'],
         'second stage', label_xy=(XO + 1.5, 0.45), label_align='center')

    rail(d, XB - 2.4, XO + 2.2, Y_VDD, 'VDD')
    rail(d, XB - 2.4, XO + 2.2, Y_VSS, 'VSS')

    # bias branch: M7 diode PMOS + IBIAS sink to VSS
    m7 = pmos(d, (XB, Y_VDD), 'M7', '120u/0.5u')
    d7 = m7.absanchors['drain']
    wire(d, (XB, d7.y), (XB, 5.6))
    d.add(elm.SourceI().at((XB, 5.6)).theta(-90).length(2.6))
    wire(d, (XB, 3.0), (XB, Y_VSS))
    d += (elm.Label().at((XB - 0.75, 4.3))
          .label('IBIAS\n120 uA', fontsize=8.5, halign='right'))
    node_label(d, (XB - 0.25, Y_BUS + 0.2), 'PBIAS', halign='right')
    g7 = m7.absanchors['gate']
    # diode tie: gate → down to bus row → drain column
    wire(d, (g7.x, g7.y), (g7.x, Y_BUS), (XB, Y_BUS))
    dot(d, (XB, Y_BUS))
    dot(d, (g7.x, Y_BUS))

    # PBIAS bus (below the PMOS row) to M5 (tail) and M6 (output PMOS)
    m5 = pmos(d, (XT, Y_VDD), 'M5', '120u/0.5u', left=True)
    m6 = pmos(d, (XO, Y_VDD), 'M6', '680u/0.5u', left=True)
    g5, g6 = m5.absanchors['gate'], m6.absanchors['gate']
    wire(d, (g7.x, Y_BUS), (g6.x, Y_BUS))
    wire(d, (g5.x, Y_BUS), (g5.x, g5.y))
    dot(d, (g5.x, Y_BUS))
    wire(d, (g6.x, Y_BUS), (g6.x, g6.y))

    # node C and input pair (PMOS): M0 gate INN (drain A) / M1 gate INP (B)
    d5 = m5.absanchors['drain']
    wire(d, (XT, d5.y), (XT, Y_C))
    dot(d, (XT, Y_C))
    node_label(d, (XT + 0.22, Y_C + 0.3), 'C')
    wire(d, (XL, Y_C), (XR, Y_C))
    m0 = pmos(d, (XL, Y_PIN), 'M0', '160u/0.5u', left=True)
    m1 = pmos(d, (XR, Y_PIN), 'M1', '160u/0.5u')
    wire(d, (XL, Y_C), (XL, Y_PIN))
    wire(d, (XR, Y_C), (XR, Y_PIN))
    g0, g1 = m0.absanchors['gate'], m1.absanchors['gate']
    wire(d, (g0.x, g0.y), (g0.x - 1.0, g0.y))
    port(d, (g0.x - 1.0, g0.y), 'INN')
    wire(d, (g1.x, g1.y), (g1.x + 0.8, g1.y))
    port(d, (g1.x + 0.8, g1.y), 'INP', 'right')

    # NMOS mirror M3 (diode, A) / M4 (B), gates facing inward
    m3 = nmos(d, (XL, Y_NM), 'M3', '60u/0.5u')
    m4 = nmos(d, (XR, Y_NM), 'M4', '60u/0.5u', left=True)
    wire(d, m3.absanchors['source'], (XL, Y_VSS))
    wire(d, m4.absanchors['source'], (XR, Y_VSS))
    wire(d, (XL, Y_A), (XL, Y_NM))
    wire(d, (XR, Y_A), (XR, Y_NM))
    node_label(d, (XL - 0.25, 3.6), 'A', halign='right')
    node_label(d, (XR - 0.25, 3.75), 'B', halign='right')
    g3, g4 = m3.absanchors['gate'], m4.absanchors['gate']
    wire(d, (g3.x, g3.y), (g4.x, g4.y))
    wire(d, (g3.x, g3.y), (g3.x, 2.75), (XL, 2.75))   # M3 diode tie
    dot(d, (XL, 2.75))
    dot(d, (g3.x, g3.y))

    # second stage: M6 PMOS from VDD, M2 NMOS gate=B, node OUT
    d6 = m6.absanchors['drain']
    wire(d, (XO, d6.y), (XO, Y_OUT))
    dot(d, (XO, Y_OUT))
    m2 = nmos(d, (XO, Y_NM), 'M2', '720u/0.5u', left=True)
    wire(d, (XO, Y_OUT), (XO, Y_NM))
    wire(d, m2.absanchors['source'], (XO, Y_VSS))
    g2 = m2.absanchors['gate']
    # B → M2 gate along the Y_B corridor
    dot(d, (XR, Y_B))
    wire(d, (XR, Y_B), (g2.x, Y_B), (g2.x, g2.y))
    # Miller cap CC: tap on the B corridor → OUT node
    xcc = 6.2
    dot(d, (xcc, Y_B))
    d.add(elm.Capacitor().at((xcc, Y_B)).to((xcc, Y_OUT))
          .label('CC 12p', loc='bottom', fontsize=8.5))
    wire(d, (xcc, Y_OUT), (XO, Y_OUT))
    # OUT port
    wire(d, (XO, Y_OUT), (XO + 1.9, Y_OUT))
    port(d, (XO + 1.9, Y_OUT), 'OUT', 'right')

    title(d, (XB + XO) / 2, Y_VDD + 0.75,
          'Two-Stage Miller Op Amp   (PTM 180 nm, VDD = 1.8 V)')
    save(d, 'opamp2')


# ─────────────────────────────────────────────────────────────────────────────
# 3) LDO
# ─────────────────────────────────────────────────────────────────────────────
def draw_ldo():
    d = drawing()
    XB = -4.8                       # bias column (I1 + M6)
    XL, XR = 0.0, 4.4               # EA columns: net3 (left) / net4 (right)
    XT = (XL + XR) / 2
    XP = 8.6                        # pass device / VOUT column
    XF = 10.6                       # feedback divider
    XO = 12.2                       # output cap / port
    Y_VIN, Y_VSS = 9.4, 0.0
    Y_PD = Y_VIN - FET_H            # EA PMOS drains
    Y_ND = 5.0                      # diff-pair drains
    Y_TIE = Y_ND + 0.55             # M4 diode-tie row
    Y_TAI = 2.2                     # tail drain (net16)
    Y_G2 = 6.6                      # net3 → M2-gate corridor
    Y_OUT = 5.6

    tint(d, XB - 1.9, Y_VSS + 0.2, XB + 1.6, Y_VIN - 0.2, TINTS['bias'],
         'bias')
    tint(d, XL - 1.6, 3.0, XR + 1.6, Y_VIN - 0.2, TINTS['input'],
         'error amplifier', label_xy=(XT, 3.2), label_align='center')
    tint(d, XT - 1.6, Y_VSS + 0.2, XT + 1.6, Y_TAI + 0.65, TINTS['bias'],
         'tail mirror', label_xy=(XT - 0.85, 0.45), label_align='center')
    tint(d, XP - 1.6, Y_VSS + 0.2, XO + 1.3, Y_VIN - 0.2, TINTS['out'],
         'pass device + feedback')

    rail(d, XB - 2.4, XO + 1.6, Y_VIN, 'VIN')
    rail(d, XB - 2.4, XO + 1.6, Y_VSS, 'VSS')

    # bias branch: I1 from VIN into diode M6; mirror gate bus → M5 tail
    wire(d, (XB, Y_VIN), (XB, 6.4))
    d.add(elm.SourceI().at((XB, 6.4)).theta(-90).length(1.8))
    d += (elm.Label().at((XB - 0.6, 5.5))
          .label('I1\n100 uA', fontsize=8.5, halign='right'))
    m6 = nmos(d, (XB, 3.9), 'M6', '160u/1u')
    wire(d, (XB, 4.6), (XB, 3.9))
    wire(d, m6.absanchors['source'], (XB, Y_VSS))
    node_label(d, (XB - 0.25, 4.42), 'ibias', halign='right')
    g6 = m6.absanchors['gate']
    wire(d, (g6.x, g6.y), (g6.x, 4.25), (XB, 4.25))      # M6 diode tie
    dot(d, (XB, 4.25))
    dot(d, (g6.x, g6.y))
    m5 = nmos(d, (XT, Y_TAI), 'M5', '160u/1u x10', left=True)
    g5 = m5.absanchors['gate']
    wire(d, (g6.x, g6.y), (g6.x, 1.0), (g5.x, 1.0), (g5.x, g5.y))
    wire(d, m5.absanchors['source'], (XT, Y_VSS))
    node_label(d, (XT - 0.25, Y_TAI + 0.62), 'net16', halign='right')

    # EA PMOS mirror, gates inward: M3 (net3, left) / M4 (diode, net4, right)
    m3 = pmos(d, (XL, Y_VIN), 'M3', '32u/1u x10')
    m4 = pmos(d, (XR, Y_VIN), 'M4', '32u/1u x10', left=True)
    g3, g4 = m3.absanchors['gate'], m4.absanchors['gate']
    wire(d, (g3.x, g3.y), (g4.x, g4.y))
    dot(d, (g4.x, g4.y))
    wire(d, (g4.x, g4.y), (g4.x, Y_TIE), (XR, Y_TIE))    # M4 diode tie
    dot(d, (XR, Y_TIE))

    # diff pair: M0 gate VREF (left, drain net3) / M1 gate net30 (right)
    m0 = nmos(d, (XL, Y_ND), 'M0', '240u/2u x10', left=True)
    m1 = nmos(d, (XR, Y_ND), 'M1', '240u/2u x10')
    wire(d, (XL, Y_PD), (XL, Y_ND))
    wire(d, (XR, Y_PD), (XR, Y_ND))
    node_label(d, (XL - 0.25, 6.15), 'net3 (EA out)', halign='right')
    node_label(d, (XR + 0.25, 6.15), 'net4')
    g0, g1 = m0.absanchors['gate'], m1.absanchors['gate']
    wire(d, (g0.x, g0.y), (g0.x - 1.3, g0.y))
    port(d, (g0.x - 1.3, g0.y), 'VREF')
    # tail joint
    yj = Y_TAI + 0.35
    wire(d, m0.absanchors['source'], (XL, yj), (XT, yj))
    wire(d, m1.absanchors['source'], (XR, yj), (XT, yj))
    dot(d, (XT, yj))
    wire(d, (XT, yj), (XT, Y_TAI))

    # pass device M2 (source VIN, gate net3, drain VOUT)
    m2 = pmos(d, (XP, Y_VIN), 'M2', '120u/0.18u x100', left=True)
    g2 = m2.absanchors['gate']
    wire(d, (XP, Y_PD), (XP, Y_OUT))
    dot(d, (XP, Y_OUT))
    # net3 → M2 gate along the Y_G2 corridor
    dot(d, (XL, Y_G2))
    wire(d, (XL, Y_G2), (g2.x, Y_G2), (g2.x, g2.y))
    # compensation R2 + C0: tap on the corridor, down to the VOUT column
    xc = 5.9
    dot(d, (xc, Y_G2))
    d.add(elm.Resistor().at((xc, Y_G2)).theta(-90).length(1.5))
    d += (elm.Label().at((xc + 0.35, Y_G2 - 0.75))
          .label('R2 2k', fontsize=8.5, halign='left'))
    node_label(d, (xc + 0.25, Y_G2 - 1.62), 'net34')
    d.add(elm.Capacitor().at((xc, Y_G2 - 1.5)).theta(-90).length(1.3))
    d += (elm.Label().at((xc + 0.35, Y_G2 - 2.35))
          .label('C0 160p', fontsize=8.5, halign='left'))
    wire(d, (xc, Y_G2 - 2.8), (xc, 3.3), (XP, 3.3))
    wire(d, (XP, Y_OUT), (XP, 3.3))
    dot(d, (XP, 3.3))

    # VOUT rail to divider + output cap + port
    wire(d, (XP, Y_OUT), (XF, Y_OUT))
    dot(d, (XF, Y_OUT))
    d.add(elm.Resistor().at((XF, Y_OUT)).theta(-90).length(1.7))
    d += (elm.Label().at((XF + 0.35, Y_OUT - 0.85))
          .label('R0 900', fontsize=8.5, halign='left'))
    dot(d, (XF, 3.9))
    node_label(d, (XF + 0.3, 4.12), 'net30 (FB)')
    d.add(elm.Resistor().at((XF, 3.9)).theta(-90).length(1.7))
    d += (elm.Label().at((XF + 0.35, 3.05))
          .label('R1 900', fontsize=8.5, halign='left'))
    wire(d, (XF, 2.2), (XF, Y_VSS))
    # net30 → M1 gate
    wire(d, (XF, 3.9), (6.0, 3.9), (6.0, g1.y), (g1.x, g1.y))
    # C2 + VOUT port
    wire(d, (XF, Y_OUT), (XO, Y_OUT))
    dot(d, (XO, Y_OUT))
    d.add(elm.Capacitor().at((XO, Y_OUT)).theta(-90).length(1.6))
    d += (elm.Label().at((XO + 0.35, Y_OUT - 0.8))
          .label('C2 1uF', fontsize=8.5, halign='left'))
    wire(d, (XO, Y_OUT - 1.6), (XO, Y_VSS))
    wire(d, (XO, Y_OUT), (XO + 1.0, Y_OUT))
    port(d, (XO + 1.0, Y_OUT), 'VOUT', 'right')

    title(d, (XB + XO) / 2, Y_VIN + 0.75,
          'LDO Regulator   (PTM 180 nm, VOUT = 1.8 V)')
    save(d, 'ldo')


# ─────────────────────────────────────────────────────────────────────────────
# 4) StrongArm comparator
# ─────────────────────────────────────────────────────────────────────────────
def draw_comparator():
    d = drawing()
    XL, XR = -1.9, 1.9              # main branches (VLP/VXP left, VLN/VXN right)
    Y_VDD, Y_VSS = 11.0, 0.0
    Y_VL = 8.63                     # VLP/VLN row (latch NMOS drains)
    Y_VX = 5.96                     # VXP/VXN row (input-pair drains)
    YJ = 2.2                        # common-source joint (VS)

    tint(d, XL - 1.5, 6.75, XR + 1.5, Y_VDD - 0.15, TINTS['latch'],
         'regenerative latch M3-M6', label_xy=(0, 7.0), label_align='center')
    tint(d, XL - 1.5, 3.7, XR + 1.5, 6.45, TINTS['input'],
         'input pair', label_xy=(0, 3.95), label_align='center')
    tint(d, -2.9, 0.3, 2.9, 2.5, TINTS['bias'],
         'clocked tail', label_xy=(1.55, 0.55), label_align='center')
    tint(d, -8.0, 5.35, -3.6, Y_VDD - 0.15, TINTS['bias'], 'reset switches')
    tint(d, 3.6, 5.35, 8.0, Y_VDD - 0.15, TINTS['bias'], 'reset switches')
    tint(d, -11.0, 3.3, -8.4, Y_VDD - 0.15, TINTS['out'],
         'output inverter', 'top')
    tint(d, 8.4, 3.3, 11.0, Y_VDD - 0.15, TINTS['out'],
         'output inverter', 'top')

    rail(d, -11.5, 11.5, Y_VDD, 'VDD')
    rail(d, -11.5, 11.5, Y_VSS, 'VSS')

    # cross-coupled latch: PMOS M5/M6 + NMOS M3/M4 (gate columns outboard)
    m5 = pmos(d, (XL, Y_VDD), 'M5', '2u', left=True)
    m6 = pmos(d, (XR, Y_VDD), 'M6', '2u')
    wire(d, (XL, Y_VDD - FET_H), (XL, Y_VL))
    wire(d, (XR, Y_VDD - FET_H), (XR, Y_VL))
    m3 = nmos(d, (XL, Y_VL), 'M3', '1u', left=True)
    m4 = nmos(d, (XR, Y_VL), 'M4', '1u')
    dot(d, (XL, Y_VL)); dot(d, (XR, Y_VL))
    node_label(d, (XL + 0.25, 8.32), 'VLP')
    node_label(d, (XR - 0.25, 8.32), 'VLN', halign='right')
    g5, g3 = m5.absanchors['gate'], m3.absanchors['gate']
    g6, g4 = m6.absanchors['gate'], m4.absanchors['gate']
    wire(d, (g5.x, g5.y), (g3.x, g3.y))                 # left gate column
    wire(d, (g6.x, g6.y), (g4.x, g4.y))                 # right gate column
    # cross-coupling X (between the drain nodes and the PMOS bodies):
    # left gates <- VLN at y=8.85, right gates <- VLP at y=9.05
    dot(d, (g3.x, 8.82))
    wire(d, (g3.x, 8.82), (XR, 8.82))
    dot(d, (XR, 8.82))
    dot(d, (g4.x, 9.12))
    wire(d, (g4.x, 9.12), (XL, 9.12))
    dot(d, (XL, 9.12))

    # latch sources -> VXP/VXN
    wire(d, m3.absanchors['source'], (XL, Y_VX))
    wire(d, m4.absanchors['source'], (XR, Y_VX))
    dot(d, (XL, Y_VX)); dot(d, (XR, Y_VX))
    node_label(d, (XL - 0.25, 6.2), 'VXP', halign='right')
    node_label(d, (XR + 0.25, 6.2), 'VXN')

    # input pair M1 (INP, left) / M2 (INN, right), drains at VX
    m1 = nmos(d, (XL, Y_VX), 'M1', '4u', left=True)
    m2 = nmos(d, (XR, Y_VX), 'M2', '4u')
    g1, g2 = m1.absanchors['gate'], m2.absanchors['gate']
    wire(d, (g1.x, g1.y), (-4.9, g1.y))
    port(d, (-4.9, g1.y), 'INP')
    wire(d, (g2.x, g2.y), (4.9, g2.y))
    port(d, (4.9, g2.y), 'INN', 'right')

    # common source VS + clocked tail M0
    wire(d, m1.absanchors['source'], (XL, YJ), (0, YJ))
    wire(d, m2.absanchors['source'], (XR, YJ), (0, YJ))
    dot(d, (0, YJ))
    node_label(d, (0.22, 2.45), 'VS')
    m0 = nmos(d, (0, YJ - 0.35), 'M0', '4u', left=True)
    wire(d, (0, YJ), (0, YJ - 0.35))
    wire(d, m0.absanchors['source'], (0, Y_VSS))
    g0 = m0.absanchors['gate']
    wire(d, (g0.x, g0.y), (-2.3, g0.y))
    port(d, (-2.3, g0.y), 'CLK')

    # reset PMOS (all gates on CLK): M7 -> VXP, M9 -> VLP, M8 -> VXN, M10 -> VLN
    def clk_gate(g, side):
        if side == 'left':
            xy, ha = (g.x - 0.12, g.y), 'right'
        elif side == 'right':
            xy, ha = (g.x + 0.12, g.y), 'left'
        else:                       # below the gate anchor
            xy, ha = (g.x, g.y - 0.45), 'center'
        d.add(elm.Label().at(xy).label('CLK', fontsize=7.5, color='#7f8c8d',
                                       halign=ha))

    m7 = pmos(d, (-6.4, Y_VDD), 'M7', '1u', left=True,
              label_at=(-6.95, 9.5, 'right'))
    wire(d, (-6.4, Y_VDD - FET_H), (-6.4, Y_VX), (XL, Y_VX))
    clk_gate(m7.absanchors['gate'], 'left')
    m9 = pmos(d, (-4.6, Y_VDD), 'M9', '1u', left=True)
    wire(d, (-4.6, Y_VDD - FET_H), (-4.6, Y_VL), (XL, Y_VL))
    clk_gate(m9.absanchors['gate'], 'below')
    m8 = pmos(d, (6.4, Y_VDD), 'M8', '1u',
              label_at=(6.95, 9.5, 'left'))
    wire(d, (6.4, Y_VDD - FET_H), (6.4, Y_VX), (XR, Y_VX))
    clk_gate(m8.absanchors['gate'], 'right')
    m10 = pmos(d, (4.6, Y_VDD), 'M10', '1u')
    wire(d, (4.6, Y_VDD - FET_H), (4.6, Y_VL), (XR, Y_VL))
    clk_gate(m10.absanchors['gate'], 'below')

    # output inverters: M11/M12 (VLP -> OUTP), M13/M14 (VLN -> OUTN);
    # gate columns inboard, outputs outboard
    for xi, mnp, mnn, xtap, out, left in (
            (-9.8, 'M11', 'M12', -3.0, 'OUTP', True),
            (9.8, 'M13', 'M14', 3.0, 'OUTN', False)):
        mp = pmos(d, (xi, Y_VDD), mnp, '2u', left=not left)
        mn = nmos(d, (xi, 5.6), mnn, '1u', left=not left)
        wire(d, (xi, Y_VDD - FET_H), (xi, 5.6))
        wire(d, mn.absanchors['source'], (xi, Y_VSS))
        gp, gn = mp.absanchors['gate'], mn.absanchors['gate']
        wire(d, (gp.x, gp.y), (gn.x, gn.y))
        ymid = (gp.y + gn.y) / 2
        dot(d, (gp.x, ymid))
        wire(d, (gp.x, ymid), (xtap, ymid), (xtap, Y_VL))
        dot(d, (xtap, Y_VL))
        yop = 6.5
        dot(d, (xi, yop))
        xo = xi + (-1.4 if left else 1.4)
        wire(d, (xi, yop), (xo, yop))
        port(d, (xo, yop), out, 'left' if left else 'right')

    title(d, 0, Y_VDD + 0.75,
          'StrongArm Dynamic Comparator   (PTM 45 nm HP, VDD = 1.0 V, L = 45 nm)')
    save(d, 'comparator')


# ─────────────────────────────────────────────────────────────────────────────
# 5) Bootstrapped switch
# ─────────────────────────────────────────────────────────────────────────────
def draw_bootstrap():
    d = drawing()
    Y_VDD, Y_VSS = 10.0, 0.0
    XCK = -7.6                      # clock inverter column
    XQ = -3.6                       # charge column (M1 / CB / M2)
    XM3 = -1.6                      # M3 (bottom-plate tracking switch)
    XG4 = 0.6                       # M4 transfer column
    XVG = 3.4                       # discharge column (M5A / M5)
    XS = 6.8                        # sampling switch MS
    Y_CBT = 7.6                     # CB_TOP row
    Y_CBB = 5.9                     # CB_BOT junction row
    Y_HUB = 5.3                     # VGATE distribution corridor
    XRISE = -1.0                    # VGATE riser to M1 gate

    tint(d, -9.2, 4.3, -5.9, 9.75, TINTS['bias'], 'clock inverter', 'top')
    tint(d, -4.4, 3.2, -2.4, 9.75, TINTS['comp'], 'bootstrap cap',
         label_xy=(-3.95, 9.55), label_align='right')
    tint(d, 0.0, 0.55, 4.3, 8.2, TINTS['mirror'],
         'gate transfer + discharge')
    tint(d, 4.7, 1.9, 9.3, 6.3, TINTS['input'], 'sampling switch',
         label_xy=(5.75, 2.12), label_align='center')

    rail(d, -9.9, 9.5, Y_VDD, 'VDD')
    rail(d, -9.9, 9.5, Y_VSS, 'VSS')

    # clock inverter (MP_INV / MN_INV): CLKS -> CLKSB
    mpi = pmos(d, (XCK, Y_VDD), 'MP_INV', '2u', left=True)
    mni = nmos(d, (XCK, 6.6), 'MN_INV', '1u', left=True)
    wire(d, (XCK, Y_VDD - FET_H), (XCK, 6.6))
    wire(d, mni.absanchors['source'], (XCK, Y_VSS))
    gpi, gni = mpi.absanchors['gate'], mni.absanchors['gate']
    wire(d, (gpi.x, gpi.y), (gni.x, gni.y))
    ymid = (gpi.y + gni.y) / 2
    wire(d, (gpi.x, ymid), (-9.5, ymid))
    port(d, (-9.5, ymid), 'CLKS')
    # CLKSB bus: down the side, feeding M2 gate and M5 gate
    dot(d, (XCK, 7.4))
    node_label(d, (-7.0, 7.62), 'CLKSB', halign='center')
    wire(d, (XCK, 7.4), (-6.3, 7.4), (-6.3, 1.2), (1.9, 1.2), (1.9, 1.665))

    # charge column: M1 (VDD -> CB_TOP, gate VGATE), CB, M2 (CB_BOT -> 0)
    m1 = pmos(d, (XQ, Y_VDD), 'M1', '4u')
    wire(d, (XQ, Y_VDD - FET_H), (XQ, Y_CBT))
    dot(d, (XQ, Y_CBT))
    node_label(d, (XQ - 0.25, Y_CBT + 0.2), 'CB_TOP', halign='right')
    d.add(elm.Capacitor().at((XQ, Y_CBT)).theta(-90).length(1.2))
    d += (elm.Label().at((XQ - 0.4, Y_CBT - 0.6))
          .label('CB 4p', fontsize=8.5, halign='right'))
    wire(d, (XQ, Y_CBT - 1.2), (XQ, 5.2))
    dot(d, (XQ, Y_CBB))
    node_label(d, (XQ - 0.25, Y_CBB + 0.2), 'CB_BOT', halign='right')
    m2 = nmos(d, (XQ, 5.2), 'M2', '8u', left=True)
    wire(d, m2.absanchors['source'], (XQ, Y_VSS))
    g2 = m2.absanchors['gate']
    dot(d, (-6.3, g2.y))
    wire(d, (-6.3, g2.y), (g2.x, g2.y))                 # CLKSB -> M2 gate

    # M3: CB_BOT -> VIN (gate VGATE), tracks the bottom plate
    m3 = nmos(d, (XM3, 4.4), 'M3', '13u')
    wire(d, (XM3, 4.4), (XM3, Y_CBB), (XQ, Y_CBB))
    wire(d, m3.absanchors['source'], (XM3, 2.6))
    g3 = m3.absanchors['gate']
    wire(d, (g3.x, g3.y), (g3.x, Y_HUB))                # VGATE stub
    dot(d, (g3.x, Y_HUB))

    # M4: CB_TOP -> VGATE (gate NET_G4, drivers condensed in the note)
    m4 = pmos(d, (XG4, Y_CBT), 'M4', '4u')
    wire(d, (XQ, Y_CBT), (XG4, Y_CBT))
    wire(d, (XG4, Y_CBT - FET_H), (XG4, Y_HUB))
    dot(d, (XG4, Y_HUB))
    node_label(d, (XG4 - 0.3, Y_HUB - 0.35), 'VGATE', halign='right')
    g4 = m4.absanchors['gate']
    wire(d, (g4.x, g4.y), (g4.x + 0.6, g4.y))
    dot(d, (g4.x + 0.6, g4.y))
    node_label(d, (g4.x + 0.75, g4.y + 0.25), 'NET_G4')
    d += (elm.Label().at((g4.x + 0.75, g4.y - 0.55))
          .label('M4A: VGATE→VIN\nM4B: CLKS→VDD\nM4C: CLKS→CB_BOT',
                 fontsize=7.5, color='#7f8c8d', halign='left'))

    # VGATE corridor: hub -> M3 gate, M5A drain, MS gate, and riser to M1 gate
    ms_gx = XS - GATE_DX
    wire(d, (XRISE, Y_HUB), (ms_gx, Y_HUB))
    m5a = nmos(d, (XVG, 4.6), 'M5A', '2u', left=True)
    dot(d, (XVG, Y_HUB))
    wire(d, (XVG, Y_HUB), (XVG, 4.6))
    node_label(d, (XVG + 0.25, 4.85), 'VGATE')
    wire(d, m5a.absanchors['source'], (XVG, 2.5))
    node_label(d, (XVG + 0.25, 2.72), 'NET_5A')
    m5 = nmos(d, (XVG, 2.5), 'M5', '2u', left=True)
    wire(d, m5.absanchors['source'], (XVG, Y_VSS))
    g5a, g5 = m5a.absanchors['gate'], m5.absanchors['gate']
    node_label(d, (g5a.x - 0.15, g5a.y), 'VDD', halign='right')
    # (CLKSB bus already routed to M5 gate at (1.9, 1.665))
    wire(d, (1.9, g5.y), (g5.x, g5.y))
    # riser to M1 gate (VGATE)
    g1 = m1.absanchors['gate']
    dot(d, (XRISE, Y_HUB))
    wire(d, (XRISE, Y_HUB), (XRISE, g1.y), (g1.x, g1.y))

    # sampling switch MS: VIN -> VOUT, gate on VGATE corridor
    ms = nmos(d, (XS, 4.9), 'MS', '16u', left=True)
    gms = ms.absanchors['gate']
    wire(d, (ms_gx, Y_HUB), (gms.x, gms.y))
    wire(d, (XS, 4.9), (XS, 5.6))
    wire(d, (XS, 5.6), (8.6, 5.6))
    port(d, (8.6, 5.6), 'VOUT', 'right')
    wire(d, ms.absanchors['source'], (XS, 2.6))
    # VIN bus: port on the left, M3 source, then under the discharge column
    port(d, (-2.6, 2.6), 'VIN')
    wire(d, (-2.6, 2.6), (2.6, 2.6), (2.6, 0.5), (XS, 0.5), (XS, 2.6))
    dot(d, (XM3, 2.6))

    title(d, 0, Y_VDD + 0.75,
          'Bootstrapped Sampling Switch   (PTM 180 nm, VDD = 1.8 V)')
    save(d, 'bootstrap')


# ─────────────────────────────────────────────────────────────────────────────
# 6) Current-mirror (symmetric) OTA — studio_circuits (Sizing tab)
# ─────────────────────────────────────────────────────────────────────────────
def draw_cm_ota():
    """PMOS-input current-mirror OTA — matches studio_circuits/amp/netlist/
    CM_OTA_Pin_3 device-by-device (self-biased from one internal Ibias)."""
    d = drawing()
    Y_VDD, Y_VSS = 8.0, 0.0
    Y_PD = Y_VDD - FET_H            # PMOS drains (6.33)
    Y_NT = Y_PD                     # tail / input-pair source bus
    Y_ND = 4.4                      # input-pair (PMOS) drains  n1/n2
    Y_MND = FET_H                   # NMOS mirror drains (1.67)

    X_B = -3.6                      # bias: MB diode + Ibias
    X1, X2 = 0.0, 3.6              # input pair / mirror-input legs
    XT = (X1 + X2) / 2              # tail
    X5 = 7.2                        # fold: M5 + M7 diode -> n3
    X6 = 10.8                       # output: M8 + M6 -> OUT

    tint(d, X_B - 1.1, Y_VSS + 0.1, X_B + 1.1, Y_VDD - 0.15, TINTS['bias'],
         'bias')
    tint(d, X1 - 1.5, Y_ND - 0.4, X2 + 1.5, Y_VDD - 0.15, TINTS['input'],
         'PMOS input pair + tail', label_at='top')
    tint(d, X1 - 1.5, Y_VSS + 0.1, X2 + 1.5, Y_MND + 0.7, TINTS['mirror'],
         'NMOS mirror inputs')
    tint(d, X5 - 1.3, Y_VSS + 0.1, X6 + 2.0, Y_VDD - 0.15, TINTS['out'],
         'mirror out + fold + output', label_at='top')

    rail(d, X_B - 1.4, X6 + 2.4, Y_VDD, 'VDDA')
    rail(d, X_B - 1.4, X6 + 2.4, Y_VSS, 'GNDA')

    # bias: MB PMOS diode + Ibias sink; VB = npb
    mb = pmos(d, (X_B, Y_VDD), 'MB', '')
    npb = (X_B, Y_PD)
    wire(d, mb.absanchors['drain'], npb)
    gb = mb.absanchors['gate']
    wire(d, (gb.x, gb.y), (X_B, gb.y)); dot(d, (X_B, gb.y)); dot(d, npb)
    node_label(d, (X_B - 0.25, Y_PD + 0.2), 'VB', halign='right')
    d.add(elm.SourceI().at((X_B, Y_PD)).theta(-90).length(Y_PD)
          .label('Ibias', fontsize=8, loc='right'))

    # tail M0 (PMOS), gate = VB
    m0 = pmos(d, (XT, Y_VDD), 'M0', '', left=True)
    nt = (XT, Y_PD)
    wire(d, m0.absanchors['drain'], nt)
    g0 = m0.absanchors['gate']
    wire(d, npb, (X_B, g0.y), (g0.x, g0.y))
    node_label(d, (XT + 0.15, Y_PD + 0.22), 'nt', halign='left')

    # input pair M1(INN,left) / M2(INP,right); sources on the nt bus
    m1 = pmos(d, (X1, Y_NT), 'M1', '', left=True)
    m2 = pmos(d, (X2, Y_NT), 'M2', '')
    wire(d, (X1, Y_NT), (X2, Y_NT)); dot(d, nt)
    n1 = (X1, Y_ND); n2 = (X2, Y_ND)
    wire(d, m1.absanchors['drain'], n1)
    wire(d, m2.absanchors['drain'], n2)
    g1 = m1.absanchors['gate']; g2 = m2.absanchors['gate']
    wire(d, (g1.x, g1.y), (X1 - 2.0, g1.y)); port(d, (X1 - 2.0, g1.y), 'VINN')
    wire(d, (g2.x, g2.y), (X2 + 2.0, g2.y))
    port(d, (X2 + 2.0, g2.y), 'VINP', 'right')

    # NMOS mirror-input diodes M3/M4 (drain=gate=n1/n2)
    m3 = nmos(d, (X1, Y_MND), 'M3', '', left=True)
    m4 = nmos(d, (X2, Y_MND), 'M4', '')
    wire(d, n1, (X1, Y_MND)); wire(d, n2, (X2, Y_MND))
    wire(d, m3.absanchors['source'], (X1, Y_VSS))
    wire(d, m4.absanchors['source'], (X2, Y_VSS))
    g3 = m3.absanchors['gate']; g4 = m4.absanchors['gate']
    wire(d, (g3.x, g3.y), (X1, g3.y)); dot(d, (X1, g3.y))
    wire(d, (g4.x, g4.y), (X2, g4.y)); dot(d, (X2, g4.y))
    dot(d, n1); node_label(d, (X1 - 0.25, Y_ND + 0.15), 'n1', halign='right')
    dot(d, n2); node_label(d, (X2 + 0.25, Y_ND + 0.15), 'n2', halign='left')

    # fold: M5(NMOS, gate n1) + M7(PMOS diode) -> n3
    m5 = nmos(d, (X5, Y_MND), 'M5', '')
    wire(d, m5.absanchors['source'], (X5, Y_VSS))
    g5 = m5.absanchors['gate']
    wire(d, (X1, Y_ND), (X1, 3.5))                       # n1 gate bus (middle)
    wire(d, (X1, 3.5), (g5.x, 3.5), (g5.x, g5.y)); dot(d, (X1, 3.5))
    m7 = pmos(d, (X5, Y_VDD), 'M7', '')
    n3 = (X5, Y_PD)
    wire(d, m7.absanchors['drain'], n3)
    wire(d, n3, (X5, Y_MND))                             # n3 down to M5 drain
    g7 = m7.absanchors['gate']
    wire(d, (g7.x, g7.y), (X5, g7.y)); dot(d, (X5, g7.y))
    dot(d, n3); node_label(d, (X5 + 0.2, Y_PD + 0.2), 'n3', halign='left')

    # output: M8(PMOS, gate n3) + M6(NMOS, gate n2) -> OUT
    m8 = pmos(d, (X6, Y_VDD), 'M8', '', left=True)
    out_t = (X6, Y_PD)
    wire(d, m8.absanchors['drain'], out_t)
    g8 = m8.absanchors['gate']
    wire(d, (X5, g7.y), (g8.x, g8.y))                    # n3 -> M8 gate
    m6 = nmos(d, (X6, Y_MND), 'M6', '')
    wire(d, m6.absanchors['source'], (X6, Y_VSS))
    g6 = m6.absanchors['gate']
    wire(d, (X2, Y_ND), (X2, 2.9))                       # n2 gate bus (middle)
    wire(d, (X2, 2.9), (g6.x, 2.9), (g6.x, g6.y)); dot(d, (X2, 2.9))
    wire(d, out_t, (X6, Y_MND)); dot(d, out_t)
    wire(d, out_t, (X6 + 1.9, Y_PD)); port(d, (X6 + 1.9, Y_PD), 'VOUT', 'right')
    d.add(elm.Capacitor().at((X6 + 0.95, Y_PD)).to((X6 + 0.95, Y_VSS))
          .label('CL', fontsize=8, loc='bottom'))

    title(d, (X1 + X6) / 2, Y_VDD + 0.8,
          'Current-Mirror (Symmetric) OTA   (SKY130, VDDA = 1.8 V)')
    STUDIO_SCH_DIR.mkdir(parents=True, exist_ok=True)
    path = STUDIO_SCH_DIR / 'CM_OTA_Pin_3.png'
    d.save(str(path), dpi=200, transparent=False)
    print(f'  saved {path}')


DRAWERS = {
    'ota5t': draw_ota5t,
    'opamp2': draw_opamp2,
    'ldo': draw_ldo,
    'comparator': draw_comparator,
    'bootstrap': draw_bootstrap,
    'cm_ota': draw_cm_ota,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', help='render a single circuit key')
    args = ap.parse_args()
    keys = [args.only] if args.only else list(DRAWERS)
    for k in keys:
        print(f'rendering {k} ...')
        DRAWERS[k]()


if __name__ == '__main__':
    main()

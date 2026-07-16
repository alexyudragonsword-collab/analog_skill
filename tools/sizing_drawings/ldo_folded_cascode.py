"""ldo_folded_cascode — folded-cascode error amplifier + PMOS pass.

NMOS input pair M1 (vinp) / M2 (vinn) with tail M9 (Vb1); the pair drains
net2/net3 are the folded nodes: PMOS loads M3/M4 (gates on net1, the
self-bias node) on top, cascode PMOS M5/M6 (Vb2) folding down to the
NMOS sinks M7/M8 (Vb1). Single-ended output vout1 drives the pass PMOS
M10 into Vreg; compensation is Rfb from vout1 into the folded node net2
plus Cfb from net2 to Vreg. Vb1/Vb2 are subckt pins: drawn as ports on
M7/M5 and as labelled stubs on their siblings.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_sizing_schematics import (   # noqa: E402
    LDO_NL, Sheet, TINTS, Y_CT, Y_GND, Y_ND, Y_PD, Y_VDD, dot, gate_feed,
    node_label, port, rail, tint, title, wire,
)

KEY = 'ldo_folded_cascode'


def draw():
    sh = Sheet(LDO_NL / 'ldo_folded_cascode.txt')
    d = sh.d
    XL = 0.0                          # net1 column: M3 / M5 / M7
    XT = 2.4                          # tail M9 (left of the pair)
    XPL, XPR = 4.8, 7.4               # input pair M1 / M2
    XR = 10.6                         # net3 column: M4 / M6 / M8
    XP = 14.2                         # pass device / Vreg column
    XMAX = XP + 2.8

    tint(d, XL - 2.6, Y_GND + .12, XR + 2.0, Y_VDD - .15, TINTS['input'],
         'folded-cascode error amplifier')
    tint(d, XR + 2.15, Y_GND + .12, XMAX - 0.2, Y_VDD - .15, TINTS['out'],
         'pass device + compensation')
    rail(d, XL - 3.0, XMAX, Y_VDD, 'VDD')
    rail(d, XL - 3.0, XMAX, Y_GND, 'VSS')

    # PMOS loads, gates inward on the self-bias node net1
    m3 = sh.pfet('xm3', XL, 'M3')
    m4 = sh.pfet('xm4', XR, 'M4', left=True)
    g3, g4 = m3.absanchors['gate'], m4.absanchors['gate']
    wire(d, (g3.x, g3.y), (g4.x, g4.y))          # inward gate bus (net1)
    # cascode PMOS pair (sources on the folded nodes net2 / net3)
    m5 = sh.pfet('xm5', XL, 'M5', left=True, y=Y_PD)
    g5 = m5.absanchors['gate']
    wire(d, (g5.x, g5.y), (g5.x - 0.68, g5.y))
    port(d, (g5.x - 0.68, g5.y), 'VB2')
    sh.pfet('xm6', XR, 'M6', bias='Vb2', y=Y_PD)
    # NMOS cascode sinks
    m7 = sh.nfet('xm7', XL, Y_ND, 'M7', left=True, to_gnd=True)
    g7 = m7.absanchors['gate']
    wire(d, (g7.x, g7.y), (g7.x - 0.68, g7.y))
    port(d, (g7.x - 0.68, g7.y), 'VB1')
    sh.nfet('xm8', XR, Y_ND, 'M8', bias='Vb1', to_gnd=True)
    wire(d, (XL, Y_PD - 1.67), (XL, Y_ND))       # net1 column
    wire(d, (XR, Y_PD - 1.67), (XR, Y_ND))       # vout1 column
    # net1 ties back to the load gates (T onto the gate bus)
    dot(d, (XL, 6.4))
    wire(d, (XL, 6.4), (XL + 1.4, 6.4), (XL + 1.4, g3.y))
    dot(d, (XL + 1.4, g3.y))
    node_label(d, (XL - 0.25, 5.6), 'net1', halign='right')
    node_label(d, (XR + 0.18, 4.4), 'vout1')

    # NMOS input pair, drains folded up to net2 / net3
    m1 = sh.nfet('xm1', XPL, Y_CT, 'M1', left=True)
    m2 = sh.nfet('xm2', XPR, Y_CT, 'M2')
    g1, g2 = m1.absanchors['gate'], m2.absanchors['gate']
    wire(d, (g1.x, g1.y), (g1.x - 0.6, g1.y))
    port(d, (g1.x - 0.6, g1.y), 'VINP')
    wire(d, (g2.x, g2.y), (g2.x + 0.6, g2.y))
    port(d, (g2.x + 0.6, g2.y), 'VINN', 'right')
    wire(d, (XPL, Y_CT), (XPL, Y_PD), (XL, Y_PD))
    dot(d, (XL, Y_PD))                           # net2 fold junction
    wire(d, (XPR, Y_CT), (XPR, Y_PD), (XR, Y_PD))
    dot(d, (XR, Y_PD))                           # net3 fold junction
    node_label(d, (XL + 1.7, Y_PD + 0.18), 'net2')
    node_label(d, (XPR + 0.18, 7.6), 'net3')
    # tail under the pair source bus
    wire(d, (XT, Y_ND), (XPR, Y_ND))
    dot(d, (XPL, Y_ND))
    sh.nfet('xm9', XT, Y_ND, 'M9', bias='Vb1', to_gnd=True)
    node_label(d, ((XT + XPL) / 2 - 0.55, Y_ND + 0.18), 'net4')

    # pass PMOS, gate fed from vout1 (faces left)
    m10 = sh.pfet('xm10', XP, 'M10 (pass)', left=True)
    g10 = m10.absanchors['gate']
    gate_feed(sh, (XR, 6.3), g10.x, g10.y)       # vout1 -> M10 gate
    wire(d, (XP, Y_PD), (XP, 5.2))               # Vreg column
    dot(d, (XP, 7.4))
    wire(d, (XP, 7.4), (XP + 1.3, 7.4))
    port(d, (XP + 1.3, 7.4), 'VREG', 'right')

    # compensation: vout1 -Rfb-> net2 (folded node) -Cfb-> Vreg
    dot(d, (XPL, 5.8))
    wire(d, (XPL, 5.8), (XPL + 0.7, 5.8))
    sh.res('xrfb', (XPL + 0.7, 5.8), (XPL + 2.1, 5.8), 'RFB')
    wire(d, (XPL + 2.1, 5.8), (XR, 5.8))
    dot(d, (XR, 5.8))
    dot(d, (XPL, 5.2))
    wire(d, (XPL, 5.2), (XP - 1.3, 5.2))
    sh.cap('xcfb', (XP - 1.3, 5.2), (XP - 0.3, 5.2), 'CFB')
    wire(d, (XP - 0.3, 5.2), (XP, 5.2))
    dot(d, (XP, 5.2))

    title(d, (XL - 2.6 + XMAX) / 2, Y_VDD + 0.8,
          'Folded-Cascode LDO — LDO (SKY130, 1.8 V)')
    sh.save(KEY)

"""ldo_simple — 5T OTA error amplifier + PMOS pass device.

Smallest LDO of the family: NMOS input pair (M1/M2) under a PMOS mirror
(M4 diode / M3), tail M5 biased from the Vb pin, pass PMOS M6 driven by
the single-ended amp output vout1, and an Rfb+Cfb series network from
vout1 to the regulated node Vreg (net22 in between).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_sizing_schematics import (   # noqa: E402
    LDO_NL, Sheet, TINTS, Y_CT, Y_GND, Y_ND, Y_VDD, dot, gate_feed,
    node_label, port, rail, tint, title, wire,
)

KEY = 'ldo_simple'


def draw():
    sh = Sheet(LDO_NL / 'ldo_simple.txt')
    d = sh.d
    XL, XT, XR = 0.0, 2.4, 4.8       # error amp: mirror/pair cols + tail
    XP = 8.8                         # pass device / Vreg column
    XMAX = XP + 2.6

    tint(d, XL - 2.4, Y_GND + .12, XR + 0.4, Y_VDD - .15, TINTS['input'],
         'error amplifier (5T OTA)')
    tint(d, XR + 0.5, Y_GND + .12, XMAX - 0.2, Y_VDD - .15, TINTS['out'],
         'pass device + compensation')
    rail(d, XL - 2.7, XMAX, Y_VDD, 'VDD')
    rail(d, XL - 2.7, XMAX, Y_GND, 'VSS')

    # PMOS mirror load (gates inward, diode on the M4/net1 side)
    m4 = sh.pfet('xm4', XL, 'M4')
    m3 = sh.pfet('xm3', XR, 'M3', left=True)
    g4, g3 = m4.absanchors['gate'], m3.absanchors['gate']
    wire(d, (g4.x, g4.y), (g3.x, g3.y))          # inward mirror gate bus
    dot(d, (g4.x, g4.y))
    sh.diode_tie(m4, XL)

    # NMOS input pair + tail sink
    wire(d, (XL, Y_VDD - 1.67), (XL, Y_CT))      # net1 column
    wire(d, (XR, Y_VDD - 1.67), (XR, Y_CT))      # vout1 column
    m1 = sh.nfet('xm1', XL, Y_CT, 'M1', left=True)
    m2 = sh.nfet('xm2', XR, Y_CT, 'M2')
    g1, g2 = m1.absanchors['gate'], m2.absanchors['gate']
    wire(d, (g1.x, g1.y), (g1.x - 0.6, g1.y))
    port(d, (g1.x - 0.6, g1.y), 'VINP')
    wire(d, (g2.x, g2.y), (g2.x + 0.6, g2.y))
    port(d, (g2.x + 0.6, g2.y), 'VINN', 'right')
    wire(d, (XL, Y_ND), (XR, Y_ND))              # net2 source bus
    m5 = sh.nfet('xm5', XT, Y_ND, 'M5', left=True, to_gnd=True)
    dot(d, (XT, Y_ND))
    g5 = m5.absanchors['gate']
    wire(d, (g5.x, g5.y), (g5.x - 0.6, g5.y))
    port(d, (g5.x - 0.6, g5.y), 'VB')
    node_label(d, (XL - 0.25, 7.1), 'net1', halign='right')
    node_label(d, (XR + 0.18, 7.85), 'vout1')
    node_label(d, (XT + 0.6, Y_ND + 0.18), 'net2')

    # pass PMOS, gate fed from vout1 (faces left)
    m6 = sh.pfet('xm6', XP, 'M6 (pass)', left=True)
    g6 = m6.absanchors['gate']
    gate_feed(sh, (XR, 7.5), g6.x, g6.y)         # vout1 -> M6 gate
    wire(d, (XP, Y_VDD - 1.67), (XP, 6.2))       # Vreg column
    dot(d, (XP, 7.2))
    wire(d, (XP, 7.2), (XP + 1.2, 7.2))
    port(d, (XP + 1.2, 7.2), 'VREG', 'right')

    # Rfb + Cfb series compensation: vout1 -> net22 -> Vreg
    dot(d, (XR, 6.2))
    wire(d, (XR, 6.2), (XR + 0.5, 6.2))
    sh.res('xrfb', (XR + 0.5, 6.2), (XR + 1.9, 6.2), 'RFB')
    wire(d, (XR + 1.9, 6.2), (XR + 2.6, 6.2))
    node_label(d, (XR + 2.05, 6.38), 'net22')
    sh.cap('xcfb', (XR + 2.6, 6.2), (XR + 3.5, 6.2), 'CFB')
    wire(d, (XR + 3.5, 6.2), (XP, 6.2))
    dot(d, (XP, 6.2))

    title(d, (XL - 2.4 + XMAX) / 2, Y_VDD + 0.8,
          'Simple LDO — LDO (SKY130, 1.8 V)')
    sh.save(KEY)

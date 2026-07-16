"""ldo_1 — two-stage error amplifier + PMOS pass + resistive divider.

NMOS input pair M2 (vinn) / M3 (vinp) under a PMOS mirror (M1 diode on
net1 / M0 to net8), tail and second-stage sinks mirrored off the Ib pin
diode M5; common-source PMOS M6 (gate net8) loaded by M7 drives the pass
gate net3; pass PMOS M8 feeds vout with the r0/r1 divider tapped at vfb.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_sizing_schematics import (   # noqa: E402
    LDO_NL, Sheet, TINTS, Y_CT, Y_GND, Y_ND, Y_VDD, dot, gate_feed,
    node_label, port, rail, tint, title, wire,
)

KEY = 'ldo_1'


def draw():
    sh = Sheet(LDO_NL / 'ldo_1.txt')
    d = sh.d
    XB = 0.0                          # Ib bias diode
    XL, XT, XR = 3.2, 5.6, 8.0        # error amp: mirror/pair cols + tail
    X2 = 11.0                         # second stage (M6 over M7)
    XP = 14.2                         # pass device / vout column
    XMAX = XP + 2.8

    tint(d, XB - 1.3, Y_GND + .12, XB + 1.3, Y_VDD - .15, TINTS['bias'],
         'bias (Ib)')
    tint(d, XL - 2.5, Y_GND + .12, XR + 1.25, Y_VDD - .15, TINTS['input'],
         'error amplifier')
    tint(d, XR + 1.35, Y_GND + .12, X2 + 1.4, Y_VDD - .15, TINTS['mirror'],
         'stage 2')
    tint(d, X2 + 1.5, Y_GND + .12, XMAX - 0.2, Y_VDD - .15, TINTS['out'],
         'pass device + feedback')
    rail(d, XB - 1.6, XMAX, Y_VDD, 'VDD')
    rail(d, XB - 1.6, XMAX, Y_GND, 'VSS')

    # bias: NMOS diode M5 off the Ib pin (gate stubs 'Ib' mirror from it)
    m5 = sh.nfet('xm5', XB, Y_ND, 'M5', to_gnd=True)
    sh.diode_tie(m5, XB)
    wire(d, (XB, Y_ND), (XB, 6.5))
    port(d, (XB, 6.5), 'IB')
    node_label(d, (XB + 0.2, 5.4), 'Ib')

    # PMOS mirror load (gates inward, diode on the M1/net1 side)
    m1 = sh.pfet('xm1', XL, 'M1')
    m0 = sh.pfet('xm0', XR, 'M0', left=True)
    g1, g0 = m1.absanchors['gate'], m0.absanchors['gate']
    wire(d, (g1.x, g1.y), (g0.x, g0.y))          # inward mirror gate bus
    dot(d, (g1.x, g1.y))
    sh.diode_tie(m1, XL)

    # NMOS input pair + Ib-mirrored tail
    wire(d, (XL, Y_VDD - 1.67), (XL, Y_CT))      # net1 column
    wire(d, (XR, Y_VDD - 1.67), (XR, Y_CT))      # net8 column
    m2 = sh.nfet('xm2', XL, Y_CT, 'M2', left=True)
    m3 = sh.nfet('xm3', XR, Y_CT, 'M3')
    g2, g3 = m2.absanchors['gate'], m3.absanchors['gate']
    wire(d, (g2.x, g2.y), (g2.x - 0.6, g2.y))
    port(d, (g2.x - 0.6, g2.y), 'VINN')
    wire(d, (g3.x, g3.y), (g3.x + 0.6, g3.y))
    port(d, (g3.x + 0.6, g3.y), 'VINP', 'right')
    wire(d, (XL, Y_ND), (XR, Y_ND))              # net2 source bus
    sh.nfet('xm4', XT, Y_ND, 'M4', left=True, bias='Ib', to_gnd=True)
    dot(d, (XT, Y_ND))
    node_label(d, (XL - 0.25, 7.1), 'net1', halign='right')
    node_label(d, (XR + 0.18, 6.6), 'net8')
    node_label(d, (XT + 0.6, Y_ND + 0.18), 'net2')

    # stage 2: common-source PMOS M6 over Ib-mirrored sink M7 -> net3
    m6 = sh.pfet('xm6', X2, 'M6', left=True)
    g6 = m6.absanchors['gate']
    gate_feed(sh, (XR, 7.5), g6.x, g6.y)         # net8 -> M6 gate
    wire(d, (X2, Y_VDD - 1.67), (X2, Y_ND))      # net3 column
    sh.nfet('xm7', X2, Y_ND, 'M7', bias='Ib', to_gnd=True)
    node_label(d, (X2 + 0.2, 5.6), 'net3')

    # pass PMOS + r0/r1 feedback divider under vout
    m8 = sh.pfet('xm8', XP, 'M8 (pass)', left=True)
    g8 = m8.absanchors['gate']
    gate_feed(sh, (X2, 7.9), g8.x, g8.y)         # net3 -> M8 gate
    wire(d, (XP, Y_VDD - 1.67), (XP, 4.7))       # vout column
    dot(d, (XP, 7.1))
    wire(d, (XP, 7.1), (XP + 1.3, 7.1))
    port(d, (XP + 1.3, 7.1), 'VOUT', 'right')
    sh.res('r0', (XP, 4.7), (XP, 3.0), 'R0\n300k', loc='bot')
    dot(d, (XP, 3.0))
    wire(d, (XP, 3.0), (XP + 1.0, 3.0))
    port(d, (XP + 1.0, 3.0), 'VFB', 'right')
    sh.res('r1', (XP, 3.0), (XP, 1.3), 'R1\n100k', loc='bot')
    wire(d, (XP, 1.3), (XP, Y_GND))

    title(d, (XB - 1.3 + XMAX) / 2, Y_VDD + 0.8,
          'LDO 1 — LDO (SKY130, 1.8 V)')
    sh.save(KEY)

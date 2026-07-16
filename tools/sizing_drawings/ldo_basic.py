"""ldo_basic — AnalogGym Basic LDO (LDO_netlist.txt).

Same skeleton as the NMC-amp reference sheets: an Ib-referenced bias band
(vb3/vb4 generation + replica), a PMOS-pair error amplifier with cascoded
NMOS sinks and a PMOS mirror on top (voutn diode / net10 output), then a
gm2 level shifter (M24 pull-up, source-follower-style lvt M10 whose
source node net1 drives the pass gate, M21/M22 net7 mirror as its sink),
the big power PMOS M11 into vout, the r1/r0 divider tapped at vfb, and
the C0 compensation cap from the cascode node net106 to vout.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_sizing_schematics import (   # noqa: E402
    FET_H, LDO_NL, Sheet, TINTS, Y_CM, Y_CT, Y_GND, Y_ND, Y_PD, Y_SRC,
    Y_VDD, dot, gate_feed, node_label, port, rail, tint, title, wire,
)

KEY = 'ldo_basic'


def draw():
    sh = Sheet(LDO_NL / 'LDO_netlist.txt')
    d = sh.d
    XB0, XB1, XB2, XR = -0.4, 2.6, 5.8, 9.0      # bias band columns
    XTAIL = 13.0                                 # tail (left of the pair)
    XCL, XPL, XPR, XCR = 15.8, 18.0, 20.2, 22.8  # error-amp columns
    X2A, X2B = 25.6, 28.2                        # gm2: net7 mirror + M10
    XP = 31.8                                    # pass device / vout
    XMAX = XP + 2.8

    tint(d, XB0 - 1.2, Y_GND + .12, XR + 1.1, Y_VDD - .15, TINTS['bias'],
         'bias (Ib / vb3 / vb4)')
    tint(d, XTAIL - 1.7, Y_GND + .12, XCR + 1.2, Y_VDD - .15,
         TINTS['input'], 'error amplifier: cascoded input')
    tint(d, X2A - 1.3, Y_GND + .12, X2B + 1.2, Y_VDD - .15, TINTS['mirror'],
         'gm2 / pass driver')
    tint(d, XP - 1.3, Y_GND + .12, XMAX - 0.2, Y_VDD - .15, TINTS['out'],
         'pass device + feedback')
    rail(d, XB0 - 1.5, XMAX, Y_VDD, 'VDDA')
    rail(d, XB0 - 1.5, XMAX, Y_GND, 'GNDA')

    # bias band: PMOS diode off the Ib pin, vb4/vb3 generators, replica
    m0 = sh.pfet('xm0', XB0, 'M0')
    g0 = m0.absanchors['gate']
    wire(d, m0.absanchors['drain'], (XB0, g0.y))
    sh.diode_tie(m0, XB0)
    node_label(d, (XB0 - 0.25, g0.y - 0.4), 'Ib', halign='right')
    wire(d, (XB0, Y_PD), (XB0, 1.4))
    port(d, (XB0, 1.4), 'IB')
    sh.pfet('xm1', XB1, 'M1', bias='Ib')         # vb4 generator leg
    wire(d, (XB1, Y_PD), (XB1, Y_CT))
    sh.nfet('xm12', XB1, Y_CT, 'M12 (4x)', left=True, bias='vb3')
    sh.nfet('xm17', XB1, Y_CM, 'M17 (4x)', left=True, bias='vb4',
            to_gnd=True)
    node_label(d, (XB1 + 0.15, Y_CT + 0.9), 'vb4')
    sh.pfet('xm3', XB2, 'M3', bias='Ib')         # vb3 diode leg
    wire(d, (XB2, Y_PD), (XB2, Y_ND))
    m14 = sh.nfet('xm14', XB2, Y_ND, 'M14', left=True, to_gnd=True)
    sh.diode_tie(m14, XB2)
    node_label(d, (XB2 + 0.15, Y_ND + 0.9), 'vb3')
    sh.pfet('xm2', XR, 'M2', bias='Ib')          # replica / dummy branch
    wire(d, (XR, Y_PD), (XR, Y_CT))
    sh.nfet('xm13', XR, Y_CT, 'M13 (4x)', bias='vb3')
    sh.nfet('xm18', XR, Y_CM, 'M18 (4x)', bias='vb4', to_gnd=True)
    node_label(d, (XR + 0.15, Y_CT + 0.9), 'dm_1')

    # error amp: tail on the left feeds the PMOS pair source bus
    sh.pfet('xm4', XTAIL, 'M4 (2x)', bias='Ib', left=True)
    wire(d, (XTAIL, Y_PD), (XTAIL, Y_SRC), (XPL, Y_SRC))
    wire(d, (XPL, Y_SRC), (XPR, Y_SRC))
    node_label(d, ((XTAIL + XPL) / 2 - 0.4, Y_SRC + 0.15), 'net20')
    l = sh.pfet('xm8', XPL, 'M8', left=True, y=Y_SRC)
    r = sh.pfet('xm9', XPR, 'M9', y=Y_SRC)
    gl, gr = l.absanchors['gate'], r.absanchors['gate']
    wire(d, (gl.x, gl.y), (gl.x - 0.6, gl.y))
    port(d, (gl.x - 0.6, gl.y), 'VINP')
    wire(d, (gr.x, gr.y), (gr.x + 0.6, gr.y))
    port(d, (gr.x + 0.6, gr.y), 'VINN', 'right')
    # PMOS mirror on top (gates inward), cascoded NMOS sinks below
    m5 = sh.pfet('xm5', XCL, 'M5')
    m6 = sh.pfet('xm6', XCR, 'M6', left=True)
    g5, g6 = m5.absanchors['gate'], m6.absanchors['gate']
    wire(d, (g5.x, g5.y), (g6.x, g6.y))          # inward mirror gate bus
    dot(d, (g5.x, g5.y))
    sh.diode_tie(m5, XCL)
    sh.nfet('xm15', XCL, Y_CT, 'M15 (4x)', left=True, bias='vb3')
    sh.nfet('xm19', XCL, Y_CM, 'M19 (8x)', left=True, bias='vb4',
            to_gnd=True)
    sh.nfet('xm16', XCR, Y_CT, 'M16 (4x)', bias='vb3')
    sh.nfet('xm20', XCR, Y_CM, 'M20 (8x)', bias='vb4', to_gnd=True)
    wire(d, (XCL, Y_PD), (XCL, Y_CT))            # voutn column
    wire(d, (XCR, Y_PD), (XCR, Y_CT))            # net10 column
    node_label(d, (XCL - 0.25, Y_CT + 1.3), 'voutn', halign='right')
    node_label(d, (XCR + 0.22, Y_CT + 1.3), 'net10')
    # pair drains join the cascode mid nodes (dm_2 / net106)
    dl, dr = (XPL, Y_SRC - FET_H), (XPR, Y_SRC - FET_H)
    wire(d, dl, (XPL, Y_CM), (XCL, Y_CM)); dot(d, (XCL, Y_CM))
    wire(d, dr, (XPR, Y_CM), (XCR, Y_CM)); dot(d, (XCR, Y_CM))
    node_label(d, (XPL + 0.15, Y_CM + 0.25), 'dm_2')
    node_label(d, (XPR - 0.2, Y_CM + 0.25), 'net106', halign='right')

    # gm2: net7 mirror bias (M7 over M22 diode) + M24/M10/M21 column
    sh.pfet('xm7', X2A, 'M7', bias='Ib')
    wire(d, (X2A, Y_PD), (X2A, Y_ND))            # net7 column
    m22 = sh.nfet('xm22', X2A, Y_ND, 'M22', to_gnd=True)
    sh.diode_tie(m22, X2A)
    m21 = sh.nfet('xm21', X2B, Y_ND, 'M21', left=True, to_gnd=True)
    g22, g21 = m22.absanchors['gate'], m21.absanchors['gate']
    wire(d, (g22.x, g22.y), (g21.x, g21.y))      # inward mirror gate bus
    dot(d, (g22.x, g22.y))
    node_label(d, (X2A + 0.2, Y_ND + 1.3), 'net7')
    sh.pfet('xm24', X2B, 'M24', bias='Ib')       # pulls net1 up
    m10 = sh.pfet('xm10', X2B, 'M10 (lvt)', left=True, y=Y_PD)
    wire(d, (X2B, Y_PD - FET_H), (X2B, Y_ND))    # net12 column
    node_label(d, (X2B + 0.2, Y_ND + 1.3), 'net12')
    g10 = m10.absanchors['gate']
    gate_feed(sh, (XCR, g10.y), g10.x, g10.y)    # net10 -> M10 gate

    # pass device: power PMOS M11, gate driven by net1
    m11 = sh.pfet('xm11', XP, 'M11 (power)', left=True)
    g11 = m11.absanchors['gate']
    gate_feed(sh, (X2B, Y_PD), g11.x, g11.y)     # net1 -> M11 gate
    node_label(d, (X2B + 0.3, Y_PD + 0.2), 'net1')
    wire(d, (XP, Y_PD), (XP, 4.7))               # vout column
    dot(d, (XP, 7.3))
    wire(d, (XP, 7.3), (XP + 1.4, 7.3))
    port(d, (XP + 1.4, 7.3), 'VOUT', 'right')

    # C0 compensation: cascode node net106 -> vout
    dot(d, (XPR, 5.9))
    wire(d, (XPR, 5.9), (XP - 2.3, 5.9))
    sh.cap('xc0', (XP - 2.3, 5.9), (XP - 1.2, 5.9), 'C0')
    wire(d, (XP - 1.2, 5.9), (XP, 5.9))
    dot(d, (XP, 5.9))

    # feedback divider r1/r0, tap at vfb
    sh.res('r1', (XP, 4.7), (XP, 3.0), 'R1\n300k', loc='bot')
    dot(d, (XP, 3.0))
    wire(d, (XP, 3.0), (XP + 1.0, 3.0))
    port(d, (XP + 1.0, 3.0), 'VFB', 'right')
    sh.res('r0', (XP, 3.0), (XP, 1.3), 'R0\n100k', loc='bot')
    wire(d, (XP, 1.3), (XP, Y_GND))

    title(d, (XB0 + XMAX) / 2, Y_VDD + 0.8,
          'Basic LDO — LDO (SKY130, 1.8 V)')
    sh.save(KEY)

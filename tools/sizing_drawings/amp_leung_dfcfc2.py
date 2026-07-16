"""amp_leung_dfcfc2 — Leung DFCFC2, 3-stage damping-factor-control (PMOS gm4).

Sibling of amp_leung_nmcf / amp_leung_dfcfc1.  Netlist deltas: the bias
reference net is renamed net013 -> net1 (so the hub's bias helpers are
inlined here with the right label), the damping branch is a PMOS gm4
xm10 (gate on net050) over a VB4-biased 4x sink xm22 -> node net2, and
the caps are C1 net050 -> VOUT (outer Miller) plus C2 net050 -> net2
(damping cap).  gmf2 feedforward xm12 is kept; tail is 2x.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_sizing_schematics import (   # noqa: E402
    AMP_NL, FET_H, Sheet, TINTS, Y_CM, Y_CT, Y_GND, Y_ND, Y_PD, Y_SRC,
    Y_VDD, dot, gate_feed, node_label, port, rail, tint, title, wire,
)

KEY = 'amp_leung_dfcfc2'


# ─────────────────────────────────────────────────────────────────────────────
def draw():
    sh = Sheet(AMP_NL / 'Leung_DFCFC2_Pin_3')
    d = sh.d
    XB0, XB1, XB2, XR = -0.4, 2.6, 5.8, 9.0      # bias band columns
    XTAIL = 11.8                                 # tail (left of the pair)
    XCL, XPL, XPR, XCR = 14.6, 16.8, 19.0, 21.6  # stage-1 columns
    X2A, X2B = 24.8, 27.4                        # stage 2
    XG4 = 30.4                                   # damping branch (net2)
    X3 = 33.6                                    # output
    XMAX = X3 + 2.4

    tint(d, XB0 - 1.2, Y_GND + .12, XR + 1.1, Y_VDD - .15, TINTS['bias'],
         'bias (net1 / VB3 / VB4)')
    tint(d, XTAIL - 1.1, Y_GND + .12, XCR + 1.2, Y_VDD - .15,
         TINTS['input'], 'stage 1: cascoded input')
    tint(d, X2A - 1.3, Y_GND + .12, X2B + 1.2, Y_VDD - .15, TINTS['mirror'],
         'stage 2')
    tint(d, XG4 - 1.3, Y_GND + .12, XG4 + 1.2, Y_VDD - .15, TINTS['comp'],
         'damping (gm4)')
    tint(d, X3 - 1.3, Y_GND + .12, XMAX - 0.2, Y_VDD - .15, TINTS['out'],
         'stage 3 + feedforward')
    rail(d, XB0 - 1.5, XMAX, Y_VDD, 'VDDA')
    rail(d, XB0 - 1.5, XMAX, Y_GND, 'GNDA')

    # bias band (inlined hub helpers — reference net here is net1)
    m0 = sh.pfet('xm0', XB0, 'M0')
    g0 = m0.absanchors['gate']
    wire(d, m0.absanchors['drain'], (XB0, g0.y))
    sh.diode_tie(m0, XB0)
    node_label(d, (XB0 - 0.25, g0.y - 0.4), 'net1', halign='right')
    sh.isrc('i0', XB0, g0.y - 0.55, Y_GND, 'I0')
    wire(d, (XB0, g0.y), (XB0, g0.y - 0.55))
    # VB3/VB4 generator leg
    sh.pfet('xm1', XB1, 'M1', bias='net1')
    wire(d, (XB1, Y_PD), (XB1, Y_CT))
    sh.nfet('xm13', XB1, Y_CT, 'M13 (4x)', left=True, bias='VB3')
    sh.nfet('xm18', XB1, Y_CM, 'M18 (4x)', left=True, bias='VB4',
            to_gnd=True)
    node_label(d, (XB1 + 0.15, Y_CT + 0.9), 'VB4')
    # VB3 diode leg
    sh.pfet('xm3', XB2, 'M3', bias='net1')
    wire(d, (XB2, Y_PD), (XB2, Y_ND))
    m15 = sh.nfet('xm15', XB2, Y_ND, 'M15', left=True, to_gnd=True)
    sh.diode_tie(m15, XB2)
    node_label(d, (XB2 + 0.15, Y_ND + 0.9), 'VB3')
    # replica/dummy leg
    sh.pfet('xm2', XR, 'M2', bias='net1')
    wire(d, (XR, Y_PD), (XR, Y_CT))
    sh.nfet('xm14', XR, Y_CT, 'M14 (4x)', bias='VB3')
    sh.nfet('xm19', XR, Y_CM, 'M19 (4x)', bias='VB4', to_gnd=True)
    node_label(d, (XR + 0.15, Y_CT + 0.9), 'DM_1')

    # stage 1: tail on the left feeds the pair source bus
    sh.pfet('xm4', XTAIL, 'M4 (2x)', bias='net1', left=True)
    wire(d, (XTAIL, Y_PD), (XTAIL, Y_SRC), (XPL, Y_SRC))
    wire(d, (XPL, Y_SRC), (XPR, Y_SRC))
    l = sh.pfet('xm8', XPL, 'M8', left=True, y=Y_SRC)
    r = sh.pfet('xm9', XPR, 'M9', y=Y_SRC)
    gl, gr = l.absanchors['gate'], r.absanchors['gate']
    wire(d, (gl.x, gl.y), (gl.x - 0.6, gl.y))
    port(d, (gl.x - 0.6, gl.y), 'VINN')
    wire(d, (gr.x, gr.y), (gr.x + 0.6, gr.y))
    port(d, (gr.x + 0.6, gr.y), 'VINP', 'right')
    # mirror on top (gates inward), cascode sinks below, pair joins mid
    m5 = sh.pfet('xm5', XCL, 'M5',)
    m6 = sh.pfet('xm6', XCR, 'M6', left=True)
    g5, g6 = m5.absanchors['gate'], m6.absanchors['gate']
    wire(d, (g5.x, g5.y), (g6.x, g6.y))          # inward mirror gate bus
    dot(d, (g5.x, g5.y))
    sh.diode_tie(m5, XCL)
    sh.nfet('xm16', XCL, Y_CT, 'M16 (4x)', left=True, bias='VB3')
    sh.nfet('xm20', XCL, Y_CM, 'M20 (8x)', left=True, bias='VB4',
            to_gnd=True)
    sh.nfet('xm17', XCR, Y_CT, 'M17 (4x)', bias='VB3')
    sh.nfet('xm21', XCR, Y_CM, 'M21 (8x)', bias='VB4', to_gnd=True)
    wire(d, (XCL, Y_PD), (XCL, Y_CT))            # VOUTN column
    wire(d, (XCR, Y_PD), (XCR, Y_CT))            # net050 column
    node_label(d, (XCL - 0.25, Y_CT + 1.3), 'VOUTN', halign='right')
    node_label(d, (XCR + 0.22, Y_CT + 1.3), 'net050')
    # pair drains join the cascode mid nodes (DM_2 / net063)
    dl, dr = (XPL, Y_SRC - FET_H), (XPR, Y_SRC - FET_H)
    wire(d, dl, (XPL, Y_CM), (XCL, Y_CM)); dot(d, (XCL, Y_CM))
    wire(d, dr, (XPR, Y_CM), (XCR, Y_CM)); dot(d, (XCR, Y_CM))
    node_label(d, (XPL + 0.15, Y_CM + 0.25), 'DM_2')
    node_label(d, (XPR - 0.2, Y_CM + 0.25), 'net063', halign='right')

    # stage 2: gm2 PMOS + NMOS mirror; bias leg xm7 pulls up net049
    m11 = sh.pfet('xm11', X2A, 'M11', left=True)
    wire(d, (X2A, Y_PD), (X2A, Y_ND))            # net043 column
    m23 = sh.nfet('xm23', X2A, Y_ND, 'M23', to_gnd=True)
    sh.diode_tie(m23, X2A)
    m24 = sh.nfet('xm24', X2B, Y_ND, 'M24', left=True, to_gnd=True)
    g23, g24 = m23.absanchors['gate'], m24.absanchors['gate']
    wire(d, (g23.x, g23.y), (g24.x, g24.y))      # inward mirror gate bus
    dot(d, (g23.x, g23.y))
    sh.pfet('xm7', X2B, 'M7', bias='net1')
    wire(d, (X2B, Y_PD), (X2B, Y_ND))            # net049 column
    node_label(d, (X2A - 0.25, Y_ND + 1.3), 'net043', halign='right')
    node_label(d, (X2B + 0.25, Y_ND + 1.3), 'net049')

    # damping branch: PMOS gm4 xm10 over a VB4-biased sink xm22 -> net2
    m10 = sh.pfet('xm10', XG4, 'M10 (gm4)', left=True)
    sh.nfet('xm22', XG4, Y_ND, 'M22 (4x)', bias='VB4', to_gnd=True)
    wire(d, (XG4, Y_PD), (XG4, Y_ND))            # net2 column
    node_label(d, (XG4 + 0.25, Y_ND + 1.3), 'net2')

    # stage 3: gm3 NMOS + gmf2 PMOS feedforward into VOUT
    m12 = sh.pfet('xm12', X3, 'M12 (gmf2)', left=True)
    m25 = sh.nfet('xm25', X3, Y_ND, 'M25 (gm3)', left=True, to_gnd=True)
    wire(d, (X3, Y_PD), (X3, Y_ND))              # VOUT column
    dot(d, (X3, 5.8))
    wire(d, (X3, 5.8), (XMAX - 0.6, 5.8))
    port(d, (XMAX - 0.6, 5.8), 'VOUT', 'right')

    # signal gate feeds (all target gates face left, so feeds never cross
    # their device bodies); net050 drives gm2, gm4 and gmf2
    g11 = m11.absanchors['gate']
    gate_feed(sh, (XCR, 7.5), g11.x, g11.y)      # net050 -> M11 gate
    g10 = m10.absanchors['gate']
    gate_feed(sh, (XCR, 7.15), g10.x, g10.y)     # net050 -> M10 gate
    g12 = m12.absanchors['gate']
    gate_feed(sh, (XCR, 6.8), g12.x, g12.y)      # net050 -> M12 gate
    g25 = m25.absanchors['gate']
    gate_feed(sh, (X2B, 4.4), g25.x, g25.y)      # net049 -> M25 gate

    # compensation: outer Miller C1 net050 -> VOUT (plates pinned between
    # the X2B and XG4 columns), damping cap C2 net050 -> net2
    wire(d, (XCR, 6.3), (X2B + 0.7, 6.3))
    sh.cap('c1', (X2B + 0.7, 6.3), (XG4 - 0.9, 6.3), 'C1', loc='bot')
    wire(d, (XG4 - 0.9, 6.3), (X3, 6.3))
    dot(d, (XCR, 6.3)); dot(d, (X3, 6.3))
    sh.cap('c2', (XCR, 5.4), (XG4 - 0.9, 5.4), 'C2')
    wire(d, (XG4 - 0.9, 5.4), (XG4, 5.4))
    dot(d, (XCR, 5.4)); dot(d, (XG4, 5.4))

    title(d, (XB0 + XMAX) / 2, Y_VDD + 0.8,
          'Leung DFCFC2 — 3-stage damping-factor-control, PMOS gm4 '
          '(SKY130, 1.8 V)')
    sh.save(KEY)

"""amp_peng_acbc — Peng ACBC, 3-stage amp with AC-boosting compensation.

Same NMC-family skeleton as the Leung reference (net013/VB3/VB4 bias band,
cascoded PMOS-input first stage, LOAD2 mirror second stage, gm3 + gmf2
output) plus the ACBC branch: C1 does not return straight to net049 —
it lands on net1, a diode-loaded auxiliary leg (M8 bias pull-up, M59 ma1
diode, M24 gm4 sink driven from net043).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_sizing_schematics import (   # noqa: E402
    AMP_NL, FET_H, Sheet, TINTS, Y_CM, Y_CT, Y_GND, Y_ND, Y_PD, Y_SRC,
    Y_VDD, bias_column, dot, gate_feed, node_label, port, rail,
    replica_column, tint, title, vb3_diode, vb_gen, wire,
)

KEY = 'amp_peng_acbc'


# ─────────────────────────────────────────────────────────────────────────────
def draw():
    sh = Sheet(AMP_NL / 'Peng_ACBC_Pin_3')
    d = sh.d
    XB0, XB1, XB2, XR = -0.4, 2.6, 5.8, 9.0      # bias band columns
    XTAIL = 11.8                                 # tail (left of the pair)
    XCL, XPL, XPR, XCR = 14.6, 16.8, 19.0, 21.6  # stage-1 columns
    X2A, X2B = 24.8, 27.4                        # stage 2
    XA1, XA2 = 30.8, 33.2                        # ACBC branch (net1)
    X3 = 37.0                                    # output
    XMAX = X3 + 2.4

    tint(d, XB0 - 1.2, Y_GND + .12, XR + 1.1, Y_VDD - .15, TINTS['bias'],
         'bias (net013 / VB3 / VB4)')
    tint(d, XTAIL - 1.1, Y_GND + .12, XCR + 1.2, Y_VDD - .15,
         TINTS['input'], 'stage 1: cascoded input')
    tint(d, X2A - 1.3, Y_GND + .12, X2B + 1.2, Y_VDD - .15, TINTS['mirror'],
         'stage 2')
    tint(d, XA1 - 1.3, Y_GND + .12, XA2 + 1.2, Y_VDD - .15, TINTS['comp'],
         'ACBC branch (ma1 / gm4)')
    tint(d, X3 - 1.3, Y_GND + .12, XMAX - 0.2, Y_VDD - .15, TINTS['out'],
         'stage 3 + feedforward')
    rail(d, XB0 - 1.5, XMAX, Y_VDD, 'VDDA')
    rail(d, XB0 - 1.5, XMAX, Y_GND, 'GNDA')

    # bias band (same structure as the Leung reference)
    bias_column(sh, XB0)
    vb_gen(sh, XB1, 'xm1', 'M1', ('xm13', 'xm18'), ('M13 (4x)', 'M18 (4x)'))
    vb3_diode(sh, XB2, 'xm3', 'M3', 'xm15', 'M15')
    replica_column(sh, XR, 'xm2', 'M2', ('xm14', 'xm19'),
                   ('M14 (4x)', 'M19 (4x)'))

    # stage 1: tail on the left feeds the pair source bus
    sh.pfet('xm4', XTAIL, 'M4 (2x)', bias='net013', left=True)
    wire(d, (XTAIL, Y_PD), (XTAIL, Y_SRC), (XPL, Y_SRC))
    wire(d, (XPL, Y_SRC), (XPR, Y_SRC))
    l = sh.pfet('xm9', XPL, 'M9', left=True, y=Y_SRC)
    r = sh.pfet('xm10', XPR, 'M10', y=Y_SRC)
    gl, gr = l.absanchors['gate'], r.absanchors['gate']
    wire(d, (gl.x, gl.y), (gl.x - 0.6, gl.y))
    port(d, (gl.x - 0.6, gl.y), 'VINN')
    wire(d, (gr.x, gr.y), (gr.x + 0.6, gr.y))
    port(d, (gr.x + 0.6, gr.y), 'VINP', 'right')
    # mirror on top (gates inward), cascode sinks below, pair joins mid
    m5 = sh.pfet('xm5', XCL, 'M5')
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

    # stage 2: gm2 PMOS + LOAD2 NMOS mirror; bias leg xm7 pulls up net049
    m11 = sh.pfet('xm11', X2A, 'M11\n(gm2)', left=True)
    wire(d, (X2A, Y_PD), (X2A, Y_ND))            # net043 column
    m22 = sh.nfet('xm22', X2A, Y_ND, 'M22', to_gnd=True)
    sh.diode_tie(m22, X2A)
    m23 = sh.nfet('xm23', X2B, Y_ND, 'M23', left=True, to_gnd=True)
    g22, g23 = m22.absanchors['gate'], m23.absanchors['gate']
    wire(d, (g22.x, g22.y), (g23.x, g23.y))      # inward mirror gate bus
    dot(d, (g22.x, g22.y))
    sh.pfet('xm7', X2B, 'M7', bias='net013')
    wire(d, (X2B, Y_PD), (X2B, Y_ND))            # net049 column
    node_label(d, (X2A - 0.25, Y_ND + 1.3), 'net043', halign='right')
    node_label(d, (X2B + 0.25, Y_ND + 1.3), 'net049')

    # ACBC branch: net1 = M59 ma1 diode || M8 (net013 leg) over M24 (gm4)
    m59 = sh.pfet('xm59', XA1, 'M59')
    sh.diode_tie(m59, XA1)
    sh.pfet('xm8', XA2, 'M8', bias='net013')
    wire(d, (XA2, Y_PD), (XA1, Y_PD))            # net1 top tie
    dot(d, (XA1, Y_PD))
    wire(d, (XA1, Y_PD), (XA1, Y_ND))            # net1 column
    m24 = sh.nfet('xm24', XA1, Y_ND, 'M24 (gm4)', left=True, to_gnd=True)
    node_label(d, (XA1 + 0.25, Y_ND + 1.3), 'net1')

    # stage 3: gm3 NMOS + gmf2 PMOS feedforward into VOUT
    m12 = sh.pfet('xm12', X3, 'M12 (gmf2)', left=True)
    m25 = sh.nfet('xm25', X3, Y_ND, 'M25 (gm3)', left=True, to_gnd=True)
    wire(d, (X3, Y_PD), (X3, Y_ND))              # VOUT column
    dot(d, (X3, 5.8))
    wire(d, (X3, 5.8), (XMAX - 0.6, 5.8))
    port(d, (XMAX - 0.6, 5.8), 'VOUT', 'right')

    # signal gate feeds (target gates face left, so feeds never cross
    # their device bodies)
    g11 = m11.absanchors['gate']
    gate_feed(sh, (XCR, 7.5), g11.x, g11.y)      # net050 -> M11 gate
    g12 = m12.absanchors['gate']
    gate_feed(sh, (XCR, 7.0), g12.x, g12.y)      # net050 -> M12 gate
    g25 = m25.absanchors['gate']
    gate_feed(sh, (X2B, 4.4), g25.x, g25.y)      # net049 -> M25 gate
    g24 = m24.absanchors['gate']
    gate_feed(sh, (X2A, 4.0), g24.x, g24.y)      # net043 -> M24 gate

    # compensation: C0 nested Miller, C1 into the ACBC net1 branch
    sh.cap('c0', (XCR, 6.3), (X3 - 0.9, 6.3), 'C0')
    wire(d, (X3 - 0.9, 6.3), (X3, 6.3))
    dot(d, (XCR, 6.3)); dot(d, (X3, 6.3))
    sh.cap('c1', (X2B, 5.2), (XA1 - 0.9, 5.2), 'C1')
    wire(d, (XA1 - 0.9, 5.2), (XA1, 5.2))
    dot(d, (X2B, 5.2)); dot(d, (XA1, 5.2))

    title(d, (XB0 + XMAX) / 2, Y_VDD + 0.8,
          'Peng ACBC — 3-stage amp, AC-boosting compensation '
          '(SKY130, 1.8 V)')
    sh.save(KEY)

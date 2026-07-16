"""amp_hoilee_affc — Hoi Lee AFFC, 3-stage active-feedback frequency comp.

Same NMC-family skeleton as the Leung reference (bias band, cascoded
input stage, gm2 second stage, gm3+gmf2 output) plus the AFFC block on
the far right: the HSBCM PMOS mirror xm59/xm62 sits on a second PMOS
row (y=Y_SRC, sources wired to VDDA) over the gma cascode legs
xm60/xm61 (net2 diode branch) and xm63/xm64 (injecting into net050);
C1 closes the active-feedback loop from VOUT into net1 (xm63 source).
Stage 2 swaps the Leung column order (bias leg xm7 on the left) so the
gm2 gate feed and the net013 stub never collide.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_sizing_schematics import (   # noqa: E402
    AMP_NL, FET_H, Sheet, TINTS, Y_CM, Y_CT, Y_GND, Y_ND, Y_PD, Y_SRC,
    Y_VDD, bias_column, dot, gate_feed, node_label, port, rail,
    replica_column, tint, title, vb3_diode, vb_gen, wire,
)

KEY = 'amp_hoilee_affc'


# ─────────────────────────────────────────────────────────────────────────────
def draw():
    sh = Sheet(AMP_NL / 'HoiLee_AFFC_Pin_3')
    d = sh.d
    XB0, XB1, XB2, XR = -0.4, 2.6, 5.8, 9.0      # bias band columns
    XTAIL = 11.8                                 # tail (left of the pair)
    XCL, XPL, XPR, XCR = 14.6, 16.8, 19.0, 21.6  # stage-1 columns
    X2A, X2B = 24.8, 27.4                        # stage 2 (bias leg | gm2)
    X3 = 30.6                                    # output stage
    XGB, XGA = 34.0, 38.2                        # AFFC: gma legs + HSBCM
    XMAX = XGA + 2.4
    XC1 = X3 + 0.9                               # C1 down-leg into net1
    Y_BUS = Y_SRC - FET_H                        # net050 distribution (6.33)

    tint(d, XB0 - 1.2, Y_GND + .12, XR + 1.1, Y_VDD - .15, TINTS['bias'],
         'bias (net013 / VB3 / VB4)')
    tint(d, XTAIL - 1.1, Y_GND + .12, XCR + 1.2, Y_VDD - .15,
         TINTS['input'], 'stage 1: cascoded input')
    tint(d, X2A - 1.3, Y_GND + .12, X2B + 1.2, Y_VDD - .15, TINTS['mirror'],
         'stage 2')
    tint(d, X3 - 1.3, Y_GND + .12, X3 + 2.1, Y_VDD - .15, TINTS['out'],
         'stage 3 + gmf2')
    tint(d, X3 + 2.25, Y_GND + .12, XGA + 1.9, Y_VDD - .15, TINTS['comp'],
         'active feedback (gma) + HSBCM')
    rail(d, XB0 - 1.5, XMAX, Y_VDD, 'VDDA')
    rail(d, XB0 - 1.5, XMAX, Y_GND, 'GNDA')

    # bias band
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
    node_label(d, (XCR + 0.22, Y_CT + 1.55), 'net050')
    dl, dr = (XPL, Y_SRC - FET_H), (XPR, Y_SRC - FET_H)
    wire(d, dl, (XPL, Y_CM), (XCL, Y_CM)); dot(d, (XCL, Y_CM))
    wire(d, dr, (XPR, Y_CM), (XCR, Y_CM)); dot(d, (XCR, Y_CM))
    node_label(d, (XPL + 0.15, Y_CM + 0.25), 'DM_2')
    node_label(d, (XPR - 0.2, Y_CM + 0.25), 'net063', halign='right')

    # stage 2: bias leg xm7 pulls up net049 (left); gm2 + NMOS mirror right
    sh.pfet('xm7', X2A, 'M7', bias='net013', left=True)
    wire(d, (X2A, Y_PD), (X2A, Y_ND))            # net049 column
    m23 = sh.nfet('xm23', X2A, Y_ND, 'M23', to_gnd=True)
    m11 = sh.pfet('xm11', X2B, 'M11 (gm2)', left=True)
    wire(d, (X2B, Y_PD), (X2B, Y_ND))            # net043 column
    m22 = sh.nfet('xm22', X2B, Y_ND, 'M22', left=True, to_gnd=True)
    sh.diode_tie(m22, X2B)
    g23, g22 = m23.absanchors['gate'], m22.absanchors['gate']
    wire(d, (g23.x, g23.y), (g22.x, g22.y))      # inward mirror gate bus
    dot(d, (g22.x, g22.y))
    node_label(d, (X2A - 0.25, Y_ND + 1.3), 'net049', halign='right')
    node_label(d, (X2B + 0.25, Y_ND + 1.3), 'net043')

    # stage 3: gm3 NMOS + gmf2 PMOS feedforward into VOUT
    m12 = sh.pfet('xm12', X3, 'M12 (gmf2)', left=True)
    m25 = sh.nfet('xm25', X3, Y_ND, 'M25 (gm3)', left=True, to_gnd=True)
    wire(d, (X3, Y_PD), (X3, Y_ND))              # VOUT column
    dot(d, (X3, 5.9))
    wire(d, (X3, 5.9), (XMAX - 0.6, 5.9))
    port(d, (XMAX - 0.6, 5.9), 'VOUT', 'right')

    # AFFC block: HSBCM PMOS mirror on a second PMOS row over the gma legs
    m62 = sh.pfet('xm62', XGB, 'M62', y=Y_SRC)
    m59 = sh.pfet('xm59', XGA, 'M59', left=True, y=Y_SRC)
    wire(d, (XGB, Y_SRC), (XGB, Y_VDD))          # sources up to VDDA
    wire(d, (XGA, Y_SRC), (XGA, Y_VDD))
    g62, g59 = m62.absanchors['gate'], m59.absanchors['gate']
    wire(d, (g62.x, g62.y), (g59.x, g59.y))      # inward mirror gate bus
    dot(d, (g59.x, g59.y))
    sh.diode_tie(m59, XGA)                       # xm59 diode -> net2
    wire(d, (XGB, Y_SRC - FET_H), (XGB, Y_CT))   # net050 injection column
    wire(d, (XGA, Y_SRC - FET_H), (XGA, Y_CT))   # net2 column
    sh.nfet('xm63', XGB, Y_CT, 'M63 (gma)', left=True, bias='VB3')
    sh.nfet('xm64', XGB, Y_CM, 'M64 (4x)', left=True, bias='VB4',
            to_gnd=True)
    sh.nfet('xm60', XGA, Y_CT, 'M60 (gma)', bias='VB3')
    sh.nfet('xm61', XGA, Y_CM, 'M61 (4x)', bias='VB4', to_gnd=True)
    node_label(d, (XGA + 0.25, 5.25), 'net2')
    node_label(d, (XGA + 0.22, Y_CM + 0.25), 'net3')
    node_label(d, (XGB + 0.2, Y_CM + 0.22), 'net1')

    # net050 bus: stage-1 output -> gm2 gate, gmf2 gate, gma injection leg
    g11, g12 = m11.absanchors['gate'], m12.absanchors['gate']
    wire(d, (XCR, Y_BUS), (XGB, Y_BUS))
    dot(d, (XCR, Y_BUS)); dot(d, (XGB, Y_BUS))
    wire(d, (g11.x, Y_BUS), (g11.x, g11.y)); dot(d, (g11.x, Y_BUS))
    wire(d, (g12.x, Y_BUS), (g12.x, g12.y)); dot(d, (g12.x, Y_BUS))

    # net049 -> gm3 gate (faces left, feed never crosses the body)
    g25 = m25.absanchors['gate']
    gate_feed(sh, (X2A, 4.4), g25.x, g25.y)

    # compensation caps: C0 net049 -> VOUT, C1 VOUT -> net1 (AFFC)
    dot(d, (X2A, 5.2))
    wire(d, (X2A, 5.2), (X3 - 2.3, 5.2))
    sh.cap('c0', (X3 - 2.3, 5.2), (X3 - 0.9, 5.2), 'C0')
    wire(d, (X3 - 0.9, 5.2), (X3, 5.2))
    dot(d, (X3, 5.2))
    dot(d, (X3, 5.45))
    sh.cap('c1', (X3, 5.45), (XC1, 5.45), 'C1', loc='bot')
    wire(d, (XC1, 5.45), (XC1, Y_CM), (XGB, Y_CM))
    dot(d, (XGB, Y_CM))

    title(d, (XB0 + XMAX) / 2, Y_VDD + 0.8,
          'Hoi Lee AFFC — 3-stage active-feedback frequency compensation '
          '(SKY130, 1.8 V)')
    sh.save(KEY)

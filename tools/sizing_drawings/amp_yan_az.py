"""amp_yan_az — Yan AZ, 3-stage amp with active-zero compensation.

Same VB1-referenced skeleton as Qu2017 (xm0 diode + I0, xm1/xm19 -> VB4,
xm3 -> net078 with the R0/R1 pull-downs onto the gm5 diodes xm16/xm17
that generate the cascode gates net077/net082; gm8 cascodes xm14/xm15).
The zero network is smaller: gm2 (xm11) output net094 sees the series
R2/C1 arm (-> net051) and the local shunt device xm22 (gmb1, gate
net051); net094 also drives xm23 (gmb2) whose drain net057 is pulled up
by xm67 — a third slave of the VOUTN mirror — and gates the output
device xm18 (gm3).  C0 is the Miller cap net063 -> VOUT; xm13 is the
gmf2 feedforward.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_sizing_schematics import (   # noqa: E402
    AMP_NL, FET_H, Sheet, TINTS, Y_CM, Y_CT, Y_GND, Y_ND, Y_PD, Y_SRC,
    Y_VDD, dot, gate_feed, node_label, port, rail, tint, title, wire,
)

KEY = 'amp_yan_az'


# VB1-flavoured bias columns (hub helpers hardcode 'net013')
def _vb1_column(sh, x):
    m = sh.pfet('xm0', x, 'M0')
    g = m.absanchors['gate']
    wire(sh.d, m.absanchors['drain'], (x, g.y))
    sh.diode_tie(m, x)
    node_label(sh.d, (x - 0.25, g.y - 0.4), 'VB1', halign='right')
    sh.isrc('i0', x, g.y - 0.55, Y_GND, 'I0')
    wire(sh.d, (x, g.y), (x, g.y - 0.55))


def _vb4_column(sh, x):
    """xm1 (VB1 leg) over the NMOS diode xm19 -> VB4."""
    sh.pfet('xm1', x, 'M1', bias='VB1')
    wire(sh.d, (x, Y_PD), (x, Y_ND))
    e = sh.nfet('xm19', x, Y_ND, 'M19', to_gnd=True)
    sh.diode_tie(e, x)
    node_label(sh.d, (x + 0.15, Y_ND + 0.9), 'VB4')


def _casc_bias(sh, xa, xb):
    """xm3 -> net078; R0/R1 drop onto the gm5 diodes xm16/xm17,
    generating the cascode gate voltages net077/net082."""
    d = sh.d
    sh.pfet('xm3', xa, 'M3\n(4x)', bias='VB1')
    wire(d, (xa, Y_PD), (xa, 7.0))
    wire(d, (xa, 7.0), (xb, 7.0))
    dot(d, (xa, 7.0))
    node_label(d, (xa + 0.2, 7.15), 'net078')
    sh.res('r0', (xa, 7.0), (xa, 4.6), 'R0', loc='bot')
    wire(d, (xa, 4.6), (xa, Y_ND))
    sh.res('r1', (xb, 7.0), (xb, 4.6), 'R1', loc='bot')
    wire(d, (xb, 4.6), (xb, Y_ND))
    sh.nfet('xm16', xa, Y_ND, 'M16', left=True, bias='DM_2', to_gnd=True)
    sh.nfet('xm17', xb, Y_ND, 'M17', bias='net063', to_gnd=True)
    node_label(d, (xa + 0.2, Y_ND + 0.35), 'net077')
    node_label(d, (xb + 0.2, Y_ND + 0.35), 'net082')


# ─────────────────────────────────────────────────────────────────────────────
def draw():
    sh = Sheet(AMP_NL / 'Yan_AZ_Pin_3')
    d = sh.d
    XB0, XB1 = -0.4, 2.0                         # VB1 / VB4 columns
    XN1, XN2 = 5.4, 8.2                          # cascode-bias branch
    XTAIL = 11.0                                 # tail (left of the pair)
    XCL, XPL, XPR, XCR = 13.8, 16.0, 18.2, 20.8  # stage-1 columns
    X2A = 23.6                                   # stage 2 (gm2 / gmb1)
    XRC = 26.6                                   # R2 / C1 arm (net051)
    X2B = 29.2                                   # xm67 / gmb2 (net057)
    X3 = 32.2                                    # output
    XMAX = X3 + 2.4

    tint(d, XB0 - 1.2, Y_GND + .12, XN2 + 1.1, Y_VDD - .15, TINTS['bias'],
         'bias (VB1 / VB4) + cascode bias R0/R1')
    tint(d, XTAIL - 1.1, Y_GND + .12, XCR + 1.2, Y_VDD - .15,
         TINTS['input'], 'stage 1: cascoded input')
    tint(d, X2A - 1.3, Y_GND + .12, X2B + 1.2, Y_VDD - .15, TINTS['comp'],
         'stage 2 + active zero (gmb1/gmb2)')
    tint(d, X3 - 1.3, Y_GND + .12, XMAX - 0.2, Y_VDD - .15, TINTS['out'],
         'stage 3 + feedforward')
    rail(d, XB0 - 1.5, XMAX, Y_VDD, 'VDDA')
    rail(d, XB0 - 1.5, XMAX, Y_GND, 'GNDA')

    # bias band
    _vb1_column(sh, XB0)
    _vb4_column(sh, XB1)
    _casc_bias(sh, XN1, XN2)

    # stage 1: tail on the left feeds the pair source bus
    sh.pfet('xm2', XTAIL, 'M2\n(2x)', bias='VB1', left=True)
    wire(d, (XTAIL, Y_PD), (XTAIL, Y_SRC), (XPL, Y_SRC))
    wire(d, (XPL, Y_SRC), (XPR, Y_SRC))
    node_label(d, (XTAIL + 0.6, Y_SRC + 0.15), 'net019')
    l = sh.pfet('xm9', XPL, 'M9', left=True, y=Y_SRC)
    r = sh.pfet('xm10', XPR, 'M10', y=Y_SRC)
    gl, gr = l.absanchors['gate'], r.absanchors['gate']
    wire(d, (gl.x, gl.y), (gl.x - 0.6, gl.y))
    port(d, (gl.x - 0.6, gl.y), 'VINN')
    wire(d, (gr.x, gr.y), (gr.x + 0.6, gr.y))
    port(d, (gr.x + 0.6, gr.y), 'VINP', 'right')
    # PMOS mirror load on top (gates inward), gm8 cascodes below
    m4 = sh.pfet('xm4', XCL, 'M4')
    m5 = sh.pfet('xm5', XCR, 'M5', left=True)
    g4, g5 = m4.absanchors['gate'], m5.absanchors['gate']
    wire(d, (g4.x, g4.y), (g5.x, g5.y))          # inward mirror gate bus
    dot(d, (g4.x, g4.y))
    sh.diode_tie(m4, XCL)
    sh.nfet('xm14', XCL, Y_CT, 'M14\n(gm8)', left=True, bias='net077')
    sh.nfet('xm20', XCL, Y_CM, 'M20', left=True, bias='VB4', to_gnd=True)
    sh.nfet('xm15', XCR, Y_CT, 'M15\n(gm8)', bias='net082')
    sh.nfet('xm21', XCR, Y_CM, 'M21', left=True, bias='VB4', to_gnd=True)
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

    # stage 2: gm2 PMOS over the gmb1 shunt device xm22
    m11 = sh.pfet('xm11', X2A, 'M11\n(gm2)', left=True)
    wire(d, (X2A, Y_PD), (X2A, Y_ND))            # net094 column
    sh.nfet('xm22', X2A, Y_ND, 'M22\n(gmb1)', left=True, bias='net051',
            to_gnd=True)
    node_label(d, (X2A + 0.22, Y_ND + 1.3), 'net094')
    # series zero arm: R2 -> net051 -> C1 to ground
    sh.res('r2', (X2A, 6.6), (XRC, 6.6), 'R2')
    dot(d, (X2A, 6.6))
    node_label(d, (XRC + 0.15, 6.75), 'net051')
    sh.cap('c1', (XRC, 6.6), (XRC, Y_GND), 'C1', loc='bot')

    # gmb2 leg: net094 -> xm23; net057 pulled up by the VOUTN slave xm67
    sh.pfet('xm67', X2B, 'M67', bias='VOUTN', left=True)
    wire(d, (X2B, Y_PD), (X2B, Y_ND))            # net057 column
    m23 = sh.nfet('xm23', X2B, Y_ND, 'M23\n(gmb2)', left=True, to_gnd=True)
    node_label(d, (X2B - 0.25, 7.3), 'net057', halign='right')

    # stage 3: gm3 NMOS + gmf2 PMOS feedforward into VOUT
    m13 = sh.pfet('xm13', X3, 'M13 (gmf2)', left=True)
    m18 = sh.nfet('xm18', X3, Y_ND, 'M18 (gm3)', left=True, to_gnd=True)
    wire(d, (X3, Y_PD), (X3, Y_ND))              # VOUT column

    # signal gate feeds (all target gates face left)
    g11 = m11.absanchors['gate']
    gate_feed(sh, (XCR, 7.6), g11.x, g11.y)      # net050 -> M11 gate
    g13 = m13.absanchors['gate']
    gate_feed(sh, (XCR, 7.1), g13.x, g13.y)      # net050 -> M13 gate
    g23 = m23.absanchors['gate']
    gate_feed(sh, (X2A, 4.4), g23.x, g23.y)      # net094 -> M23 gate
    g18 = m18.absanchors['gate']
    gate_feed(sh, (X2B, 4.7), g18.x, g18.y)      # net057 -> M18 gate

    # Miller cap net063 -> VOUT (cap body kept right of the gmb2 leg)
    wire(d, (XPR, 6.1), (X3 - 2.5, 6.1))
    sh.cap('c0', (X3 - 2.5, 6.1), (X3 - 0.9, 6.1), 'C0')
    wire(d, (X3 - 0.9, 6.1), (X3, 6.1))
    dot(d, (XPR, 6.1)); dot(d, (X3, 6.1))
    wire(d, (X3, 6.1), (XMAX - 0.6, 6.1))
    port(d, (XMAX - 0.6, 6.1), 'VOUT', 'right')

    title(d, (XB0 + XMAX) / 2, Y_VDD + 0.8,
          'Yan AZ — 3-stage amp, active-zero compensation '
          '(SKY130, 1.8 V)')
    sh.save(KEY)

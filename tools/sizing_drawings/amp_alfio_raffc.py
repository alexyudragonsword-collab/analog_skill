"""amp_alfio_raffc — Alfio RAFFC, 3-stage reversed active-feedback comp.

Netlist quirks (vs the Leung NMCF reference):
- the bias diode / distribution node is net1; the name net013 is reused
  here as the SIGNAL node at the stage-2 output (xm10 gm2 PMOS over the
  xm59 VB4-biased NMOS sink);
- the stage-1 cascodes xm15/xm16 are the gmb (active-feedback) devices;
- stage 3 is a PMOS gm3 (xm7, gate = net013) into the xm21/xm22 LOAD2
  NMOS mirror, whose output leg pulls VOUT; feedforward is the gmf PMOS
  xm11 (gate = net050);
- caps: C1 net050 -> net013 (around gm2) and C0 net063 -> VOUT (from the
  right cascode source node — the reversed feedback tap).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_sizing_schematics import (   # noqa: E402
    AMP_NL, FET_H, Sheet, TINTS, Y_CM, Y_CT, Y_GND, Y_ND, Y_PD, Y_SRC,
    Y_VDD, dot, gate_feed, node_label, port, rail, tint, title, wire,
)

KEY = 'amp_alfio_raffc'


# net1-flavoured bias-band columns (hub helpers hardcode 'net013')
def _bias_column(sh, x):
    m = sh.pfet('xm0', x, 'M0')
    g = m.absanchors['gate']
    wire(sh.d, m.absanchors['drain'], (x, g.y))
    sh.diode_tie(m, x)
    node_label(sh.d, (x - 0.25, g.y - 0.4), 'net1', halign='right')
    sh.isrc('i0', x, g.y - 0.55, Y_GND, 'I0')
    wire(sh.d, (x, g.y), (x, g.y - 0.55))


def _vb_gen(sh, x, top_leg, top_lbl, names, labels):
    sh.pfet(top_leg, x, top_lbl, bias='net1')
    wire(sh.d, (x, Y_PD), (x, Y_CT))
    sh.nfet(names[0], x, Y_CT, labels[0], left=True, bias='VB3')
    sh.nfet(names[1], x, Y_CM, labels[1], left=True, bias='VB4',
            to_gnd=True)
    node_label(sh.d, (x + 0.15, Y_CT + 0.9), 'VB4')


def _vb3_diode(sh, x, top_leg, top_lbl, name, label):
    sh.pfet(top_leg, x, top_lbl, bias='net1')
    wire(sh.d, (x, Y_PD), (x, Y_ND))
    e = sh.nfet(name, x, Y_ND, label, left=True, to_gnd=True)
    sh.diode_tie(e, x)
    node_label(sh.d, (x + 0.15, Y_ND + 0.9), 'VB3')


def _replica_column(sh, x, top_leg, top_lbl, names, labels):
    sh.pfet(top_leg, x, top_lbl, bias='net1')
    wire(sh.d, (x, Y_PD), (x, Y_CT))
    sh.nfet(names[0], x, Y_CT, labels[0], bias='VB3')
    sh.nfet(names[1], x, Y_CM, labels[1], bias='VB4', to_gnd=True)
    node_label(sh.d, (x + 0.15, Y_CT + 0.9), 'DM_1')


# ─────────────────────────────────────────────────────────────────────────────
def draw():
    sh = Sheet(AMP_NL / 'Alfio_RAFFC_Pin_3')
    d = sh.d
    XB0, XB1, XB2, XR = -0.4, 2.6, 5.8, 9.0      # bias band columns
    XTAIL = 11.8                                 # tail (left of the pair)
    # wider stage-1/2/3 pitch than the Leung sheet: the (8x)/(gm*) label
    # suffixes on M5/M59/M10/M7 need the extra room
    XCL, XPL, XPR, XCR = 15.8, 18.0, 20.2, 22.8  # stage-1 columns
    X2A = 26.8                                   # stage 2 (net013)
    X2B = 30.0                                   # gm3 + mirror diode
    X3 = 33.2                                    # output
    XMAX = X3 + 2.6

    tint(d, XB0 - 1.2, Y_GND + .12, XR + 1.1, Y_VDD - .15, TINTS['bias'],
         'bias (net1 / VB3 / VB4)')
    tint(d, XTAIL - 1.1, Y_GND + .12, XCR + 1.2, Y_VDD - .15,
         TINTS['input'], 'stage 1: cascoded input (gmb cascodes)')
    tint(d, X2A - 1.9, Y_GND + .12, X2A + 1.2, Y_VDD - .15, TINTS['mirror'],
         'stage 2')
    tint(d, X2B - 1.4, Y_GND + .12, XMAX - 0.2, Y_VDD - .15, TINTS['out'],
         'stage 3 + feedforward')
    rail(d, XB0 - 1.5, XMAX, Y_VDD, 'VDDA')
    rail(d, XB0 - 1.5, XMAX, Y_GND, 'GNDA')

    # bias band (reference node net1)
    _bias_column(sh, XB0)
    _vb_gen(sh, XB1, 'xm1', 'M1', ('xm12', 'xm17'), ('M12 (4x)', 'M17 (4x)'))
    _vb3_diode(sh, XB2, 'xm3', 'M3', 'xm14', 'M14')
    _replica_column(sh, XR, 'xm2', 'M2', ('xm13', 'xm18'),
                    ('M13 (4x)', 'M18 (4x)'))

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
    # mirror on top (gates inward), gmb cascodes below, pair joins mid
    m5 = sh.pfet('xm5', XCL, 'M5 (8x)')
    m6 = sh.pfet('xm6', XCR, 'M6 (8x)', left=True)
    g5, g6 = m5.absanchors['gate'], m6.absanchors['gate']
    wire(d, (g5.x, g5.y), (g6.x, g6.y))          # inward mirror gate bus
    dot(d, (g5.x, g5.y))
    sh.diode_tie(m5, XCL)
    sh.nfet('xm15', XCL, Y_CT, 'M15 (gmb)', left=True, bias='VB3')
    sh.nfet('xm19', XCL, Y_CM, 'M19 (8x)', left=True, bias='VB4',
            to_gnd=True)
    sh.nfet('xm16', XCR, Y_CT, 'M16 (gmb)', bias='VB3')
    sh.nfet('xm20', XCR, Y_CM, 'M20 (8x)', bias='VB4', to_gnd=True)
    wire(d, (XCL, Y_PD), (XCL, Y_CT))            # VOUTN column
    wire(d, (XCR, Y_PD), (XCR, Y_CT))            # net050 column
    node_label(d, (XCL - 0.25, Y_CT + 1.3), 'VOUTN', halign='right')
    node_label(d, (XCR - 0.25, Y_CT + 1.3), 'net050', halign='right')
    # pair drains join the cascode mid nodes (DM_2 / net063)
    dl, dr = (XPL, Y_SRC - FET_H), (XPR, Y_SRC - FET_H)
    wire(d, dl, (XPL, Y_CM), (XCL, Y_CM)); dot(d, (XCL, Y_CM))
    wire(d, dr, (XPR, Y_CM), (XCR, Y_CM)); dot(d, (XCR, Y_CM))
    node_label(d, (XPL + 0.15, Y_CM + 0.25), 'DM_2')
    node_label(d, (XPR - 0.2, Y_CM + 0.25), 'net063', halign='right')

    # stage 2: gm2 PMOS over the VB4-biased NMOS sink -> node net013
    # (xm59 faces left so its label lands right, clear of xm20's VB4 stub)
    m10 = sh.pfet('xm10', X2A, 'M10 (gm2)', left=True)
    wire(d, (X2A, Y_PD), (X2A, Y_ND))            # net013 column
    sh.nfet('xm59', X2A, Y_ND, 'M59 (8x)', left=True, bias='VB4',
            to_gnd=True)
    node_label(d, (X2A - 0.25, Y_ND + 1.3), 'net013', halign='right')

    # stage 3: gm3 PMOS (gate = net013) over the LOAD2 mirror diode
    m7 = sh.pfet('xm7', X2B, 'M7 (gm3)', left=True)
    wire(d, (X2B, Y_PD), (X2B, Y_ND))            # net043 column
    m21 = sh.nfet('xm21', X2B, Y_ND, 'M21', to_gnd=True)
    sh.diode_tie(m21, X2B)
    node_label(d, (X2B + 0.25, Y_ND + 1.3), 'net043')

    # output: gmf PMOS feedforward over the mirror output leg -> VOUT
    m11 = sh.pfet('xm11', X3, 'M11 (gmf)', left=True)
    m22 = sh.nfet('xm22', X3, Y_ND, 'M22', left=True, to_gnd=True)
    g21, g22 = m21.absanchors['gate'], m22.absanchors['gate']
    wire(d, (g21.x, g21.y), (g22.x, g22.y))      # inward mirror gate bus
    dot(d, (g21.x, g21.y))
    wire(d, (X3, Y_PD), (X3, Y_ND))              # VOUT column
    dot(d, (X3, 5.8))
    wire(d, (X3, 5.8), (XMAX - 0.6, 5.8))
    port(d, (XMAX - 0.6, 5.8), 'VOUT', 'right')

    # signal gate feeds (all target gates face left, so feeds never cross
    # their device bodies)
    g10 = m10.absanchors['gate']
    gate_feed(sh, (XCR, 7.5), g10.x, g10.y)      # net050 -> M10 gate
    g7 = m7.absanchors['gate']
    gate_feed(sh, (X2A, 7.8), g7.x, g7.y)        # net013 -> M7 gate
    g11 = m11.absanchors['gate']
    gate_feed(sh, (XCR, 7.0), g11.x, g11.y)      # net050 -> M11 gate

    # compensation: C1 net050 -> net013 (around gm2); C0 net063 -> VOUT
    # (tapped on the right cascode source column — the RAFFC path)
    sh.cap('c1', (XCR, 6.3), (X2A - 0.9, 6.3), 'C1')
    wire(d, (X2A - 0.9, 6.3), (X2A, 6.3))
    dot(d, (XCR, 6.3)); dot(d, (X2A, 6.3))
    dot(d, (XPR, 5.4))
    wire(d, (XPR, 5.4), (X2B + 1.1, 5.4))
    sh.cap('c0', (X2B + 1.1, 5.4), (X3 - 0.9, 5.4), 'C0')
    wire(d, (X3 - 0.9, 5.4), (X3, 5.4))
    dot(d, (X3, 5.4))

    title(d, (XB0 + XMAX) / 2, Y_VDD + 0.8,
          'Alfio RAFFC — 3-stage reversed active-feedback frequency '
          'compensation (SKY130, 1.8 V)')
    sh.save(KEY)

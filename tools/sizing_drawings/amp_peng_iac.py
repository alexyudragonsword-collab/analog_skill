"""amp_peng_iac — Peng IAC, 3-stage amp with impedance-adapting
compensation.

Bias bank and input stage match the TCFC sibling (cascoded VB1/VB2
PMOS legs over VB3/VB4 NMOS stacks, plus the net7 replica).  The IAC
difference is in stage 2: the gm2 load is the 32x cascode M67 whose
source node net1 takes both the VB4 sink M68 and the net043-driven
injector M70 (the impedance-adapting leg), M69 mirrors net043 into
net10, the pull-up is the M7/M66(gmt) cascode, and compensation is
C0 (VOUTP->VOUT) plus the series R0-C1 shunt from net10 to ground.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_sizing_schematics import (   # noqa: E402
    AMP_NL, FET_H, Sheet, TINTS, Y_CM, Y_CT, Y_GND, Y_ND, Y_PD, Y_SRC,
    Y_VDD, dot, gate_feed, node_label, port, rail, tint, title, wire,
)

KEY = 'amp_peng_iac'

Y_P2D = Y_PD - FET_H              # cascode PMOS drain row      6.66


def casc_pair(sh, x, top, top_lbl, cas, cas_lbl):
    """VB1/VB2 cascoded PMOS leg; returns the leg drain point."""
    sh.pfet(top, x, top_lbl, left=True, bias='VB1')
    sh.pfet(cas, x, cas_lbl, left=True, bias='VB2', y=Y_PD)
    return (x, Y_P2D)


# ─────────────────────────────────────────────────────────────────────────────
def draw():
    sh = Sheet(AMP_NL / 'Peng_IAC_Pin_3')
    d = sh.d
    XB0, XB1, XB2, XB3, XB4 = -0.4, 2.8, 6.0, 9.2, 12.4   # bias bank
    XTAIL = 15.6                                          # tail
    XCL, XPL, XPR, XCR = 18.4, 20.6, 22.8, 25.4           # stage 1
    X2A = 29.4                                            # gm2 / net043
    XM70 = 32.4                                           # net1 injector
    X2B = 35.2                                            # net10 column
    X3 = 38.4                                             # output
    XRC = 40.4                                            # R0-C1 shunt leg
    XMAX = 42.0

    tint(d, XB0 - 1.4, Y_GND + .12, XB4 + 1.2, Y_VDD - .15, TINTS['bias'],
         'cascoded bias bank (VB1 / VB2 / VB3 / VB4)')
    tint(d, XTAIL - 1.1, Y_GND + .12, XCR + 1.2, Y_VDD - .15,
         TINTS['input'], 'stage 1: cascoded input')
    tint(d, X2A - 1.3, Y_GND + .12, X2B + 1.2, Y_VDD - .15, TINTS['mirror'],
         'stage 2 + impedance-adapting leg')
    tint(d, X3 - 1.3, Y_GND + .12, XMAX - 0.2, Y_VDD - .15, TINTS['out'],
         'stage 3 + feedforward')
    rail(d, XB0 - 1.7, XMAX, Y_VDD, 'VDDA')
    rail(d, XB0 - 1.7, XMAX, Y_GND, 'GNDA')

    # ── bias bank (same structure as the TCFC sibling) ─────────────────
    m0 = sh.pfet('xm0', XB0, 'M0 (4x)')
    sh.pfet('xm57', XB0, 'M57\n(4x)', left=True, bias='VB2', y=Y_PD)
    g0 = m0.absanchors['gate']
    wire(d, (g0.x, g0.y), (XB0 + 1.6, g0.y), (XB0 + 1.6, 6.2),
         (XB0, 6.2))                                  # VB1 gate tie
    wire(d, (XB0, Y_P2D), (XB0, 5.4))
    dot(d, (XB0, 6.2))
    node_label(d, (XB0 - 0.25, 6.3), 'VB1', halign='right')
    sh.isrc('i0', XB0, 5.4, Y_GND, 'I0')

    m65 = sh.pfet('xm65', XB1, 'M65')
    sh.diode_tie(m65, XB1)
    wire(d, (XB1, Y_PD), (XB1, Y_CT))
    sh.nfet('xm63', XB1, Y_CT, 'M63\n(4x)', left=True, bias='VB3')
    sh.nfet('xm64', XB1, Y_CM, 'M64\n(4x)', left=True, bias='VB4',
            to_gnd=True)
    node_label(d, (XB1 + 0.15, Y_CT + 0.9), 'VB2')

    p = casc_pair(sh, XB2, 'xm1', 'M1 (4x)', 'xm58', 'M58\n(4x)')
    wire(d, p, (XB2, Y_CT))
    sh.nfet('xm12', XB2, Y_CT, 'M12\n(4x)', left=True, bias='VB3')
    sh.nfet('xm17', XB2, Y_CM, 'M17\n(4x)', left=True, bias='VB4',
            to_gnd=True)
    node_label(d, (XB2 + 0.15, Y_CT + 0.9), 'VB4')

    p = casc_pair(sh, XB3, 'xm3', 'M3 (4x)', 'xm62', 'M62\n(4x)')
    wire(d, p, (XB3, Y_ND))
    m14 = sh.nfet('xm14', XB3, Y_ND, 'M14', left=True, to_gnd=True)
    sh.diode_tie(m14, XB3)
    node_label(d, (XB3 + 0.15, Y_ND + 0.9), 'VB3')

    p = casc_pair(sh, XB4, 'xm2', 'M2 (4x)', 'xm61', 'M61\n(4x)')
    wire(d, p, (XB4, Y_CT))
    sh.nfet('xm13', XB4, Y_CT, 'M13\n(4x)', bias='VB3')
    sh.nfet('xm18', XB4, Y_CM, 'M18\n(4x)', bias='VB4', to_gnd=True)
    node_label(d, (XB4 + 0.15, Y_CT + 0.9), 'net7')

    # ── stage 1: tail on the left feeds the pair source bus ───────────
    sh.pfet('xm4', XTAIL, 'M4\n(8x)', bias='VB1', left=True)
    wire(d, (XTAIL, Y_PD), (XTAIL, Y_SRC), (XPL, Y_SRC))
    wire(d, (XPL, Y_SRC), (XPR, Y_SRC))
    l = sh.pfet('xm8', XPL, 'M8', left=True, y=Y_SRC)
    r = sh.pfet('xm9', XPR, 'M9', y=Y_SRC)
    gl, gr = l.absanchors['gate'], r.absanchors['gate']
    wire(d, (gl.x, gl.y), (gl.x - 0.6, gl.y))
    port(d, (gl.x - 0.6, gl.y), 'VINN')
    wire(d, (gr.x, gr.y), (gr.x + 0.6, gr.y))
    port(d, (gr.x + 0.6, gr.y), 'VINP', 'right')
    m5 = sh.pfet('xm5', XCL, 'M5\n(4x)')
    m6 = sh.pfet('xm6', XCR, 'M6 (4x)', left=True)
    g5, g6 = m5.absanchors['gate'], m6.absanchors['gate']
    wire(d, (g5.x, g5.y), (g6.x, g6.y))          # inward mirror gate bus
    dot(d, (g5.x, g5.y))
    sh.diode_tie(m5, XCL)
    sh.nfet('xm15', XCL, Y_CT, 'M15 (8x)', left=True, bias='VB3')
    sh.nfet('xm19', XCL, Y_CM, 'M19 (8x)', left=True, bias='VB4',
            to_gnd=True)
    sh.nfet('xm16', XCR, Y_CT, 'M16 (8x)', bias='VB3')
    sh.nfet('xm20', XCR, Y_CM, 'M20 (8x)', bias='VB4', to_gnd=True)
    wire(d, (XCL, Y_PD), (XCL, Y_CT))            # VOUTN column
    wire(d, (XCR, Y_PD), (XCR, Y_CT))            # VOUTP column
    node_label(d, (XCL - 0.25, Y_CT + 1.3), 'VOUTN', halign='right')
    node_label(d, (XCR + 0.22, Y_CT + 1.3), 'VOUTP')
    dl, dr = (XPL, Y_SRC - FET_H), (XPR, Y_SRC - FET_H)
    wire(d, dl, (XPL, Y_CM), (XCL, Y_CM)); dot(d, (XCL, Y_CM))
    wire(d, dr, (XPR, Y_CM), (XCR, Y_CM)); dot(d, (XCR, Y_CM))
    node_label(d, (XPL + 0.15, Y_CM + 0.25), 'DM_2')
    node_label(d, (XPR - 0.2, Y_CM + 0.25), 'net063', halign='right')

    # ── stage 2: gm2 over the M67 cascode; net1 adapting leg ──────────
    m10 = sh.pfet('xm10', X2A, 'M10\n(gm2)', left=True)
    wire(d, (X2A, Y_PD), (X2A, Y_CT))            # net043 column
    sh.nfet('xm67', X2A, Y_CT, 'M67\n(32x)', left=True, bias='VB3')
    sh.nfet('xm68', X2A, Y_CM, 'M68', left=True, bias='VB4', to_gnd=True)
    node_label(d, (X2A - 0.3, 5.1), 'net043', halign='right')
    # net1: cascode source node, fed by the M70 injector
    m70 = sh.nfet('xm70', XM70, Y_CM, 'M70', to_gnd=True)
    wire(d, (XM70, Y_CM), (X2A, Y_CM)); dot(d, (X2A, Y_CM))
    node_label(d, (X2A + 0.7, Y_CM + 0.22), 'net1')
    # net10 column: M7/M66(gmt) cascode pull-up over the M69 mirror leg
    sh.pfet('xm7', X2B, 'M7\n(16x)', left=True, bias='VB1')
    sh.pfet('xm66', X2B, 'M66\n(gmt)', left=True, bias='VB2', y=Y_PD)
    wire(d, (X2B, Y_P2D), (X2B, Y_ND))           # net10 column
    node_label(d, (X2B + 0.25, Y_PD + 0.17), 'net049')
    node_label(d, (X2B + 0.25, Y_ND + 1.3), 'net10')
    m69 = sh.nfet('xm69', X2B, Y_ND, 'M69', left=True, to_gnd=True)
    # net043 drives both M70 and M69 gates (bus between the two legs)
    g70, g69 = m70.absanchors['gate'], m69.absanchors['gate']
    wire(d, (g70.x, g70.y), (g69.x, g69.y))
    XRI = 33.8
    dot(d, (XRI, g70.y))
    wire(d, (XRI, g70.y), (XRI, 6.0), (X2A, 6.0))
    dot(d, (X2A, 6.0))

    # ── stage 3: gm3 NMOS + gmf PMOS feedforward into VOUT ────────────
    m11 = sh.pfet('xm11', X3, 'M11 (gmf)', left=True)
    m23 = sh.nfet('xm23', X3, Y_ND, 'M23\n(gm3)', left=True, to_gnd=True)
    wire(d, (X3, Y_PD), (X3, Y_ND))              # VOUT column
    dot(d, (X3, 5.8))
    wire(d, (X3, 5.8), (XMAX - 0.6, 5.8))
    port(d, (XMAX - 0.6, 5.8), 'VOUT', 'right')

    # signal gate feeds (target gates face left)
    g10 = m10.absanchors['gate']
    gate_feed(sh, (XCR, 7.5), g10.x, g10.y)      # VOUTP -> M10 gate
    g11 = m11.absanchors['gate']
    gate_feed(sh, (XCR, 5.6), g11.x, g11.y)      # VOUTP -> M11 gate
    g23 = m23.absanchors['gate']
    gate_feed(sh, (X2B, 4.4), g23.x, g23.y)      # net10 -> M23 gate

    # compensation: C0 (VOUTP -> VOUT), series C1+R0 from net10 to GNDA
    sh.cap('c0', (XCR, 6.3), (X3 - 0.9, 6.3), 'C0')
    wire(d, (X3 - 0.9, 6.3), (X3, 6.3))
    dot(d, (XCR, 6.3)); dot(d, (X3, 6.3))
    wire(d, (X2B, 5.2), (XRC - 1.2, 5.2))        # net10 tap (crosses VOUT
    dot(d, (X2B, 5.2))                           # column dot-free)
    sh.cap('c1', (XRC - 1.2, 5.2), (XRC, 5.2), 'C1', loc='bot')
    node_label(d, (XRC + 0.2, 4.6), 'net4')
    sh.res('r0', (XRC, 5.2), (XRC, 3.4), 'R0', loc='bot')
    wire(d, (XRC, 3.4), (XRC, Y_GND))

    title(d, (XB0 + XMAX) / 2, Y_VDD + 0.8,
          'Peng IAC — 3-stage amp, impedance-adapting compensation '
          '(SKY130, 1.8 V)')
    sh.save(KEY)

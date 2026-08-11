"""amp_song_dacfc — Song DACFC, the family's largest sheet.

37 MOS + I0 + C2 + C0.  A three-stage amp with damping-factor-control
frequency compensation: DUAL feedforward (gmf1 = xm57/xm58 into stage 2,
gmf2 = xm11 into the output) plus an active-feedback / damping path
(gma1 = xm5/xm6 and gma2 = xm7, all gated by the stage-1 node VOUTN),
and a class-AB-style floating current source (net70 biases xm68/xm69,
whose cascodes xm62/xm63 sit over the VOUTN branch).

Layout (left → right bands):
- bias band  : net013 diode + I0, VB4 gen (xm1/xm12/xm17), VB3 diode
               (xm3/xm14), DM_1 self-biased cascode ref (xm2/xm13/xm18);
- float CS   : net70 stack (xm68/xm63 over xm70/xm65) + xm69 → net3;
- stage 1    : VOUTN branch (aux col xm62/xm71/xm64 + main col xm5/xm60
               over xm15/xm19) LEFT of the tail xm4, the gm1 pair
               xm8/xm9, and the net4 branch (xm6/xm61 over xm16/xm20)
               RIGHT of the pair;
- feedforward: gmf1 pair xm57/xm58 on the net1 tail xm59;
- stage 2    : net043 (gm2 xm10 + LOAD2 diode xm21) and net049 (gma2 xm7
               + LOAD2 mirror xm22), each also taking a gmf1 drain;
- output     : gmf2 xm11 + gm3 xm23 into VOUT; C2 net4→GND, C0 VOUT→net70.

Long inter-block signal gates (net4 → gm2/gmf2, VOUTN → gma1/gma2) are
labelled gate stubs, matching the bias-stub convention — routing them as
wires across this 37-device field would cross several bodies.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_sizing_schematics import (   # noqa: E402
    AMP_NL, FET_H, Sheet, TINTS, Y_CM, Y_CT, Y_GND, Y_ND, Y_PD, Y_SRC,
    Y_VDD, bias_column, diff_pair, dot, gate_feed, node_label, port, rail,
    tint, title, vb3_diode, vb_gen, wire,
)

KEY = 'amp_song_dacfc'

VOUTN_Y = Y_PD - FET_H     # 6.66 — PMOS-cascode-delivered stage-1 node row


def draw():
    sh = Sheet(AMP_NL / 'Song_DACFC_Pin_3')
    d = sh.d
    XB0, XB1, XB2, XR = -0.4, 2.6, 5.8, 9.0        # bias band
    XG, XG2 = 12.2, 14.8                            # float CS (net70/net3)
    XVA, XVL = 17.8, 20.8                           # VOUTN aux / main cols
    XT = 23.6                                        # main tail
    XPL, XPR = 26.2, 28.8                            # gm1 pair
    XNR = 31.8                                       # net4 branch
    XFT, XFL, XFR = 35.6, 38.2, 40.8                # gmf1 pair
    X2A, X2B = 44.0, 46.8                            # stage 2
    X3 = 49.6                                        # output
    XMAX = X3 + 3.0

    tint(d, XB0 - 1.2, Y_GND + .12, XR + 1.2, Y_VDD - .15, TINTS['bias'],
         'bias (net013 / VB3 / VB4 / DM_1)')
    tint(d, XG - 1.2, Y_GND + .12, XG2 + 1.2, Y_VDD - .15, TINTS['bias'],
         'floating CS (net70)')
    tint(d, XVA - 1.3, Y_GND + .12, XNR + 1.4, Y_VDD - .15, TINTS['input'],
         'stage 1: cascoded input + gma feedback')
    tint(d, XFT - 1.2, Y_GND + .12, XFR + 1.2, Y_VDD - .15, TINTS['comp'],
         'feedforward gmf1')
    tint(d, X2A - 1.3, Y_GND + .12, X2B + 1.3, Y_VDD - .15, TINTS['mirror'],
         'stage 2 (gm2 + LOAD2)')
    tint(d, X3 - 1.3, Y_GND + .12, XMAX - 0.2, Y_VDD - .15, TINTS['out'],
         'output: gmf2 + gm3')
    rail(d, XB0 - 1.5, XMAX, Y_VDD, 'VDDA')
    rail(d, XB0 - 1.5, XMAX, Y_GND, 'GNDA')

    # ── bias band ────────────────────────────────────────────────────────
    bias_column(sh, XB0)                                        # xm0 + I0
    vb_gen(sh, XB1, 'xm1', 'M1 (4x)', ('xm12', 'xm17'),
           ('M12 (4x)', 'M17 (4x)'))                            # VB4
    vb3_diode(sh, XB2, 'xm3', 'M3 (4x)', 'xm14', 'M14')         # VB3
    # DM_1: PMOS diode xm2 over a VB3/VB4 cascoded NMOS sink (xm13/xm18)
    m2 = sh.pfet('xm2', XR, 'M2')
    g2 = m2.absanchors['gate']
    wire(d, m2.absanchors['drain'], (XR, g2.y))
    sh.diode_tie(m2, XR)
    wire(d, (XR, Y_PD), (XR, Y_CT))
    sh.nfet('xm13', XR, Y_CT, 'M13 (4x)', left=True, bias='VB3')
    sh.nfet('xm18', XR, Y_CM, 'M18 (4x)', left=True, bias='VB4', to_gnd=True)
    node_label(d, (XR + 0.15, Y_CT + 0.9), 'DM_1')

    # ── floating current source: net70 biases xm68/xm69 ─────────────────
    sh.pfet('xm68', XG, 'M68', bias='net70')                    # → net2
    node_label(d, (XG + 0.2, Y_PD + 0.12), 'net2')
    sh.pfet('xm63', XG, 'M63 (4x)', y=Y_PD, bias='DM_1')        # net2→net70
    wire(d, (XG, VOUTN_Y), (XG, Y_CT))
    sh.nfet('xm70', XG, Y_CT, 'M70 (4x)', left=True, bias='VB3')
    sh.nfet('xm65', XG, Y_CM, 'M65 (8x)', left=True, bias='VB4', to_gnd=True)
    node_label(d, (XG - 0.25, 5.5), 'net70', halign='right')
    node_label(d, (XG - 0.2, Y_CM + 0.25), 'net69', halign='right')
    sh.pfet('xm69', XG2, 'M69', bias='net70', left=True)        # → net3
    wire(d, (XG2, Y_PD), (XG2, Y_PD - 0.6))
    node_label(d, (XG2 + 0.18, Y_PD - 0.75), 'net3')

    # ── stage 1: VOUTN aux column (xm62 cascode + xm71/xm64 pulldown) ────
    sh.pfet('xm62', XVA, 'M62 (4x)', y=Y_PD, bias='DM_1', left=True)
    node_label(d, (XVA - 0.2, Y_PD + 0.12), 'net3', halign='right')
    wire(d, (XVA, VOUTN_Y), (XVA, Y_CT))
    sh.nfet('xm71', XVA, Y_CT, 'M71 (4x)', left=True, bias='VB3')
    sh.nfet('xm64', XVA, Y_CM, 'M64 (8x)', left=True, bias='VB4', to_gnd=True)
    node_label(d, (XVA - 0.2, Y_CM + 0.25), 'net85', halign='right')

    # VOUTN main column: gma1 xm5 + cascode xm60 over cascode xm15 + sink xm19
    sh.pfet('xm5', XVL, 'M5 (gma1)', bias='VOUTN', left=True)
    node_label(d, (XVL + 0.18, Y_PD + 0.12), 'net5')
    sh.pfet('xm60', XVL, 'M60 (4x)', y=Y_PD, bias='DM_1', left=True)
    wire(d, (XVL, VOUTN_Y), (XVL, Y_CT))
    sh.nfet('xm15', XVL, Y_CT, 'M15 (4x)', left=True, bias='VB3')
    sh.nfet('xm19', XVL, Y_CM, 'M19 (8x)', left=True, bias='VB4', to_gnd=True)
    node_label(d, (XVL - 0.25, 5.7), 'VOUTN', halign='right')
    # VOUTN bus ties the aux and main columns
    wire(d, (XVA, VOUTN_Y), (XVL, VOUTN_Y))
    dot(d, (XVA, VOUTN_Y)); dot(d, (XVL, VOUTN_Y))

    # main tail + gm1 pair
    sh.pfet('xm4', XT, 'M4 (tail, 2x)', bias='net013', left=True)
    wire(d, (XT, Y_PD), (XT, Y_SRC), (XPL, Y_SRC))
    wire(d, (XPL, Y_SRC), (XPR, Y_SRC))
    dot(d, (XT, Y_SRC))
    l = sh.pfet('xm8', XPL, 'M8', left=True, y=Y_SRC)
    r = sh.pfet('xm9', XPR, 'M9', y=Y_SRC)
    gl, gr = l.absanchors['gate'], r.absanchors['gate']
    wire(d, (gl.x, gl.y), (gl.x - 0.6, gl.y)); port(d, (gl.x - 0.6, gl.y), 'VINN')
    wire(d, (gr.x, gr.y), (gr.x + 0.6, gr.y))
    port(d, (gr.x + 0.6, gr.y), 'VINP', 'right')
    # left drain DM_2 → xm15 source (in XVL); right drain net063 → xm16 (XNR)
    wire(d, (XPL, Y_SRC - FET_H), (XPL, Y_CM), (XVL, Y_CM)); dot(d, (XVL, Y_CM))
    node_label(d, (XPL + 0.15, Y_CM + 0.25), 'DM_2')
    wire(d, (XPR, Y_SRC - FET_H), (XPR, Y_CM), (XNR, Y_CM)); dot(d, (XNR, Y_CM))
    node_label(d, (XPR - 0.2, Y_CM + 0.25), 'net063', halign='right')

    # net4 branch (right of the pair): gma1 xm6 + cascode xm61 over xm16/xm20
    sh.pfet('xm6', XNR, 'M6 (gma1)', bias='VOUTN', left=True)
    node_label(d, (XNR + 0.18, Y_PD + 0.12), 'net050')
    sh.pfet('xm61', XNR, 'M61 (4x)', y=Y_PD, bias='DM_1')
    wire(d, (XNR, VOUTN_Y), (XNR, Y_CT))
    sh.nfet('xm16', XNR, Y_CT, 'M16 (4x)', bias='VB3')
    sh.nfet('xm20', XNR, Y_CM, 'M20 (8x)', bias='VB4', to_gnd=True)
    node_label(d, (XNR + 0.2, 5.7), 'net4')
    # C2 : net4 → GND (grounded comp cap, just right of the branch)
    XC2 = XNR + 1.5
    wire(d, (XNR, 5.9), (XC2, 5.9), (XC2, 3.2))
    dot(d, (XNR, 5.9))
    sh.cap('c2', (XC2, 3.2), (XC2, 1.9), 'C2', loc='bot')
    wire(d, (XC2, 1.9), (XC2, Y_GND))

    # ── feedforward gmf1 pair on the net1 tail ──────────────────────────
    (ffl, ffr) = diff_pair(sh, XFT, XFL, XFR, 'xm59', 'M59',
                           'xm57', 'M57', 'xm58', 'M58')
    node_label(d, (XFT + 0.15, Y_SRC + 0.25), 'net1')

    # ── stage 2: net043 (gm2 + LOAD2 diode) and net049 (gma2 + mirror) ──
    sh.pfet('xm10', X2A, 'M10 (gm2)', bias='net4', left=True)
    wire(d, (X2A, Y_PD), (X2A, Y_ND))
    m21 = sh.nfet('xm21', X2A, Y_ND, 'M21', to_gnd=True)
    sh.diode_tie(m21, X2A)
    node_label(d, (X2A - 0.25, Y_ND + 1.5), 'net043', halign='right')
    sh.pfet('xm7', X2B, 'M7 (gma2)', bias='VOUTN', left=True)
    wire(d, (X2B, Y_PD), (X2B, Y_ND))
    m22 = sh.nfet('xm22', X2B, Y_ND, 'M22', left=True, to_gnd=True)
    node_label(d, (X2B + 0.25, Y_ND + 1.5), 'net049')
    g21, g22 = m21.absanchors['gate'], m22.absanchors['gate']
    wire(d, (g21.x, g21.y), (g22.x, g22.y)); dot(d, (g21.x, g21.y))
    # gmf1 drains feed the stage-2 nodes (net043 left, net049 right)
    wire(d, ffl, (XFL, 5.8), (X2A, 5.8), (X2A, Y_ND + 1.0)); dot(d, (X2A, 5.8))
    wire(d, ffr, (XFR, 5.4), (X2B, 5.4), (X2B, Y_ND + 1.0)); dot(d, (X2B, 5.4))

    # ── output: gmf2 xm11 + gm3 xm23 into VOUT ──────────────────────────
    sh.pfet('xm11', X3, 'M11 (gmf2)', bias='net4', left=True)
    m23 = sh.nfet('xm23', X3, Y_ND, 'M23 (gm3)', left=True, to_gnd=True)
    wire(d, (X3, Y_PD), (X3, Y_ND))
    dot(d, (X3, VOUTN_Y))
    wire(d, (X3, VOUTN_Y), (XMAX - 0.7, VOUTN_Y))
    port(d, (XMAX - 0.7, VOUTN_Y), 'VOUT', 'right')
    g23 = m23.absanchors['gate']
    gate_feed(sh, (X2B, 4.3), g23.x, g23.y)                    # net049 → gm3
    # C0 : VOUT → net70 (outer Miller, net70 as a labelled stub)
    dot(d, (X3, 6.0))
    wire(d, (X3, 6.0), (X3 + 0.7, 6.0))
    sh.cap('c0', (X3 + 0.7, 6.0), (X3 + 1.7, 6.0), 'C0')
    node_label(d, (X3 + 1.85, 6.0), 'net70')

    title(d, (XB0 - 1.5 + XMAX) / 2, Y_VDD + 0.8,
          'Song DACFC — 3-stage, dual feedforward + damping-factor '
          'control (SKY130, 1.8 V)')
    sh.save(KEY)

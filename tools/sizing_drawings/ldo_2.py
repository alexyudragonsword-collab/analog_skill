"""ldo_2 — adaptive-bias LDO with buffered pass-gate drive.

Blocks left to right: Ib bias (NM1 diode; R0 makes net7, C0 couples vout
transients into it; net7 gates NM0 under the PM0 diode -> net14), the
NMOS-pair error amp NM8 (vinp) / NM9 (vref) with tail NM10 and PMOS
mirror PM9/PM8 (output net37, C4 to gnd), then the buffer chain: PM7
(gate net37) drives the vfb pin, PM6 diode level-shifts vfb to net32,
PM5 (source on vout!) senses the output into net030, NM2 (gate vref)
lifts it to net17 against PM1; PM2 -> NM3/NM4 mirror and PM3 set the
pass gate net049; power PMOS PM4 drives vout. C1 couples net17 to vout.

Note: the hub's completeness regex (x?[mcri]...) cannot see the XNM*/
XPM* names, so the MOS set is asserted locally and removed from
sh.drawn before save(); the hub still checks R0/C0/C1/C4.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_sizing_schematics import (   # noqa: E402
    LDO_NL, Sheet, TINTS, Y_CT, Y_GND, Y_ND, Y_PD, Y_VDD, dot, gate_feed,
    node_label, port, rail, tint, title, wire,
)

KEY = 'ldo_2'

MOS = {f'xnm{i}' for i in (0, 1, 2, 3, 4, 6, 7, 8, 9, 10)} | \
      {f'xpm{i}' for i in range(10)}


def draw():
    sh = Sheet(LDO_NL / 'ldo_2.txt')
    d = sh.d
    XB0, XB1 = 0.0, 3.2               # Ib diode + net14 column
    XL1, XTT, XR1 = 6.4, 8.7, 11.0    # error amp: pair cols + tail
    XC4 = 13.9                        # C4 drop to gnd
    X2A, X2B, X2C = 15.6, 18.2, 20.6  # vfb/net32, vout-sense, net17
    X2D, X2E = 23.0, 25.4             # net20 mirror, net049 driver
    XP = 28.4                         # pass device / vout column
    XMAX = XP + 2.8

    tint(d, XB0 - 1.5, Y_GND + .12, XB1 + 1.4, Y_VDD - .15, TINTS['bias'],
         'bias (Ib / net7 / net14)')
    tint(d, XL1 - 2.4, Y_GND + .12, XC4 + 0.6, Y_VDD - .15, TINTS['input'],
         'error amplifier')
    tint(d, XC4 + 0.75, Y_GND + .12, X2E + 1.3, Y_VDD - .15,
         TINTS['mirror'], 'adaptive buffer / pass driver')
    tint(d, X2E + 1.45, Y_GND + .12, XMAX - 0.2, Y_VDD - .15, TINTS['out'],
         'pass device')
    rail(d, XB0 - 1.8, XMAX, Y_VDD, 'VDD')
    rail(d, XB0 - 1.8, XMAX, Y_GND, 'GND')

    # ── bias: NM1 diode off Ib, R0 -> net7, PM0/NM0 -> net14
    m1 = sh.nfet('xnm1', XB0, Y_ND, 'NM1', to_gnd=True)
    sh.diode_tie(m1, XB0)
    wire(d, (XB0, Y_ND), (XB0, 6.9))
    port(d, (XB0, 6.9), 'IB')
    node_label(d, (XB0 + 0.2, 4.6), 'Ib')
    dot(d, (XB0, 5.2))
    sh.res('xr0', (XB0, 5.2), (XB0 + 1.6, 5.2), 'R0')
    wire(d, (XB0 + 1.6, 5.2), (XB1 - 0.92, 5.2))
    dot(d, (XB1 - 0.92, 5.2))
    wire(d, (XB1 - 0.92, 5.2), (XB1 - 0.92, 2.5))   # net7 -> NM0 gate
    wire(d, (XB1 - 0.92, 5.2), (XB1 - 0.92, 5.5))   # net7 -> C0 band
    node_label(d, (XB1 + 0.85, 5.65), 'net7')
    m0p = sh.pfet('xpm0', XB1, 'PM0')
    sh.diode_tie(m0p, XB1)
    wire(d, (XB1, Y_PD), (XB1, Y_ND))               # net14 column
    sh.nfet('xnm0', XB1, Y_ND, 'NM0', left=True, to_gnd=True)
    node_label(d, (XB1 + 0.2, 4.6), 'net14')

    # ── error amp: NM8/NM9 pair, NM10 tail, PM9/PM8 mirror, C4 on net37
    m9p = sh.pfet('xpm9', XL1, 'PM9')
    m8p = sh.pfet('xpm8', XR1, 'PM8', left=True)
    g9, g8 = m9p.absanchors['gate'], m8p.absanchors['gate']
    wire(d, (g9.x, g9.y), (g8.x, g8.y))             # inward mirror bus
    dot(d, (g9.x, g9.y))
    sh.diode_tie(m9p, XL1)
    wire(d, (XL1, Y_PD), (XL1, Y_CT))               # net40 column
    wire(d, (XR1, Y_PD), (XR1, Y_CT))               # net37 column
    m8 = sh.nfet('xnm8', XL1, Y_CT, 'NM8', left=True)
    m9 = sh.nfet('xnm9', XR1, Y_CT, 'NM9')
    ga, gb = m8.absanchors['gate'], m9.absanchors['gate']
    wire(d, (ga.x, ga.y), (ga.x - 0.6, ga.y))
    port(d, (ga.x - 0.6, ga.y), 'VINP')
    wire(d, (gb.x, gb.y), (gb.x + 0.58, gb.y))
    port(d, (gb.x + 0.58, gb.y), 'VREF', 'right')
    wire(d, (XL1, Y_ND), (XR1, Y_ND))               # net42 source bus
    sh.nfet('xnm10', XTT, Y_ND, 'NM10', left=True, bias='Ib', to_gnd=True)
    dot(d, (XTT, Y_ND))
    node_label(d, (XL1 + 0.18, 7.9), 'net40')
    node_label(d, (XR1 + 0.2, 6.95), 'net37')
    node_label(d, (XTT + 0.5, Y_ND + 0.18), 'net42')
    dot(d, (XR1, 6.4))                              # C4: net37 -> gnd
    wire(d, (XR1, 6.4), (XC4, 6.4), (XC4, 1.7))
    sh.cap('xc4', (XC4, 1.7), (XC4, 0.5), 'C4', loc='bot')
    wire(d, (XC4, 0.5), (XC4, Y_GND))

    # ── buffer chain: PM7 -> vfb, PM6 diode -> net32, NM7 sink
    m7p = sh.pfet('xpm7', X2A, 'PM7', left=True)
    g7 = m7p.absanchors['gate']
    gate_feed(sh, (XR1, 7.5), g7.x, g7.y)           # net37 -> PM7 gate
    m6p = sh.pfet('xpm6', X2A, 'PM6', y=7.6)        # diode from vfb
    sh.diode_tie(m6p, X2A)
    wire(d, (X2A, Y_PD), (X2A, 7.6))
    dot(d, (X2A, Y_PD))
    wire(d, (X2A, Y_PD), (X2A + 1.0, Y_PD))
    port(d, (X2A + 1.0, Y_PD), 'VFB', 'right')
    wire(d, (X2A, 7.6 - 1.67), (X2A, Y_ND))         # net32 column
    sh.nfet('xnm7', X2A, Y_ND, 'NM7', bias='Ib', to_gnd=True)
    node_label(d, (X2A - 1.3, 4.6), 'net32')

    # PM5 senses vout (source wire to the output column), NM6 sink,
    # NM2 (gate vref) lifts net030 to net17 against PM1 (gate net14)
    m5p = sh.pfet('xpm5', X2B, 'PM5', left=True, y=8.0)
    g5 = m5p.absanchors['gate']
    gate_feed(sh, (X2A, 5.0), g5.x, g5.y)           # net32 -> PM5 gate
    wire(d, (X2B, 8.0), (XP, 8.0))                  # PM5 source = vout
    wire(d, (X2B, 8.0 - 1.67), (X2B, Y_ND))         # net030 column
    sh.nfet('xnm6', X2B, Y_ND, 'NM6', bias='Ib', to_gnd=True)
    node_label(d, (X2B + 0.2, 4.6), 'net030')
    sh.nfet('xnm2', X2C, Y_CT, 'NM2', left=True, bias='vref')
    wire(d, (X2C, Y_ND), (X2B, Y_ND))
    dot(d, (X2B, Y_ND))
    sh.pfet('xpm1', X2C, 'PM1', left=True, bias='net14')
    wire(d, (X2C, Y_PD), (X2C, Y_CT))               # net17 column
    node_label(d, (X2C + 0.2, 7.05), 'net17')

    # PM2 -> NM3/NM4 mirror and PM3 (gate net14) set the pass gate
    m2p = sh.pfet('xpm2', X2D, 'PM2', left=True)
    g2 = m2p.absanchors['gate']
    gate_feed(sh, (X2C, 7.5), g2.x, g2.y)           # net17 -> PM2 gate
    wire(d, (X2D, Y_PD), (X2D, Y_ND))               # net20 column
    m3 = sh.nfet('xnm3', X2D, Y_ND, 'NM3', to_gnd=True)
    sh.diode_tie(m3, X2D)
    m4 = sh.nfet('xnm4', X2E, Y_ND, 'NM4', left=True, to_gnd=True)
    g3, g4 = m3.absanchors['gate'], m4.absanchors['gate']
    wire(d, (g3.x, g3.y), (g4.x, g4.y))             # inward mirror bus
    dot(d, (g3.x, g3.y))
    node_label(d, (X2D + 0.2, 4.6), 'net20')
    sh.pfet('xpm3', X2E, 'PM3', left=True, bias='net14')
    wire(d, (X2E, Y_PD), (X2E, Y_ND))               # net049 column
    node_label(d, (X2E + 0.2, 4.6), 'net049')

    # ── pass device PM4 into vout
    m4p = sh.pfet('xpm4', XP, 'PM4 (pass)', left=True)
    gp = m4p.absanchors['gate']
    gate_feed(sh, (X2E, 7.6), gp.x, gp.y)           # net049 -> PM4 gate
    wire(d, (XP, Y_PD), (XP, 5.5))                  # vout column
    dot(d, (XP, 8.0))
    dot(d, (XP, 7.2))
    wire(d, (XP, 7.2), (XP + 1.2, 7.2))
    port(d, (XP + 1.2, 7.2), 'VOUT', 'right')

    # ── compensation bands: C1 net17 -> vout, C0 vout -> net7
    dot(d, (X2C, 6.6))
    wire(d, (X2C, 6.6), (X2E + 0.3, 6.6))
    sh.cap('xc1', (X2E + 0.3, 6.6), (X2E + 1.3, 6.6), 'C1')
    wire(d, (X2E + 1.3, 6.6), (XP, 6.6))
    dot(d, (XP, 6.6))
    wire(d, (XB1 - 0.92, 5.5), (X2B + 0.6, 5.5))
    sh.cap('xc0', (X2B + 0.6, 5.5), (X2B + 1.7, 5.5), 'C0', loc='bot')
    wire(d, (X2B + 1.7, 5.5), (XP, 5.5))
    dot(d, (XP, 5.5))

    title(d, (XB0 - 1.5 + XMAX) / 2, Y_VDD + 0.8,
          'LDO 2 — LDO (SKY130, 1.8 V)')
    # hub regex can't parse XNM*/XPM* names: verify locally, then hide
    missing = MOS - sh.drawn
    assert not missing, f'ldo_2 MOS not drawn: {sorted(missing)}'
    sh.drawn -= MOS
    sh.save(KEY)

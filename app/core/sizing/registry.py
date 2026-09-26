"""The built-in circuit registry.

Which topologies the Sizing tab offers — the vendored AnalogGym amps and
LDOs, the original studio_circuits designs, and the PTM circuit-skills
circuits — and the metric targets each is judged against.  ``SIZING`` is
built once at import; user-imported circuits are added to it later by
:mod:`app.core.sizing.user_circuits`.
"""

from dataclasses import replace

from app import paths
from app.core.sizing.spec import LdoBench, MetricSpec, SizingSpec


def _amp_metrics() -> list:
    # targets from AnalogGym's spec dicts (ckt_graphs.py / README FoM)
    return [
        MetricSpec('dcgain', 'DC gain', 'dB', 100.0, 'max', 2.0),
        MetricSpec('gain_bandwidth_product', 'GBW', 'Hz', 1.2e6, 'max', 2.0),
        # a floor: an equality target is never *met* (violation is zero
        # only at exact equality) and was the reason no amplifier here
        # could ever report all targets met.  A bare floor admitted a
        # 156-degree design with its dominant pole below 0.1 Hz; a 90
        # degree ceiling caught it and nothing else.  What that design
        # actually costs is measured now, by tsettle below — it never
        # settles — so the ceiling is gone and the floor stays.
        MetricSpec('phase_in_deg', 'Phase margin', 'deg', 60.0, 'max', 1.5),
        MetricSpec('dcpsrp', 'PSRR+ (dc)', 'dB', -60.0, 'min', 1.0),
        MetricSpec('dcpsrn', 'PSRR- (dc)', 'dB', -60.0, 'min', 1.0),
        MetricSpec('cmrrdc', 'CMRR (dc)', 'dB', -60.0, 'min', 1.0),
        MetricSpec('power', 'Power', 'W', 0.5e-3, 'min', 1.0),
        MetricSpec('vos25', 'Offset (25C)', 'V', 0.1e-3, 'absmin', 0.5),
        MetricSpec('tc', 'Temp. coeff.', 'V/°C', 10e-6, 'absmin', 0.5),
        # 1% settling of a 100 mV unity-gain step.  Measured on the
        # reference amplifier: 78-88 degree designs 0.9-1.0 us, a 40
        # degree one 1.4 us (ringing), the 156 degree one never.  The
        # Analog Studio addition to AnalogGym's nine.  Was 2 us (~15
        # time constants at the 1.2 MHz GBW target, chosen on one
        # circuit); the 27-circuit sweep put two amplifiers' best
        # points at 2.01 and 2.46 us with everything else met, six of
        # fifteen between 2 and 3 us, and no row trading another target
        # for the slack (cairn/pitfalls.md).  3 us, the maintainer's
        # call, 2026-09-25.
        MetricSpec('tsettle', 'Settling (1%)', 's', 3e-6, 'min', 1.0),
    ]


def _cm_ota_metrics() -> list:
    """Targets for the single-stage current-mirror OTA (studio_circuits).

    Same TB_Amplifier_ACDC metric keys as the AnalogGym amps, but the
    targets are calibrated for a single-stage topology on a 500 pF load
    (measured default: 42 dB / 0.37 MHz / PM 90° / 0.42 mW).  A single
    stage tops out near ~45 dB, and GBW trades directly against power and
    (weakly) against gain — so gain 44 dB and GBW 0.6 MHz are reachable
    but not simultaneously free, which is the whole point of the sizing."""
    return [
        MetricSpec('dcgain', 'DC gain', 'dB', 44.0, 'max', 2.0),
        MetricSpec('gain_bandwidth_product', 'GBW', 'Hz', 0.6e6, 'max', 2.0),
        # single-pole-dominated → naturally ~90°; require ≥ 55°, no penalty
        # for the extra stability
        MetricSpec('phase_in_deg', 'Phase margin', 'deg', 55.0, 'max', 1.0),
        MetricSpec('cmrrdc', 'CMRR (dc)', 'dB', -60.0, 'min', 1.0),
        MetricSpec('dcpsrp', 'PSRR+ (dc)', 'dB', -45.0, 'min', 1.0),
        MetricSpec('dcpsrn', 'PSRR- (dc)', 'dB', -50.0, 'min', 1.0),
        MetricSpec('power', 'Power', 'W', 1.0e-3, 'min', 1.0),
        MetricSpec('vos25', 'Offset (25C)', 'V', 5e-3, 'absmin', 0.5),
        MetricSpec('tc', 'Temp. coeff.', 'V/°C', 60e-6, 'absmin', 0.5),
        # the same follower step as the amps; 4 us for a 0.6 MHz GBW
        MetricSpec('tsettle', 'Settling (1%)', 's', 4e-6, 'min', 1.0),
    ]


def _amps(i: float) -> str:
    return f'{i * 1e3:g} mA' if i >= 1e-3 else f'{i * 1e6:g} µA'


def _ldo_conditions(bench: LdoBench) -> str:
    """'1.8 V in, 1.6 V out, 5–55 mA' for the circuit titles."""
    lo, hi = _amps(bench.i_min), _amps(bench.i_max)
    if lo.split()[1] == hi.split()[1]:
        lo = lo.split()[0]
    return f'{bench.supply:g} V in, {bench.vout:g} V out, {lo}–{hi}'


def _ldo_metrics_spec(bench: LdoBench) -> list:
    # phase margins are floors here too: the amplifiers' ceiling went when
    # settling time began measuring what over-compensation costs, and a
    # ceiling nothing measures is a guess on every circuit.  The LDO's
    # honest replacement is a load-step settling metric (ROADMAP).
    hi, lo = _amps(bench.i_max), _amps(bench.i_min)
    return [
        MetricSpec('pm_maxload', f'Phase margin ({hi})', 'deg', 60.0,
                   'max', 1.5),
        MetricSpec('pm_minload', f'Phase margin ({lo})', 'deg', 60.0,
                   'max', 1.5),
        MetricSpec('gbw_maxload', f'Loop GBW ({hi})', 'Hz', 2e6, 'max', 1.5),
        MetricSpec('lnr', 'Line regulation', 'V/V', 0.01, 'absmin', 1.0),
        # the decks print LR as ppavl/avgval/ΔI: a relative swing per
        # ampere, not volts per ampere
        MetricSpec('lr', 'Load regulation (ΔV/V)', '1/A', 0.1, 'absmin',
                   1.0),
        MetricSpec('psrr_maxload', f'PSRR (dc, {hi})', 'dB', -40.0,
                   'min', 1.0),
        MetricSpec('vos_maxload', f'Vout error ({hi})', 'V', 2e-3,
                   'absmin', 1.0),
        MetricSpec('iq', 'Quiescent current', 'A', 1e-3, 'min', 1.0),
    ]


# 15 Miller multi-stage op amps validated with ngspice-42 at their default
# sizing.  Excluded upstream defects: Qu_LEC (netlist file ships empty) and
# Tan_CLIA (default W=0.253 um is below the SKY130 model-bin range →
# "could not find a valid modelname").  All share the 5-pin subckt contract
# gnda vdda vinn vinp vout and the TB_Amplifier_ACDC testbench (DUT name
# substituted at render time).
#: power caps for the two amplifiers where the shared 0.5 mW sits inside
#: the measured feasible boundary (cairn/pitfalls.md, "Two amplifiers
#: nobody closes"): Ramos needs 0.55-0.69 mW for 1.2 MHz into 500 pF,
#: and NMCF's best point meeting the other nine targets draws 0.522 mW.
#: The maintainer's call, 2026-09-25; the other thirteen keep AnalogGym's.
_AMP_POWER_CAP = {'Leung_NMCF_Pin_3': 0.55e-3, 'Ramos_PFC_Pin_3': 0.7e-3}

_AMP_NETLISTS = [
    'HoiLee_AFFC_Pin_3', 'Leung_NMCF_Pin_3', 'Leung_NMCNR_Pin_3',
    'Leung_DFCFC1_Pin_3', 'Leung_DFCFC2_Pin_3', 'Peng_ACBC_Pin_3',
    'Peng_IAC_Pin_3', 'Peng_TCFC_Pin_3', 'Qu2017_AZC_Pin_3',
    'Ramos_PFC_Pin_3', 'Sau_CFCC_Pin_3', 'Song_DACFC_Pin_3',
    'Yan_AZ_Pin_3', 'Fan_SMC_Pin_3', 'Alfio_RAFFC_Pin_3',
]


# LDO variants: each has its own testbench; wrdata files carry the prefix
# (ldo_1/ldo_2 insert an extra _ACDC infix).  The conditions come from
# each deck's .PARAM and alter lines and from the netlist's feedback:
# Basic_LDO and ldo_1 divide the output 4:1 to a 0.4 V reference, the
# other three regulate to the reference itself — but every deck prints
# vos as `vout - 4*Vref`, so the reader undoes that with tb_vref.
_LDO_BENCH = {
    'ldo_basic': LdoBench(vout=1.6, supply=1.8, tb_vref=0.4,
                          i_max=55e-3, i_min=5e-3),
    'ldo_1': LdoBench(vout=1.6, supply=1.8, tb_vref=0.4,
                      i_max=100e-3, i_min=1e-3),
    'ldo_2': LdoBench(vout=1.6, supply=1.8, tb_vref=1.6,
                      i_max=100e-3, i_min=1e-3),
    'ldo_simple': LdoBench(vout=1.8, supply=2.0, tb_vref=1.8,
                           i_max=10e-3, i_min=10e-6),
    'ldo_folded_cascode': LdoBench(vout=1.8, supply=2.0, tb_vref=1.8,
                                   i_max=10e-3, i_min=10e-6),
}
_LDO_VARIANTS = {'ldo_simple': 'ldo_simple', 'ldo_1': 'ldo_1_ACDC',
                 'ldo_2': 'ldo_2_ACDC',
                 'ldo_folded_cascode': 'ldo_folded_cascode'}

#: where a variant's own targets differ from Basic LDO's, from the
#: characterisation in cairn/pitfalls.md ("The four LDO variants,
#: characterised"): ldo_2 regulates well and is bound by line
#: regulation (0.044 at best, stable); ldo_simple is stable with GBW
#: to spare and regulates like a simple LDO (LR 6 /A, LNR 0.05, PSRR
#: -40 dB at best).  Set where the archive's best point keeps a 10-15 %
#: margin on every metric but the stability ones — a first cut at the
#: exact numbers (1 MHz, 0.05) was 13 % and 7 % outside what any point
#: reached and no cold seed closed it.  The maintainer's call,
#: 2026-09-26.  ldo_1 and the folded cascode keep Basic LDO's: the
#: decks measure a real 0 dB crossing and no sizing in 1200-1700
#: simulated rows holds 45 degrees at both loads (ldo_1 has no
#: compensation element among its variables).
_LDO_TARGETS = {'ldo_2': {'gbw_maxload': 5e5, 'lnr': 0.06},
                'ldo_simple': {'lr': 10.0, 'lnr': 0.06,
                               'psrr_maxload': -35.0}}


# circuit-skills (PTM) circuits wired into the same optimizer via their
# plot-free simulate_*() metric paths.  The comparator additionally gets a
# fast τ-proxy entry (seconds per eval, probit-verified at the end via
# verify_key), and the bootstrap switch is optimizable through scalar Ron
# metrics post-processed from its gds-based ron testbench.
# Targets sit above the measured default-sizing values (see tests /
# ANALOG_REPOS_ANALYSIS) so the optimizer has headroom in each direction.
_SKILL_CIRCUITS: dict[str, dict] = {
    # targets calibrated against measured defaults on ngspice-42:
    # ota5t 34.3 dB / 85 MHz / PM 77.2°; opamp2 64.3 dB / 13.7 MHz /
    # PM 80.7° / 1.72 mW; ldo 51.7 dB / 1.18 MHz / PM 58.6° / PSRR 57.3 dB
    # gain targets on these two are what their boxes can reach, not
    # aspirations: only widths and bias vary (channel length is fixed), so
    # gm/gds is bounded, and DE at 600 / 400 evaluations tops out at 37.4
    # and 65.7 dB.  The earlier 40 / 70 were unreachable by ~3-4 dB.
    'ota5t': dict(
        title='5T OTA — circuit-skills (PTM 180 nm)',
        fixed=('C_LOAD',), eval_seconds=2.0,
        metrics=[
            MetricSpec('dc_gain_db', 'DC gain', 'dB', 36.0, 'max', 2.0),
            MetricSpec('ugb_hz', 'UGB', 'Hz', 100e6, 'max', 2.0),
            MetricSpec('phase_margin_deg', 'Phase margin', 'deg', 60.0,
                       'max', 1.5),
        ]),
    'opamp2': dict(
        title='Two-stage Miller op amp — circuit-skills (PTM 180 nm)',
        fixed=('CL',), eval_seconds=5.0,
        metrics=[
            MetricSpec('dc_gain_db', 'DC gain', 'dB', 64.0, 'max', 2.0),
            MetricSpec('ugb_hz', 'UGB', 'Hz', 40e6, 'max', 2.0),
            MetricSpec('phase_margin_deg', 'Phase margin', 'deg', 60.0,
                       'max', 1.5),
            MetricSpec('power_w', 'Power', 'W', 2e-3, 'min', 1.0),
        ]),
    'ldo': dict(
        title='LDO — circuit-skills (PTM 180 nm)',
        fixed=('R_LOAD_DEFAULT',), eval_seconds=5.0,
        metrics=[
            MetricSpec('dc_gain_db', 'Loop DC gain', 'dB', 55.0, 'max', 1.5),
            MetricSpec('gbw_hz', 'Loop GBW', 'Hz', 2e6, 'max', 1.5),
            MetricSpec('phase_margin_deg', 'Phase margin', 'deg', 60.0,
                       'max', 1.5),
            # circuit-skills LDO reports PSRR as positive rejection dB
            MetricSpec('psrr_dc_db', 'PSRR (dc)', 'dB', 60.0, 'max', 1.0),
        ]),
    # comparator defaults measured on ngspice-42: σ=178.6 µV,
    # P=104 µW, Tcmp=55.3 ps (162 s per evaluation, 3x1000 cycles)
    'comparator': dict(
        title='StrongArm comparator — circuit-skills (PTM 45 nm, '
              '~2 min/eval)',
        fixed=('NOISE_VIN_MV',), eval_seconds=160.0,
        metrics=[
            MetricSpec('sigma_uv', 'Input noise σ', 'uV', 150.0,
                       'absmin', 1.5),
            MetricSpec('p_avg_uw', 'Avg power', 'uW', 80.0, 'min', 1.0),
            MetricSpec('tcmp_ps', 'Decision time', 'ps', 50.0, 'min', 1.0),
        ]),
}


def _build_registry() -> dict[str, SizingSpec]:
    reg: dict[str, SizingSpec] = {}
    for name in _AMP_NETLISTS:
        short = name[:-6]                     # drop the _Pin_3 suffix
        key = 'amp_' + short.lower()
        sch = f'{name}.png'
        if not (paths.analoggym_dir() / 'amp' / 'schematic' / sch).is_file():
            sch = None
        metrics = _amp_metrics()
        if name in _AMP_POWER_CAP:
            metrics = [replace(m, target=_AMP_POWER_CAP[name])
                       if m.key == 'power' else m for m in metrics]
        reg[key] = SizingSpec(
            title=f'3-stage op amp — {short} (SKY130, 1.8 V)',
            kind='amp', netlist=name, variables=name,
            testbench='TB_Amplifier_ACDC.cir', metrics=metrics,
            fixed=('CLOAD', 'VCM'), schematic=sch, eval_seconds=3.5,
            subckt=name)
    bench = _LDO_BENCH['ldo_basic']
    reg['ldo_basic'] = SizingSpec(
        title=f'Basic LDO (SKY130, {_ldo_conditions(bench)})',
        kind='ldo', netlist='LDO_netlist.txt', variables='LDO_variables.txt',
        testbench='TB_LDO_ACDC.cir', metrics=_ldo_metrics_spec(bench),
        fixed=('M_CL',), eval_seconds=8.0, wrdata_prefix='LDO_TB_ACDC',
        bench=bench)
    for v, prefix in _LDO_VARIANTS.items():
        bench = _LDO_BENCH[v]
        own = _LDO_TARGETS.get(v, {})
        metrics = [replace(m, target=own[m.key]) if m.key in own else m
                   for m in _ldo_metrics_spec(bench)]
        reg[v] = SizingSpec(
            title=f'LDO — {v} (SKY130, {_ldo_conditions(bench)})',
            kind='ldo', netlist=f'{v}.txt', variables=f'{v}_vars.spice',
            testbench=f'{v}_acdc.cir', metrics=metrics,
            fixed=('M_CL',), eval_seconds=8.0, wrdata_prefix=prefix,
            bench=bench)
    for key, cfg in _SKILL_CIRCUITS.items():
        reg[f'skill_{key}'] = SizingSpec(
            title=cfg['title'], kind='skill', netlist='', variables='',
            testbench='', metrics=cfg['metrics'], fixed=cfg['fixed'],
            eval_seconds=cfg['eval_seconds'], skill_key=key)
    # fast comparator proxy: seconds-per-eval latch-tau + total-width
    # objective; the best point is re-verified with one full probit run
    # (defaults measured on ngspice-42: tau=8.6 ps, weighted ΣW=22 um)
    reg['skill_comparator_fast'] = SizingSpec(
        title='StrongArm comparator — fast τ proxy, probit-verified '
              '(PTM 45 nm)',
        kind='skill', netlist='', variables='', testbench='',
        metrics=[
            MetricSpec('tau_ps', 'Latch τ (speed proxy)', 'ps', 6.0,
                       'min', 2.0),
            MetricSpec('total_w_um', 'Σ width (power proxy)', 'um', 18.0,
                       'min', 1.0),
        ],
        fixed=('NOISE_VIN_MV',), eval_seconds=1.0,
        skill_key='comparator', mode='fast',
        verify_key='skill_comparator')
    # bootstrapped switch: app-layer scalars from the ron arrays
    # (defaults measured on ngspice-42: Ron_max=86.3 ohm, flatness=1.25)
    reg['skill_bootstrap'] = SizingSpec(
        title='Bootstrapped switch — circuit-skills (PTM 180 nm)',
        kind='skill', netlist='', variables='', testbench='',
        metrics=[
            MetricSpec('ron_bts_max', 'Ron max (track)', 'ohm', 70.0,
                       'min', 1.5),
            MetricSpec('ron_flat', 'Ron max/min', '', 1.2, 'min', 1.5),
        ],
        fixed=(), eval_seconds=1.5, skill_key='bootstrap', mode='ron')
    # original studio_circuits (authored for this app, not vendored):
    # single-stage PMOS-input current-mirror OTA on SKY130, reusing the
    # AnalogGym amp testbench/harness for the full 9-metric report
    reg['studio_cm_ota'] = SizingSpec(
        title='Current-mirror OTA — Analog Studio (SKY130, 1.8 V)',
        kind='amp', netlist='CM_OTA_Pin_3', variables='CM_OTA_Pin_3',
        testbench='TB_Amplifier_ACDC.cir', metrics=_cm_ota_metrics(),
        fixed=('CLOAD', 'VCM'), eval_seconds=3.5,
        subckt='CM_OTA_Pin_3', pkg='studio', schematic='CM_OTA_Pin_3.png')
    return reg


SIZING: dict[str, SizingSpec] = _build_registry()

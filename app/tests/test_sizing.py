"""Tests for the AnalogGym sizing adapter (Sizing tab core)."""

import os
import re
import shutil

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest

from app import paths
paths.init_runtime()

from app.core import sizing

needs_ngspice = pytest.mark.skipif(
    shutil.which('ngspice') is None, reason='ngspice not installed')


# ── registry / parsing (no ngspice needed) ───────────────────────────────────
def test_registry_and_assets():
    assert set(sizing.SIZING) >= {'amp_hoilee_affc', 'ldo_basic',
                                  'ldo_simple', 'ldo_folded_cascode',
                                  'skill_ota5t', 'skill_opamp2',
                                  'skill_ldo', 'skill_comparator',
                                  'skill_comparator_fast', 'skill_bootstrap',
                                  'studio_cm_ota'}
    # 15 amps + basic LDO + 4 variants + 6 circuit-skills (PTM)
    # + 1 studio_circuits amp (current-mirror OTA); user imports excluded
    assert len([k for k, s in sizing.SIZING.items()
                if s.pkg != 'user']) == 27
    for key, spec in sizing.SIZING.items():
        assert spec.metrics, key
        assert sizing.parse_variables(key), key
        if spec.kind == 'skill':
            from app.core import circuits
            assert spec.skill_key in circuits.CIRCUITS, key
            assert sizing.schematic_path(key) is not None, key
            continue
        root = sizing._pkg_root(spec) / spec.kind
        assert (root / 'netlist' / spec.netlist).is_file(), key
        assert (root / 'variables' / spec.variables).is_file(), key
        assert (root / 'testbench' / spec.testbench).is_file(), key
        if spec.kind == 'amp':               # shared TB → subckt substituted
            assert spec.subckt == spec.netlist, key
        # every built-in amp/ldo has a redrawn schemdraw schematic
        # (tools/gen_sizing_schematics.py) — non-None and non-trivial
        if spec.kind in ('amp', 'ldo') and spec.pkg == 'analoggym':
            sp = sizing.schematic_path(key)
            assert sp is not None and sp.is_file(), key
            assert sp.stat().st_size > 10_000, key
    assert (paths.analoggym_dir() / 'pdk' / 'sky130_pdk.zip').is_file()
    assert (paths.analoggym_dir() / 'LICENSE').is_file()   # BSD-3


def test_skill_variables_fixed_and_bounds():
    ota = sizing.parse_variables('skill_ota5t')
    names = {v.name for v in ota}
    assert 'C_LOAD' not in names             # TB condition stays fixed
    assert {'W_IN_UM', 'W_LOAD_UM', 'W_TAIL_UM', 'VBIAS', 'VCM'} <= names
    for v in ota:
        assert v.lo <= v.default <= v.hi, v
        if v.name.startswith('V'):
            assert v.hi <= 1.8               # rail-capped bias voltages
    comp = {v.name for v in sizing.parse_variables('skill_comparator')}
    assert 'W.inp' in comp and 'NOISE_VIN_MV' not in comp
    fast = {v.name for v in sizing.parse_variables('skill_comparator_fast')}
    assert fast == {'W.inp', 'W.tail', 'W.lat_n', 'W.lat_p', 'W.rst'}
    bts = {v.name for v in sizing.parse_variables('skill_bootstrap')}
    assert bts == {'W.sw', 'FCLK'}


def test_fast_comparator_spec():
    spec = sizing.SIZING['skill_comparator_fast']
    assert spec.mode == 'fast'
    assert spec.verify_key == 'skill_comparator'
    assert spec.eval_seconds < 10        # the whole point of the proxy


def test_parse_variables():
    amp = sizing.parse_variables('amp_hoilee_affc')
    ldo = sizing.parse_variables('ldo_basic')
    assert len(amp) == 33 and len(ldo) == 20
    for v in amp + ldo:
        assert v.lo <= v.default <= v.hi, v
    names = {v.name for v in amp}
    assert 'CLOAD' not in names and 'VCM' not in names   # TB conditions fixed
    assert 'CURRENT_0_BIAS' in names
    m_cl = {v.name.lower() for v in ldo}
    assert 'm_cl' not in m_cl                            # board-level cap


def test_change_summary():
    """Device-grouped before/after table; unchanged variables collapse."""
    defaults = {v.name: v.default
                for v in sizing.parse_variables('amp_hoilee_affc')}
    # no changes at all
    s = sizing.change_summary('amp_hoilee_affc', dict(defaults))
    assert 'unchanged' in s and 'MOSFET' not in s
    # one device + one flat variable changed
    best = dict(defaults)
    best['MOSFET_9_2_W_gm1_PMOS'] = defaults['MOSFET_9_2_W_gm1_PMOS'] * 4
    best['CURRENT_0_BIAS'] = defaults['CURRENT_0_BIAS'] / 2
    s = sizing.change_summary('amp_hoilee_affc', best)
    assert 'MOSFET_9_2' in s and 'gm1_PMOS' in s and '->' in s
    assert 'CURRENT_0_BIAS' in s
    assert 'unchanged' in s
    # skill circuits fall back to flat per-variable lines
    d2 = {v.name: v.default
          for v in sizing.parse_variables('skill_comparator_fast')}
    b2 = dict(d2)
    k = next(iter(b2))
    b2[k] = b2[k] * 2
    s2 = sizing.change_summary('skill_comparator_fast', b2)
    assert k in s2 and '->' in s2


def test_report_includes_change_summary():
    run = sizing.SizingRun(
        circuit='amp_hoilee_affc', best_values={'CURRENT_0_BIAS': 1e-5},
        best_metrics={'dcgain': 92.0}, initial_cost=3.4, best_cost=1.2,
        history=[(1, 3.4), (2, 1.2)], evals=2, cancelled=False, elapsed=1.0)
    rep = run.report()
    assert 'device changes vs default' in rep
    assert 'CURRENT_0_BIAS' in rep


def test_score_directions():
    spec_key = 'amp_hoilee_affc'
    perfect = {'dcgain': 120, 'gain_bandwidth_product': 2e6,
               'phase_in_deg': 60, 'dcpsrp': -80, 'dcpsrn': -80,
               'cmrrdc': -80, 'power': 0.1e-3, 'vos25': 1e-6, 'tc': 1e-6,
               'tsettle': 1e-6}
    assert sizing.score(spec_key, perfect) == 0.0
    worse = dict(perfect, dcgain=50)
    assert sizing.score(spec_key, worse) > 0
    assert sizing.score(spec_key, {}) > 10               # missing → penalty
    # phase margin is a floor, not an equality: 78 deg is met, 50 is not.
    # As an equality target it was met only at exactly 60.000, which no
    # amplifier here ever reported — "all targets met" was unreachable.
    assert sizing.score(spec_key, dict(perfect, phase_in_deg=78.3)) == 0.0
    assert sizing.score(spec_key, dict(perfect, phase_in_deg=50.0)) > 0
    # ...and a floor only, again: the 156 deg design the floor once
    # admitted is charged for what it actually costs, settling time
    assert sizing.score(spec_key, dict(perfect, phase_in_deg=156.0)) == 0.0
    slow = sizing.score(spec_key, dict(perfect, tsettle=19e-6))
    assert slow == pytest.approx(8.5)           # (19 - 2) / 2
    assert sizing.score(spec_key, dict(perfect, tsettle=3e-6)) == \
        pytest.approx(0.5)
    assert all(d.met for d in sizing.score_detail(
        spec_key, dict(perfect, phase_in_deg=59.86))) is False


def test_score_overrides_and_hard():
    key = 'amp_hoilee_affc'
    m = {'dcgain': 90, 'gain_bandwidth_product': 2e6, 'phase_in_deg': 60,
         'dcpsrp': -80, 'dcpsrn': -80, 'cmrrdc': -80, 'power': 0.1e-3,
         'vos25': 1e-6, 'tc': 1e-6, 'tsettle': 1e-6}
    base = sizing.score(key, m)                          # dcgain 90 < 100
    assert base > 0
    # relaxing the target to 80 clears the violation
    assert sizing.score(key, m, {'dcgain': (80.0, False)}) == 0.0
    # hard flag multiplies the same violation by 10
    hard = sizing.score(key, m, {'dcgain': (100.0, True)})
    assert abs(hard - base * 10) < 1e-9


# ── real evaluations (ngspice) ───────────────────────────────────────────────
def test_settling_is_measured_against_the_commanded_step():
    """A follower that never reaches the step must not count as settled
    at its own final value — that was the 156-degree design."""
    from app.core.sizing.evaluation import STEP_AT, settling
    import numpy as np
    t = np.linspace(0, 20e-6, 1001)
    v = np.where(t < STEP_AT, 0.45, 0.55 - 0.02 * np.exp(-(t - STEP_AT) / 2e-7))
    s = settling(t, v)
    assert 0.5e-6 < s['tsettle'] < 0.7e-6 and s['overshoot'] <= 1e-9
    stuck = np.where(t < STEP_AT, 0.45, 0.527)      # 23 mV short, for ever
    assert settling(t, stuck)['tsettle'] == pytest.approx(20e-6 - STEP_AT)
    ring = np.where(t < STEP_AT, 0.45, 0.55 + 0.03 * np.exp(
        -(t - STEP_AT) / 5e-7) * np.cos(2e7 * (t - STEP_AT)))
    r = settling(t, ring)
    assert r['overshoot'] == pytest.approx(0.3, abs=0.02)
    assert 1.5e-6 < r['tsettle'] < 2.5e-6


@needs_ngspice
def test_amp_evaluate_default():
    values = {v.name: v.default for v in
              sizing.parse_variables('amp_hoilee_affc')}
    m = sizing.evaluate('amp_hoilee_affc', values)
    # default HoiLee_AFFC sizing measured on ngspice-42 (see analysis doc)
    assert 80 < m['dcgain'] < 100
    assert m['tsettle'] > 0 and 'overshoot' in m      # the step ran
    assert m['gain_bandwidth_product'] > 1e5
    assert m['power'] > 0
    assert 0 < sizing.score('amp_hoilee_affc', m) < 50


@needs_ngspice
def test_ldo_evaluate_default():
    values = {v.name: v.default for v in sizing.parse_variables('ldo_basic')}
    m = sizing.evaluate('ldo_basic', values)
    assert m['pm_maxload'] > 0 and m['gbw_maxload'] > 1e4
    assert m['lnr'] > 0 and m['iq'] > 0


@needs_ngspice
def test_a_failed_ldo_simulation_does_not_inherit_the_last_points_metrics(
        monkeypatch):
    """Two unrelated LDO sizings once reported byte-identical metrics: the
    second's ngspice run had died on an out-of-range device, and the
    reader took the first's wrdata files, still in the slot, as its
    result.  A failed run must come back empty, not as its predecessor."""
    from app.core.sizing import evaluation as ev
    values = {v.name: v.default for v in sizing.parse_variables('ldo_basic')}
    good = sizing.evaluate('ldo_basic', values, slot=9)
    assert good.get('gbw_maxload', 0) > 1e4
    # the next run in the same slot produces nothing at all
    monkeypatch.setattr(ev, '_ngspice_cmd', lambda: 'true')
    again = sizing.evaluate('ldo_basic', values, slot=9)
    assert 'gbw_maxload' not in again and 'lr' not in again, again
    assert sizing.score('ldo_basic', again) > 10       # missing → penalty


@needs_ngspice
def test_micro_optimize_and_render(tmp_path):
    variables = sizing.parse_variables('amp_hoilee_affc')
    seen = []
    run = sizing.optimize('amp_hoilee_affc', variables, budget=5,
                          progress=lambda n, c, m: seen.append((n, c)))
    assert run.evals == 5 and len(run.history) == 5
    assert run.best_cost <= run.initial_cost
    assert seen == run.history
    assert 'best design variables' in run.report()
    assert 'CURRENT_0_BIAS' in run.params_text()
    png = sizing.render_convergence(run)
    assert png.is_file() and png.stat().st_size > 1000


@needs_ngspice
def test_amp_variant_evaluate():
    """A non-HoiLee amp exercises the DUT-name substitution path."""
    values = {v.name: v.default for v in
              sizing.parse_variables('amp_leung_dfcfc2')}
    m = sizing.evaluate('amp_leung_dfcfc2', values)
    assert m['dcgain'] > 60 and m['gain_bandwidth_product'] > 1e5


_LDOS = ('ldo_basic', 'ldo_1', 'ldo_2', 'ldo_simple', 'ldo_folded_cascode')


def test_ldo_bench_table_matches_the_decks():
    """Every LDO deck types its own supply, reference and load points into
    its measurements; the bench table the reader undoes them with must
    say the same numbers, or the mapping is wrong on that circuit."""
    import re
    for key in _LDOS:
        spec = sizing.SIZING[key]
        tb = (paths.analoggym_dir() / 'ldo' / 'testbench'
              / spec.testbench).read_text()
        param = dict(re.findall(r'^\.PARAM\s+(\w+)\s*=\s*(\S+)', tb,
                                re.MULTILINE | re.IGNORECASE))
        b = spec.bench
        assert float(param['supply_voltage']) == b.supply, key
        assert float(param['Vref']) == b.tb_vref, key
        # the deck prints vos = vout - 4*Vref: the only thing the reader
        # needs from the deck's arithmetic
        assert f'-4*{param["Vref"]}' in tb.replace(' ', ''), key
        loads = sorted({sizing.spec._parse_num(x) for x in
                        re.findall(r'^alter Iload3 dc=(\S+)', tb,
                                   re.MULTILINE)})
        assert len(loads) == 2, (key, loads)
        assert loads[0] == pytest.approx(b.i_min), (key, loads)
        assert loads[1] == pytest.approx(b.i_max), (key, loads)
        # the regulated output is the reference through the feedback:
        # a 4:1 divider (r0/r1 or the Basic_LDO ladder) or none
        netlist = (paths.analoggym_dir() / 'ldo' / 'netlist'
                   / spec.netlist).read_text()
        divided = bool(re.search(r'^r0 vout vfb 300e3', netlist,
                                 re.MULTILINE | re.IGNORECASE)) \
            or key == 'ldo_basic'
        assert b.vout == (4 * b.tb_vref if divided else b.tb_vref), key


def test_ldo_metric_fold_undoes_the_decks_arithmetic(tmp_path):
    """The deck prints vos = vout - 4*Vref and Power = -Ivdd*supply.  The
    reader reconstructs vout, takes the error against the circuit's own
    regulated output, and takes the load current off the supply current
    at min load; the first version did all of that with Basic_LDO's
    numbers on every variant (−5 V output errors at the defaults)."""
    from app.core.sizing import evaluation as ev
    spec = sizing.SIZING['ldo_simple']       # 2 V in, 1.8 V out, 10 uA
    row = [(1e-5, v) for v in (4.28, 20.5e-3, 0.6e-3, 1.803 - 7.2,
                               1.881 - 7.2)]
    (tmp_path / 'ldo_simple_LR_Power_vos').write_text(
        ' '.join(f'{x:.8e}' for pair in row for x in pair) + '\n')
    m = ev._ldo_metrics(tmp_path, {}, spec)
    assert abs(m['vout_maxload'] - 1.803) < 1e-9
    assert abs(m['vos_maxload'] - 0.003) < 1e-9
    assert abs(m['vos_minload'] - 0.081) < 1e-9
    assert abs(m['iq'] - (0.6e-3 / 2.0 - 10e-6)) < 1e-12
    assert m['lr'] == 4.28 and m['power_maxload'] == 20.5e-3


@needs_ngspice
def test_ldo_variant_evaluate():
    """All four variants at their shipped defaults.  ldo_1 exercises the
    ../simulations/ include mapping and the _ACDC wrdata prefix;
    ldo_simple names its testbench after its wrdata prefix, which the
    output clearing once deleted before ngspice ran.  The output must
    sit near each circuit's own reference: the folded cascode's default
    really is 0.31 V low at 10 mA, everything else is within 30 mV."""
    for key in _LDOS[1:]:
        values = {v.name: v.default for v in sizing.parse_variables(key)}
        m = sizing.evaluate(key, values)
        for k in ('pm_maxload', 'gbw_maxload', 'lnr', 'lr', 'iq',
                  'vos_maxload', 'vout_minload'):
            assert k in m, (key, k)
        bench = sizing.SIZING[key].bench
        assert abs(m['vout_maxload'] - bench.vout) < 0.35, (key, m)
        assert abs(m['vout_minload'] - bench.vout) < 0.1, (key, m)
        assert 0 < m['iq'] < 5e-3, (key, m['iq'])


@needs_ngspice
def test_studio_cm_ota_evaluate_and_optimize():
    """The original current-mirror OTA (studio_circuits, not AnalogGym)
    reuses the shared amp harness via _pkg_root and yields the full
    9-metric report; a micro-optimization must not raise its cost."""
    spec = sizing.SIZING['studio_cm_ota']
    assert spec.pkg == 'studio'
    variables = sizing.parse_variables('studio_cm_ota')
    names = {v.name for v in variables}
    assert {'CURRENT_0_BIAS', 'W_IN', 'M_MIRO', 'L_LOAD'} <= names
    assert 'CLOAD' not in names and 'VCM' not in names   # TB conditions fixed
    values = {v.name: v.default for v in variables}
    m = sizing.evaluate('studio_cm_ota', values)
    # single-stage current-mirror OTA on a 500 pF load: ~42 dB / ~0.37 MHz
    assert 30 < m['dcgain'] < 55
    assert m['gain_bandwidth_product'] > 1e5
    assert m['phase_in_deg'] > 45
    assert 0 < m['power'] < 5e-3
    run = sizing.optimize('studio_cm_ota', variables, budget=6,
                          algo='sobol_powell', workers=2)
    assert run.evals == 6
    assert run.best_cost <= run.initial_cost


@needs_ngspice
def test_wave_capture_and_compare(tmp_path):
    """Waveform capture cross-checks its own .meas values and renders the
    before/after overlay; non-amp circuits are rejected."""
    import numpy as np
    defaults = {v.name: v.default
                for v in sizing.parse_variables('amp_hoilee_affc')}
    w = sizing.capture_waves('amp_hoilee_affc', defaults, 'test')
    assert {'freq', 'adm_db', 'adm_ph', 'psrp_db', 'psrn_db',
            'temp', 'vout'} <= set(w)
    assert np.all(np.diff(w['freq']) > 0)
    assert len(w['freq']) == len(w['adm_db'])
    # the first AC point (0.1 Hz) IS the dcgain .meas point
    assert abs(w['adm_db'][0] - w['metrics']['dcgain']) < 0.1
    png = sizing.render_wave_comparison('amp_hoilee_affc', w, w)
    assert png.is_file() and png.stat().st_size > 1000


@needs_ngspice
def test_wave_capture_ldo():
    """LDO capture harvests both AC sweeps from the TB's plot lines and
    the line-regulation DC sweep (injected for ldo_basic)."""
    import numpy as np
    defaults = {v.name: v.default for v in sizing.parse_variables('ldo_basic')}
    w = sizing.capture_waves('ldo_basic', defaults, 'test')
    assert w['kind'] == 'ldo'
    assert 'lg_max' in w and 'lg_min' in w and 'vin' in w
    g = w['lg_max']
    assert np.all(np.diff(g['freq']) > 0)
    # first AC point (0.1 Hz) is the dcgain_maxload .meas point
    assert abs(g['gain_db'][0] - w['metrics']['dcgain_maxload']) < 0.1
    png = sizing.render_wave_comparison('ldo_basic', w, w)
    assert png.is_file() and png.stat().st_size > 1000


@needs_ngspice
def test_wave_capture_skill():
    """Skill captures reuse the simulate_* arrays (no netlist changes)."""
    import numpy as np
    ota = {v.name: v.default for v in sizing.parse_variables('skill_ota5t')}
    w = sizing.capture_waves('skill_ota5t', ota, 'test')
    assert w['kind'] == 'skill_ac'
    assert np.all(np.diff(w['freq']) > 0)
    assert abs(w['gain_db'][0] - w['metrics']['dc_gain_db']) < 0.5
    assert sizing.render_wave_comparison('skill_ota5t', w, w).is_file()

    bts = {v.name: v.default
           for v in sizing.parse_variables('skill_bootstrap')}
    w2 = sizing.capture_waves('skill_bootstrap', bts, 'test')
    assert w2['kind'] == 'skill_ron'
    assert len(w2['vin_pts']) == len(w2['ron_bts']) > 10
    assert sizing.render_wave_comparison('skill_bootstrap', w2, w2).is_file()

    cmp_ = {v.name: v.default
            for v in sizing.parse_variables('skill_comparator_fast')}
    w3 = sizing.capture_waves('skill_comparator_fast', cmp_, 'test')
    assert w3['kind'] == 'skill_wave'
    assert w3['metrics']['tau_ps'] > 0 and len(w3['time']) > 100
    assert sizing.render_wave_comparison(
        'skill_comparator_fast', w3, w3).is_file()


@needs_ngspice
@pytest.mark.skipif(not sizing.optuna_available(),
                    reason='optuna not installed')
def test_optuna_micro_run():
    variables = sizing.parse_variables('amp_hoilee_affc')
    run = sizing.optimize('amp_hoilee_affc', variables, budget=4,
                          algo='optuna')
    assert run.evals == 4 and len(run.history) == 4
    assert run.best_cost <= run.initial_cost


@needs_ngspice
def test_skill_ota_evaluate_and_micro_optimize():
    vals = {v.name: v.default for v in sizing.parse_variables('skill_ota5t')}
    m = sizing.evaluate('skill_ota5t', vals)
    # measured defaults on ngspice-42: 34.3 dB, 85 MHz, PM 77.2°
    assert 25 < m['dc_gain_db'] < 45
    assert m['ugb_hz'] > 1e7
    assert 40 < m['phase_margin_deg'] < 120
    run = sizing.optimize('skill_ota5t', sizing.parse_variables('skill_ota5t'),
                          budget=5)
    assert run.evals == 5 and run.best_cost <= run.initial_cost
    assert 'W_IN_UM' in run.params_text()    # skill export = name = value


@needs_ngspice
def test_skill_opamp_and_ldo_evaluate():
    vals = {v.name: v.default for v in sizing.parse_variables('skill_opamp2')}
    m = sizing.evaluate('skill_opamp2', vals)
    assert m['power_w'] > 0 and m['dc_gain_db'] > 50
    vals = {v.name: v.default for v in sizing.parse_variables('skill_ldo')}
    m = sizing.evaluate('skill_ldo', vals)
    assert m['gbw_hz'] > 1e5 and m['psrr_dc_db'] > 20


@needs_ngspice
def test_optimize_cancel():
    variables = sizing.parse_variables('amp_hoilee_affc')
    run = sizing.optimize('amp_hoilee_affc', variables, budget=50,
                          should_cancel=lambda: True)
    # cancelled before the second evaluation; the initial one is kept
    assert run.cancelled and run.evals <= 1


def test_optimize_seed_reaches_the_search(monkeypatch):
    """seed=0 was hardcoded three times; the second seed is the cheapest
    second opinion on a stochastic search, so it has to be a parameter."""
    import numpy as np
    import scipy.optimize as so
    seen = []

    def fake_de(func, bounds, **kw):
        seen.append(kw['seed'])
        return so.OptimizeResult(population=np.zeros((1, len(bounds))),
                                 population_energies=np.array([1.0]))

    monkeypatch.setattr(so, 'differential_evolution', fake_de)
    variables = sizing.parse_variables('amp_hoilee_affc')
    for s in (0, 7):
        sizing.optimize('amp_hoilee_affc', variables, budget=10,
                        algo='diff_evolution', seed=s)
    assert seen == [0, 7]


@needs_ngspice
def test_continue_a_de_run_from_its_population():
    """Re-running at twice the budget replays the first half.  A DE run
    keeps its last population; continuing from it serves those points
    from memory, so every evaluation in the budget is a new one, and the
    previous best is the starting point of the new curve."""
    variables = sizing.parse_variables('studio_cm_ota')   # 15 dims: 60/gen
    first = sizing.optimize('studio_cm_ota', variables, budget=8,
                            algo='diff_evolution', workers=4)
    # scipy's Sobol init rounds the population up to a power of two
    assert first.continuable and len(first.population) >= 60
    assert sum(c is not None for c in first.population_costs) == 8
    assert all(len(r) == 15 for r in first.population)

    more = sizing.optimize('studio_cm_ota', variables, budget=8,
                           algo='diff_evolution', workers=4, resume=first)
    assert more.evals == 8                     # none of the 8 known re-run
    assert more.history[0] == (0, first.best_cost)
    assert more.initial_cost == first.best_cost
    assert more.best_cost <= first.best_cost
    assert more.continuable and len(more.population) == len(first.population)

    with pytest.raises(ValueError):
        sizing.optimize('studio_cm_ota', variables, budget=8,
                        algo='sobol_powell', resume=first)
    other = sizing.parse_variables('amp_hoilee_affc')
    with pytest.raises(ValueError):
        sizing.optimize('amp_hoilee_affc', other, budget=8,
                        algo='diff_evolution', resume=first)
    first.population = None
    with pytest.raises(ValueError):
        sizing.optimize('studio_cm_ota', variables, budget=8,
                        algo='diff_evolution', resume=first)


@needs_ngspice
def test_de_llm_finish_leaves_the_finish_its_reserve(monkeypatch):
    """The search phase stops short so the finish has points to spend:
    with a budget below the reserve it gets half, and the finish sees the
    whole budget as its cap.  A cancelled search skips the finish."""
    from app.core import llm_sizing
    seen = []

    def fake_finish(circuit, variables, overrides, *, state, run_batch,
                    budget, workers, chat=None):
        seen.append((state['dispatched'], state['cap'], budget))
        return 'fake finish'

    monkeypatch.setattr(llm_sizing, 'run_finish', fake_finish)
    variables = sizing.parse_variables('amp_hoilee_affc')
    run = sizing.optimize('amp_hoilee_affc', variables, budget=8,
                          algo='de_llm_finish', workers=4)
    assert run.evals == 4                        # DE got half of a tiny budget
    assert seen == [(4, 8, 8)]

    seen.clear()
    run = sizing.optimize('amp_hoilee_affc', variables, budget=8,
                          algo='de_llm_finish', should_cancel=lambda: True)
    assert run.cancelled and seen == []


# ── P4: fast comparator proxy / bootstrap metrics / parallel / DE ────────────
@needs_ngspice
def test_skill_comparator_fast_evaluate():
    vals = {v.name: v.default for v in
            sizing.parse_variables('skill_comparator_fast')}
    m = sizing.evaluate('skill_comparator_fast', vals)
    # measured default on ngspice-42: tau = 8.6 ps
    assert 2 < m['tau_ps'] < 30
    # weighted core width: 2*4 + 4 + 2*1 + 2*2 + 4*1 = 22 um
    assert m['total_w_um'] == pytest.approx(22.0)


@needs_ngspice
def test_skill_bootstrap_evaluate():
    vals = {v.name: v.default for v in
            sizing.parse_variables('skill_bootstrap')}
    m = sizing.evaluate('skill_bootstrap', vals)
    # measured default (W.sw = 10 um, 180 nm): max ~86 ohm, flatness ~1.25
    assert 40 < m['ron_bts_max'] < 200
    assert 1.0 <= m['ron_flat'] < 2.0
    # the switch width must actually reach the rendered DUT
    wide = sizing.evaluate('skill_bootstrap', dict(vals, **{'W.sw': 20.0}))
    assert wide['ron_bts_max'] < 0.7 * m['ron_bts_max']


def test_verify_hook(monkeypatch):
    """After a proxy run the best point is re-evaluated on verify_key."""
    calls = []
    orig = sizing.evaluate

    def fake(circuit, values, **kw):
        calls.append(circuit)
        if circuit == 'skill_comparator':
            return {'sigma_uv': 180.0, 'p_avg_uw': 104.0, 'tcmp_ps': 55.0,
                    'fom1': 3.3, 'fom2': 0.18}
        return {'tau_ps': 8.0, 'total_w_um': 22.0}

    # patch where optimize() *looks the name up* — its own module global.
    # sizing.evaluate is only a re-export on the package facade; rebinding
    # that would leave sizing.optimizer.evaluate pointing at the real thing
    # and this test would silently run ngspice for minutes.
    monkeypatch.setattr(sizing.optimizer, 'evaluate', fake)
    variables = sizing.parse_variables('skill_comparator_fast')
    run = sizing.optimize('skill_comparator_fast', variables, budget=3)
    monkeypatch.setattr(sizing.optimizer, 'evaluate', orig)
    assert 'skill_comparator' in calls
    assert run.verified and run.verified['sigma_uv'] == 180.0
    assert 'verified (full evaluation, skill_comparator)' in run.report()


@needs_ngspice
def test_parallel_optimize_slots():
    """4-way parallel Sobol batch: budget honoured, slot dirs created,
    best never worse than the initial point."""
    variables = sizing.parse_variables('amp_hoilee_affc')
    run = sizing.optimize('amp_hoilee_affc', variables, budget=9, workers=4)
    assert run.evals == 9 and len(run.history) == 9
    assert run.best_cost <= run.initial_cost
    base = sizing._run_dir('amp_hoilee_affc')
    assert any((base / f'w{s}').is_dir() for s in (1, 2, 3))


# ── run persistence: save / load / compare / warm start ─────────────────────
def _fake_run(circuit='amp_hoilee_affc', cost=1.2):
    return sizing.SizingRun(
        circuit=circuit,
        best_values={'CURRENT_0_BIAS': 2.5e-6},
        best_metrics={'dcgain': 92.0}, best_cost=cost, initial_cost=3.4,
        history=[(1, 3.4), (2, 2.0), (3, cost)], evals=3, cancelled=False,
        elapsed=12.0, overrides={'dcgain': (100.0, True)})


def test_run_save_load_roundtrip(tmp_path):
    run = _fake_run()
    p = sizing.save_run(run, tmp_path / 'r.json')
    assert sizing.load_run(p) == run          # history tuples + overrides
    info = sizing.run_info(p)
    assert info['circuit'] == 'amp_hoilee_affc' and info['evals'] == 3
    assert 'HoiLee' in info['title']


def test_render_comparison(tmp_path):
    png = sizing.render_comparison(
        [_fake_run(), _fake_run('skill_ota5t', cost=0.5)])
    assert png.is_file() and png.stat().st_size > 1000


def test_runs_dialog_and_warm_start(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    # `sizing.runs_dir` is the package re-export; save_run() and list_runs()
    # resolve the name in runs.py's own globals, so patching it here patched
    # nothing and both wrote to the developer's real saved-runs store.  The
    # test still passed on a machine that had never run it, then counted the
    # previous run's files on the second go.  Patch the submodule.
    monkeypatch.setattr(sizing.runs, 'runs_dir', lambda: tmp_path)
    sizing.save_run(_fake_run())
    sizing.save_run(_fake_run('skill_ota5t', cost=0.5))

    from app.core.worker import SimWorker
    from app.ui.sizing_tab import RunsDialog, SizingTab
    worker = SimWorker()
    try:
        tab = SizingTab(worker)
        dlg = RunsDialog(tab)
        assert dlg._list.rowCount() == 2
        # Continue is offered only for a run that kept a DE population
        dlg._list.selectRow(0)
        assert not dlg.continue_btn.isEnabled()
        kept = _fake_run(cost=0.9)
        kept.algo, kept.population, kept.population_costs = (
            'diff_evolution', [[2.5e-6]], [0.9])
        sizing.save_run(kept)
        dlg._refresh()
        row = next(r for r, i in enumerate(dlg._infos) if i['continuable'])
        dlg._list.selectRow(row)
        assert dlg.continue_btn.isEnabled()
        n = tab.apply_best_to_table(_fake_run())
        assert n == 1                          # CURRENT_0_BIAS exists
        assert tab.circuit_combo.currentData() == 'amp_hoilee_affc'
        vals = {tab._table.item(r, 0).text(): tab._table.item(r, 1).text()
                for r in range(tab._table.rowCount())}
        assert vals['CURRENT_0_BIAS'] == '2.5e-06'
    finally:
        worker.stop()


def test_waves_button_enablement():
    """Waves… enables for every circuit kind once a run is shown."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.core.worker import SimWorker
    from app.ui.sizing_tab import SizingTab
    worker = SimWorker()
    try:
        tab = SizingTab(worker)
        assert not tab.waves_btn.isEnabled()
        tab._show_run(_fake_run())                       # amp_hoilee_affc
        assert tab.waves_btn.isEnabled()
        tab._show_run(_fake_run('skill_ota5t', cost=0.5))
        assert tab.waves_btn.isEnabled()                 # skill too now
    finally:
        worker.stop()


def test_parse_param_file(tmp_path):
    f = tmp_path / 'x.param'
    f.write_text('.PARAM\n+ W_A=2.5 L_A=1u\n+ M_A=4 W_B=W_A\nCLOAD=5p\n')
    v = sizing.parse_param_file(f)
    assert v['W_A'] == 2.5 and v['L_A'] == 1e-6 and v['M_A'] == 4
    assert v['CLOAD'] == 5e-12
    assert 'W_B' not in v                     # expression ref skipped


def _isolate_workspace(tmp_path, monkeypatch):
    """Point both the scratch work dir and the user-data store at tmp."""
    monkeypatch.setenv('ANALOG_WORK_DIR', str(tmp_path / 'work'))
    monkeypatch.setenv('ANALOG_USER_DATA_DIR', str(tmp_path / 'work'))


def _user_files(tmp_path, name='my_ota_t'):
    nl = (paths.studio_circuits_dir() / 'amp' / 'netlist' / 'CM_OTA_Pin_3'
          ).read_text().replace('cm_ota_pin_3', name)
    p1 = tmp_path / f'{name}.sp'
    p1.write_text(nl)
    p2 = tmp_path / f'{name}.param'
    p2.write_text((paths.studio_circuits_dir() / 'amp' / 'variables'
                   / 'CM_OTA_Pin_3').read_text())
    return p1, p2


def test_user_circuit_import_lifecycle(tmp_path, monkeypatch):
    """Import -> register -> netlist view -> rescan persistence -> remove;
    contract violations are rejected."""
    _isolate_workspace(tmp_path, monkeypatch)
    bad = tmp_path / 'bad.sp'
    bad.write_text('.subckt foo a b c\n.ends\n')
    nl, vars_f = _user_files(tmp_path)
    with pytest.raises(ValueError, match='contract'):
        sizing.import_user_circuit(bad, vars_f)
    key = sizing.import_user_circuit(nl, vars_f)
    try:
        assert key == 'user_my_ota_t' and key in sizing.SIZING
        assert sizing.SIZING[key].pkg == 'user'
        assert len(sizing.parse_variables(key)) == 15
        # duplicate import rejected
        with pytest.raises(ValueError, match='already'):
            sizing.import_user_circuit(nl, vars_f)
        # netlist viewer: 3 tabs, rendered TB carries the substituted DUT
        texts = sizing.netlist_texts(key, {'W_IN': 12.0})
        assert [t for t, _ in texts] == [
            'netlist (my_ota_t)', 'variables (with table values)',
            'testbench (rendered)']
        assert 'my_ota_t' in texts[2][1]
        assert 'W_IN=12' in texts[1][1]
        # persistence: drop from the registry, rescan restores it
        del sizing.SIZING[key]
        assert sizing.load_user_circuits() == [key]
    finally:
        sizing.remove_user_circuit(key)
    assert key not in sizing.SIZING
    assert sizing.load_user_circuits() == []          # files gone too


@pytest.mark.parametrize('name', [
    '../../../../tmp/EVIL',      # classic traversal
    '/tmp/EVIL',                 # absolute path
    '..',                        # parent dir
    'a/b',                       # nested write
])
def test_user_import_rejects_path_escape(tmp_path, monkeypatch, name):
    """A crafted .subckt name must never become a path outside the store."""
    _isolate_workspace(tmp_path, monkeypatch)
    nl, vars_f = _user_files(tmp_path, 'placeholder')
    nl.write_text(nl.read_text().replace('placeholder', name))
    with pytest.raises(ValueError, match='contract'):
        sizing.import_user_circuit(nl, vars_f)
    # nothing escaped: the only thing written is inside the workspace
    assert not (tmp_path / 'EVIL').exists()
    assert not list(tmp_path.glob('**/EVIL'))


@pytest.mark.parametrize('block', [
    '.control\nshell touch PROOF\n.endc\n',          # plain
    '.CoNtRoL\nshell touch PROOF\n.endc\n',          # directives fold case
    '   .control\nshell touch PROOF\n.endc\n',       # and may be indented
])
def test_user_import_rejects_control_block(tmp_path, monkeypatch, block):
    """ngspice executes .control blocks, so an imported design carrying one
    would run arbitrary commands on the first evaluation."""
    _isolate_workspace(tmp_path, monkeypatch)
    nl, vars_f = _user_files(tmp_path, 'ctl_ota')
    nl.write_text(nl.read_text() + block)
    with pytest.raises(ValueError, match=r'\.control'):
        sizing.import_user_circuit(nl, vars_f)
    assert 'user_ctl_ota' not in sizing.SIZING
    assert not list((tmp_path / 'work').glob('**/ctl_ota'))   # nothing copied


def test_user_import_rejects_control_block_in_variables(tmp_path, monkeypatch):
    """The .PARAM file is .include'd too — a directive inside an included
    file executes exactly as if it were inline."""
    _isolate_workspace(tmp_path, monkeypatch)
    nl, vars_f = _user_files(tmp_path, 'ctl_vars_ota')
    vars_f.write_text(vars_f.read_text()
                      + '.control\nshell touch PROOF\n.endc\n')
    with pytest.raises(ValueError, match=r'design-variables.*\.control'):
        sizing.import_user_circuit(nl, vars_f)
    assert 'user_ctl_vars_ota' not in sizing.SIZING


def test_load_user_circuits_skips_unvetted_control_block(tmp_path,
                                                         monkeypatch, capsys):
    """A file already in the store — imported before the check existed, or
    dropped in by hand — must not become runnable just by being on disk."""
    _isolate_workspace(tmp_path, monkeypatch)
    root = sizing.user_circuits_dir() / 'amp'
    (root / 'netlist').mkdir(parents=True, exist_ok=True)
    (root / 'variables').mkdir(parents=True, exist_ok=True)
    good_nl, good_vars = _user_files(tmp_path, 'planted_ota')
    (root / 'netlist' / 'planted_ota').write_text(
        good_nl.read_text() + '.control\nshell touch PROOF\n.endc\n')
    (root / 'variables' / 'planted_ota').write_text(good_vars.read_text())
    assert sizing.load_user_circuits() == []
    assert 'user_planted_ota' not in sizing.SIZING
    assert 'planted_ota' in capsys.readouterr().out    # says why it skipped


@needs_ngspice
def test_control_block_would_have_executed(tmp_path, monkeypatch):
    """The guard is worth having: prove the payload really does run when
    ngspice is handed it, so this stays a demonstrated risk and not a
    theoretical one."""
    import subprocess
    proof = tmp_path / 'PROOF'
    deck = tmp_path / 'payload.cir'
    deck.write_text('V1 a 0 1\nR1 a 0 1k\n.control\n'
                    f'shell touch "{proof}"\nquit\n.endc\n.end\n')
    subprocess.run(['ngspice', '-b', str(deck)], cwd=tmp_path,
                   capture_output=True, timeout=60)
    assert proof.exists(), 'ngspice no longer executes .control — re-check ' \
                           'whether the import guard is still needed'


@pytest.mark.parametrize('directive', [
    '.include /etc/hostname\n',           # plain, absolute
    '.INCLUDE /etc/hostname\n',           # directives fold case
    '\t.include "/etc/hostname"\n',       # tab-indented, quoted
    ".inc '/etc/hostname'\n",             # abbreviation, other quote style
    '.lib /etc/hostname tt\n',            # the library form reads files too
])
def test_user_import_rejects_file_includes(tmp_path, monkeypatch, directive):
    """`.include` is how an imported design reaches files it has no business
    reading; the amplifier contract needs none, so none are allowed."""
    _isolate_workspace(tmp_path, monkeypatch)
    nl, vars_f = _user_files(tmp_path, 'inc_ota')
    nl.write_text(nl.read_text() + directive)
    with pytest.raises(ValueError, match=r'\.(?:include|inc|lib)'):
        sizing.import_user_circuit(nl, vars_f)
    assert 'user_inc_ota' not in sizing.SIZING
    assert not list((tmp_path / 'work').glob('**/inc_ota'))   # nothing copied


def test_user_import_rejects_file_includes_in_variables(tmp_path, monkeypatch):
    """Same for the .PARAM file — it is .include'd into the deck as well."""
    _isolate_workspace(tmp_path, monkeypatch)
    nl, vars_f = _user_files(tmp_path, 'inc_vars_ota')
    vars_f.write_text(vars_f.read_text() + '.include /etc/hostname\n')
    with pytest.raises(ValueError, match=r'design-variables.*\.include'):
        sizing.import_user_circuit(nl, vars_f)
    assert 'user_inc_vars_ota' not in sizing.SIZING


def test_load_user_circuits_skips_unvetted_include(tmp_path, monkeypatch,
                                                   capsys):
    """A design imported before this check existed must not start working
    just because its files are already in the store."""
    _isolate_workspace(tmp_path, monkeypatch)
    root = sizing.user_circuits_dir() / 'amp'
    (root / 'netlist').mkdir(parents=True, exist_ok=True)
    (root / 'variables').mkdir(parents=True, exist_ok=True)
    good_nl, good_vars = _user_files(tmp_path, 'planted_inc')
    (root / 'netlist' / 'planted_inc').write_text(
        good_nl.read_text() + '.include /etc/hostname\n')
    (root / 'variables' / 'planted_inc').write_text(good_vars.read_text())
    assert sizing.load_user_circuits() == []
    assert 'user_planted_inc' not in sizing.SIZING
    assert 'planted_inc' in capsys.readouterr().out    # says why it skipped


@needs_ngspice
def test_include_would_have_leaked_the_file(tmp_path):
    """The guard is worth having: ngspice really does open the path and put
    what it read into the log the user sees.  Kept alongside the
    control-block proof so neither guard can quietly become pointless."""
    import subprocess
    secret = tmp_path / 'secret.txt'
    secret.write_text('correct-horse-battery-staple\n')
    deck = tmp_path / 'leak.cir'
    deck.write_text(f'V1 a 0 1\nR1 a 0 1k\n.include "{secret}"\n.op\n.end\n')
    r = subprocess.run(['ngspice', '-b', str(deck)], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    assert 'correct-horse-battery-staple' in (r.stdout + r.stderr), \
        'ngspice no longer echoes included files — re-check whether the ' \
        'import guard is still needed'


def test_score_is_exactly_the_sum_of_its_explanation():
    """score() was re-implemented as sum(score_detail()) so that the number
    the optimizer minimizes and the breakdown the LLM is shown can never
    disagree.  If they drift, the model is told a story about a cost it was
    not scored on."""
    m = {'dcgain': 62.1, 'gain_bandwidth_product': 1.35e6,
         'phase_in_deg': 59.2, 'dcpsrp': -71.0, 'dcpsrn': -68.0,
         'cmrrdc': -64.0, 'power': 8.1e-4, 'vos25': 4.2e-5, 'tc': 6.0e-6,
         'tsettle': 1.1e-6}
    for overrides in (None, {'dcgain': (80.0, True)}):
        detail = sizing.score_detail('amp_hoilee_affc', m, overrides)
        assert len(detail) == len(sizing.SIZING['amp_hoilee_affc'].metrics)
        assert sum(d.contribution for d in detail) == pytest.approx(
            sizing.score('amp_hoilee_affc', m, overrides))
    # a hard constraint weighs 10x, and that has to show up in the part
    soft = next(d for d in sizing.score_detail('amp_hoilee_affc', m)
                if d.spec.key == 'dcgain')
    hard = next(d for d in sizing.score_detail('amp_hoilee_affc', m,
                                               {'dcgain': (100.0, True)})
                if d.spec.key == 'dcgain')
    assert hard.contribution == pytest.approx(soft.contribution * 10)
    assert hard.violation == pytest.approx(soft.violation)   # same physics


def test_score_detail_marks_a_missing_metric_rather_than_hiding_it():
    """A simulation that produced nothing takes the fixed penalty, and the
    breakdown has to say so — otherwise the model reads a huge cost with
    every target apparently met."""
    detail = sizing.score_detail('amp_hoilee_affc', {'dcgain': 120.0})
    absent = [d for d in detail if d.value is None]
    assert len(absent) == len(detail) - 1
    assert all(not d.met for d in absent)


def test_user_data_lives_outside_the_versioned_workspace(tmp_path,
                                                         monkeypatch):
    """Saved runs and imports must not sit under ANALOG_WORK_DIR — that
    tree is versioned and wiped by paths._prune_old_workspaces()."""
    work = tmp_path / 'ws' / '1.4' / 'circuit_work'
    data = tmp_path / 'data'
    monkeypatch.setenv('ANALOG_WORK_DIR', str(work))
    monkeypatch.setenv('ANALOG_USER_DATA_DIR', str(data))
    for d in (sizing.runs_dir(), sizing.user_circuits_dir()):
        assert d.is_relative_to(data)
        assert not d.is_relative_to(work)


def test_upgrade_preserves_user_data(tmp_path):
    """Simulate a 1.3 -> 1.4 upgrade: migrate, then prune.  The old saved
    run and imported circuit survive; the scratch tree does not."""
    ws_parent = tmp_path / 'workspace'
    old = ws_parent / '1.3' / 'circuit_work'
    (old / 'sizing_runs').mkdir(parents=True)
    (old / 'sizing_runs' / 'amp_x_20250101_000000.json').write_text('{}')
    (old / 'user_circuits' / 'amp' / 'netlist').mkdir(parents=True)
    (old / 'user_circuits' / 'amp' / 'netlist' / 'my_ota').write_text('*')
    (old / 'sizing').mkdir()                 # regenerable scratch
    (old / 'sizing' / 'junk.raw').write_text('x')

    new_ws = ws_parent / '1.4'
    data = tmp_path / 'data'
    paths._migrate_user_data(new_ws, data)
    paths._prune_old_workspaces(new_ws)

    assert (data / 'sizing_runs' / 'amp_x_20250101_000000.json').is_file()
    assert (data / 'user_circuits' / 'amp' / 'netlist' / 'my_ota').is_file()
    assert not (ws_parent / '1.3').exists()  # old workspace really is gone


def test_migrate_never_overwrites_existing_data(tmp_path):
    """A name collision keeps the current store's copy."""
    ws_parent = tmp_path / 'workspace'
    old = ws_parent / '1.3' / 'circuit_work' / 'sizing_runs'
    old.mkdir(parents=True)
    (old / 'run.json').write_text('old')
    data = tmp_path / 'data'
    (data / 'sizing_runs').mkdir(parents=True)
    (data / 'sizing_runs' / 'run.json').write_text('current')

    paths._migrate_user_data(ws_parent / '1.4', data)
    assert (data / 'sizing_runs' / 'run.json').read_text() == 'current'


@needs_ngspice
def test_user_circuit_evaluates(tmp_path, monkeypatch):
    """An imported design runs through the full evaluate pipeline."""
    _isolate_workspace(tmp_path, monkeypatch)
    nl, vars_f = _user_files(tmp_path, 'my_ota_e')
    key = sizing.import_user_circuit(nl, vars_f)
    try:
        vals = {v.name: v.default for v in sizing.parse_variables(key)}
        m = sizing.evaluate(key, vals)
        assert 30 < m['dcgain'] < 55           # same silicon as studio CM-OTA
        assert m['gain_bandwidth_product'] > 1e5
    finally:
        sizing.remove_user_circuit(key)


def test_import_params_fill(tmp_path):
    """Import a .PARAM back into the variables table's init column."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.core.worker import SimWorker
    from app.ui.sizing_tab import SizingTab
    worker = SimWorker()
    try:
        tab = SizingTab(worker)
        idx = tab.circuit_combo.findData('studio_cm_ota')
        tab.circuit_combo.setCurrentIndex(idx)
        n = tab._fill_init_values({'W_IN': 33.0, 'NOT_A_VAR': 1.0})
        assert n == 1
        vals = {tab._table.item(r, 0).text(): tab._table.item(r, 1).text()
                for r in range(tab._table.rowCount())}
        assert vals['W_IN'] == '33'
        assert hasattr(tab, 'import_btn') and hasattr(tab, 'netlist_btn')
    finally:
        worker.stop()


@needs_ngspice
def test_diff_evolution_micro():
    variables = sizing.parse_variables('amp_hoilee_affc')
    run = sizing.optimize('amp_hoilee_affc', variables, budget=8,
                          algo='diff_evolution', workers=2)
    assert run.evals <= 8
    assert run.best_cost <= run.initial_cost


def test_show_parser_keeps_devices_and_columns_aligned():
    """ngspice prints `show` three devices to a block, one row per
    parameter, so the *column index* is the only thing tying a number to a
    device.  Get that wrong and every operating point is attributed to the
    wrong transistor — which reads as plausible physics, not as a bug."""
    text = (
        'noise\n---ANALOG-OP-BEGIN---\n'
        ' BSIM4v5: Berkeley Short Channel IGFET Model-4\n'
        '     device m.xop5.xm14.msky130_f m.xop5.xm19.msky130_f\n'
        '      model xop5.xm14:sky130_fd_p xop5.xm19:sky130_fd_p\n'
        '         id           1.0e-05           2.0e-05\n'
        '        vds          0.60              0.09\n'
        '      vdsat          0.11              0.12\n'
        '        vth          0.63              0.61\n'
        '        vgs          0.70              0.70\n'
        '         gm          3.0e-04           2.0e-04\n'
        '        gds          2.0e-06           9.0e-05\n'
        '---ANALOG-OP-END---\ntrailing junk\n')
    from app.core.sizing import evaluation as ev
    ops = ev.parse_show(text)
    assert set(ops) == {'xm14', 'xm19'}
    assert ops['xm14']['id'] == 1.0e-05 and ops['xm19']['id'] == 2.0e-05
    assert ops['xm19']['vds'] == 0.09            # second column, not first
    assert ev.parse_show('nothing here') == {}   # no markers, no guessing


def test_operating_point_text_flags_devices_out_of_saturation():
    """A device in triode is the most useful thing the nine metrics cannot
    say, so it has to survive both the sort and any truncation."""
    from app.core.sizing import evaluation as ev
    ops = {
        'xm1': {'id': 2e-5, 'gm': 1e-4, 'gds': 3e-7, 'vds': 1.3,
                'vdsat': 0.35, 'vgs': 1.3, 'vth': 0.96},          # sat
        'xm2': {'id': 2e-5, 'gm': 1e-4, 'gds': 1e-4, 'vds': 0.10,
                'vdsat': 0.35, 'vgs': 1.3, 'vth': 0.96},          # triode
        'xm3': {'id': 1e-9, 'gm': 1e-9, 'gds': 1e-12, 'vds': 1.0,
                'vdsat': 0.30, 'vgs': 0.10, 'vth': 0.96},         # off
    }
    spec = sizing.SIZING['amp_hoilee_affc']
    text = ev.format_operating_points(spec, ops, {'xm2': {'W': 'W_TAIL'}})
    head, *lines = text.splitlines()
    assert '2 not in saturation' in head
    assert lines[0].startswith('xm3') and 'OFF' in lines[0]     # worst first
    assert 'TRIODE' in lines[1] and 'W=W_TAIL' in lines[1]      # actionable
    assert lines[2].startswith('xm1') and 'sat' in lines[2]
    assert 'gm/ID   5.0' in lines[2]            # 1e-4 / 2e-5


def test_device_variable_map_reads_the_netlist_not_a_guess():
    """An operating point names `xm10`; the thing the model may change is
    called MOSFET_9_2_W_gm1_PMOS.  The netlist carries both on one line,
    and several devices deliberately share one variable (a mirror bank)."""
    from app.core.sizing import evaluation as ev
    vmap = ev.device_variable_map(sizing.SIZING['amp_hoilee_affc'])
    assert vmap['xm10'] == {'L': 'MOSFET_9_2_L_gm1_PMOS',
                            'W': 'MOSFET_9_2_W_gm1_PMOS'}   # the `*1` is gone
    shared = [d for d, v in vmap.items()
              if v['W'] == 'MOSFET_0_8_W_BIASCM_PMOS']
    assert len(shared) > 1, 'a mirror bank shares one variable'


# ── what to try next, from the measured order ────────────────────────────────
_PERFECT = {'dcgain': 120, 'gain_bandwidth_product': 2e6, 'phase_in_deg': 70,
            'dcpsrp': -80, 'dcpsrn': -80, 'cmrrdc': -80, 'power': 0.1e-3,
            'vos25': 1e-6, 'tc': 1e-6, 'tsettle': 1e-6}


def _run_with(metrics, algo='diff_evolution', seed=0, budget=600,
              cancelled=False):
    key = 'amp_hoilee_affc'
    cost = sizing.score(key, metrics)
    return sizing.SizingRun(
        circuit=key, best_values={}, best_metrics=metrics, best_cost=cost,
        initial_cost=3.0, history=[(1, 3.0), (budget, cost)], evals=budget,
        cancelled=cancelled, elapsed=1.0, algo=algo, seed=seed, budget=budget)


def _info(seed, cost, budget=600, circuit='amp_hoilee_affc'):
    return {'circuit': circuit, 'cancelled': False, 'seed': seed,
            'best_cost': cost, 'budget': budget}


def test_next_step_follows_the_measured_order(monkeypatch):
    """finish when close and not yet tried; another seed while fewer than
    three have been; then twice the budget at the best seed.  The order
    is the one sixteen runs at two seeds supported, not a preference."""
    done = sizing.next_step(_run_with(_PERFECT), [])
    assert done['action'] is None and done['text'].startswith('all 10')

    close = _run_with(dict(_PERFECT, phase_in_deg=58.0))   # one miss, 3%
    nxt = sizing.next_step(close, [])
    assert nxt['action'] == 'finish' and nxt['algo'].endswith('llm_finish')
    assert nxt['seed'] == 0 and nxt['budget'] == 600
    # the finish is offered behind the measured default when it exists
    monkeypatch.setattr(sizing.runs, 'cmaes_available', lambda: True)
    assert sizing.next_step(close, [])['algo'] == 'cmaes_llm_finish'
    monkeypatch.setattr(sizing.runs, 'cmaes_available', lambda: False)
    assert sizing.next_step(close, [])['algo'] == 'de_llm_finish'
    # ...and not again after a finish of either kind
    assert sizing.next_step(_run_with(dict(_PERFECT, phase_in_deg=58.0),
                                      algo='cmaes_llm_finish'),
                            [])['action'] == 'seed'
    assert 'Phase margin 58' in nxt['text']

    # no model configured: the finish is not on offer, seeds come first
    nxt = sizing.next_step(close, [], finish_available=False)
    assert nxt['action'] == 'seed' and nxt['seed'] == 1

    far = _run_with(dict(_PERFECT, dcgain=60.0, power=1e-3))
    # the archive's best under the targets beats what the run found: the
    # warm start comes before another seed — it won 14 of 16 rows against
    # a cold search at twice the evaluations; a point no better than the
    # run's own (the run's result is archived too) offers nothing new
    nxt = sizing.next_step(far, [_info(0, far.best_cost)],
                           known={'cost': far.best_cost * 0.5, 'n': 300,
                                  'values': {}})
    assert nxt['action'] == 'warm' and nxt['seed'] == far.seed
    assert 'archive holds a better point' in nxt['text']
    assert '300 archived' in nxt['text']
    nxt = sizing.next_step(far, [_info(0, far.best_cost)],
                           known={'cost': far.best_cost, 'n': 1,
                                  'values': {}})
    assert nxt['action'] == 'seed'
    nxt = sizing.next_step(far, [_info(0, far.best_cost)])
    assert nxt['action'] == 'seed' and nxt['seed'] == 1
    nxt = sizing.next_step(far, [_info(0, 2.0), _info(1, 0.9), _info(2, 1.4)])
    assert nxt['action'] == 'budget' and nxt['budget'] == 1200
    assert nxt['seed'] == 1                    # the seed that did best
    # runs at a smaller budget and on other circuits do not count as tries
    nxt = sizing.next_step(far, [_info(1, 0.9, budget=100),
                                 _info(2, 0.5, circuit='amp_fan_smc')])
    assert nxt['action'] == 'seed'

    stopped = _run_with(dict(_PERFECT, dcgain=60.0), cancelled=True)
    assert sizing.next_step(stopped, [])['action'] is None

    # a run that kept its population is continued, not restarted at 2x
    far.population, far.population_costs = [[1.0] * 33] * 4, [1.0] * 4
    nxt = sizing.next_step(far, [_info(0, 2.0), _info(1, 2.0), _info(2, 2.0)])
    assert nxt['action'] == 'budget' and nxt['resume'] is True
    assert nxt['budget'] == 600 and nxt['seed'] == 0
    # ...unless another seed did better, which is then the one to extend
    nxt = sizing.next_step(far, [_info(0, 2.0), _info(1, 0.5), _info(2, 2.0)])
    assert nxt['resume'] is False and nxt['seed'] == 1


def test_run_record_carries_its_search_and_loads_without_it(tmp_path):
    """algo / seed / budget / notes are what Try-next reads; a run saved
    before they existed has to load with the defaults, and the finish's
    account has to reach the report."""
    import json
    run = _run_with(_PERFECT, algo='de_llm_finish', seed=3, budget=616)
    run.notes = 'round 1: moved 2 of 33 variables (A, B); cost 0.5 -> 0.0'
    p = sizing.save_run(run, tmp_path / 'new.json')
    back = sizing.load_run(p)
    assert (back.algo, back.seed, back.budget) == ('de_llm_finish', 3, 616)
    assert 'search notes:' in back.report() and 'moved 2 of 33' in back.report()
    assert 'de_llm_finish, seed 3' in back.report()
    info = sizing.run_info(p)
    assert (info['algo'], info['seed'], info['budget']) == (
        'de_llm_finish', 3, 616)
    assert info['continuable'] is False        # no population saved
    run.population, run.population_costs = [[1.0, 2.0]], [0.5]
    p2 = sizing.save_run(run, tmp_path / 'pop.json')
    assert sizing.load_run(p2).population == [[1.0, 2.0]]
    assert sizing.run_info(p2)['continuable'] is True

    doc = json.loads(p.read_text())
    for k in ('algo', 'seed', 'budget', 'notes'):
        del doc['run'][k]
    old = tmp_path / 'old.json'
    old.write_text(json.dumps(doc))
    back = sizing.load_run(old)
    assert (back.algo, back.seed, back.budget, back.notes) == ('', 0, 0, '')
    assert 'search notes' not in back.report()


# ── the four searches added after the seed sweep, on a fake objective ───────
def _fake_bowl(monkeypatch):
    """skill_bootstrap has two variables; make its cost a bowl with the
    optimum at (W.sw 30, FCLK 100 MHz), so a search's result is judged
    against a known answer and no ngspice runs."""
    def fake(circuit, values, **kw):
        w = (values['W.sw'] - 30.0) / 38.0
        f = (values['FCLK'] - 1e8) / 1.875e8
        return {'q': 4 * w * w + f * f}
    monkeypatch.setattr(sizing.optimizer, 'evaluate', fake)
    monkeypatch.setattr(sizing.optimizer, 'score',
                        lambda circuit, m, ov=None: m['q'])
    return sizing.parse_variables('skill_bootstrap')


def test_cmaes_converges_and_restarts(monkeypatch):
    pytest.importorskip('cma')
    variables = _fake_bowl(monkeypatch)
    run = sizing.optimize('skill_bootstrap', variables, budget=400,
                          algo='cmaes', workers=1)
    assert run.best_cost < 1e-4, run.best_cost
    assert run.evals <= 400 and run.algo == 'cmaes'
    # the bowl is solved long before 400 evaluations: a stalled run must
    # have restarted with a larger population rather than sat idle
    assert 'run 1: popsize 12' in run.notes      # doubled on restart
    assert 'run 0: popsize 6' in run.notes and 'stopped on tol' in run.notes
    assert run.population is None                # not a DE population


def test_cmaes_surrogate_solves_the_bowl_with_fewer_evaluations(
        monkeypatch):
    """lq-CMA-ES on a quadratic bowl: the model is exact once it has a
    few points, so most of each population is ranked without an
    evaluation and the optimum arrives in fewer than plain CMA-ES
    needs.  Failed points must not reach the model (1e12 in a
    least-squares fit predicts nothing)."""
    pytest.importorskip('cma')
    variables = _fake_bowl(monkeypatch)
    run = sizing.optimize('skill_bootstrap', variables, budget=200,
                          algo='cmaes_surrogate', workers=1)
    assert run.best_cost < 1e-4, run.best_cost
    assert run.evals <= 200 and run.algo == 'cmaes_surrogate'
    assert 'of the population evaluated' in run.notes, run.notes
    plain = sizing.optimize('skill_bootstrap', variables, budget=200,
                            algo='cmaes', workers=1)

    def first_below(r, tol=1e-4):
        return next(n for n, c in r.history if c < tol)
    assert first_below(run) < first_below(plain), (run.notes, plain.notes)
    good = sizing.optimizer.evaluate
    # the surrogate's steps come in whole waves of workers: pycma's own
    # 1, 2, 3, 5 schedule idled three of four workers and doubled the
    # wall clock.  Skill circuits are serial whatever `workers` says, so
    # a bowl on an amp (15 variables, population 12, four workers):
    # steps of 4, 8 or 12, never 1, 2, 3 or 5.
    amp_vars = sizing.parse_variables('studio_cm_ota')
    a, b = amp_vars[0], amp_vars[1]

    def amp_bowl(circuit, values, **kw):
        u = (values[a.name] - a.default) / (a.hi - a.lo)
        v = (values[b.name] - b.default) / (b.hi - b.lo)
        return {'q': 4 * u * u + v * v}
    monkeypatch.setattr(sizing.optimizer, 'evaluate', amp_bowl)
    run4 = sizing.optimize('studio_cm_ota', amp_vars, budget=120,
                           algo='cmaes_surrogate', workers=4)
    steps = re.search(r'steps ([^)]*)\)', run4.notes).group(1)
    sizes = {int(t.split('×')[0]) for t in steps.split()}
    assert sizes and all(n % 4 == 0 for n in sizes), run4.notes
    assert run4.evals <= 120
    monkeypatch.setattr(sizing.optimizer, 'evaluate', good)
    # a failing evaluation ranks last and the search still converges

    def flaky(circuit, values, **kw):
        if values['W.sw'] > 60.0:
            raise RuntimeError('simulated failure')
        return good(circuit, values, **kw)
    monkeypatch.setattr(sizing.optimizer, 'evaluate', flaky)
    run = sizing.optimize('skill_bootstrap', variables, budget=200,
                          algo='cmaes_surrogate', workers=1)
    assert run.best_cost < 1e-3, run.best_cost


def test_archive_records_every_evaluation_and_rescores_on_new_targets(
        monkeypatch, tmp_path):
    """Every evaluated point goes to the circuit's archive; asked for the
    best under other targets, the archive answers without a simulation.
    Rows from another variable set (an imported circuit, an edited set)
    are left out, and a torn last line is skipped."""
    monkeypatch.setattr(sizing.archive, 'archive_dir', lambda: tmp_path)
    variables = _fake_bowl(monkeypatch)
    # the archive scores with the real scorer; the bowl's fake metrics
    # need the same fake here (see the note on re-exports in __init__)
    monkeypatch.setattr(sizing.archive, 'score',
                        lambda c, m, ov=None: m.get('q', 1e9))
    assert sizing.archive_size('skill_bootstrap') == 0
    run = sizing.optimize('skill_bootstrap', variables, budget=30,
                          algo='sobol_powell', workers=1)
    assert sizing.archive_size('skill_bootstrap') == run.evals
    names = [v.name for v in variables]
    best = sizing.archive_best('skill_bootstrap', names)
    assert best is not None and best['n'] == run.evals
    assert best['cost'] == pytest.approx(run.best_cost)
    assert best['values'] == run.best_values
    # other targets, other winner: score is monkeypatched to m['q'], so
    # score with overrides is the same here — assert the plumbing instead
    assert sizing.archive_best('skill_bootstrap', names + ['extra']) is None
    p = tmp_path / 'skill_bootstrap.jsonl'
    p.write_text(p.read_text() + '{"values": {"W.sw": 1')   # torn line
    assert sizing.archive_size('skill_bootstrap') == run.evals
    # failures are archived with empty metrics (they say where the box
    # does not simulate) and never win
    sizing.archive.record('skill_bootstrap', {n: 1.0 for n in names}, {})
    assert sizing.archive_best('skill_bootstrap', names)['cost'] == \
        pytest.approx(run.best_cost)


def test_warm_start_searches_from_the_known_point(monkeypatch, tmp_path):
    """A start point replaces the default sizing.  CMA-ES used to sample
    around its start without ever evaluating it, at σ 0.25 — measured, a
    verified 0.27 became a "best" of 0.73 in 100 evaluations.  Now the
    point is in the first population and the step is 0.1, so the first
    generation is already no worse than the start."""
    pytest.importorskip('cma')
    monkeypatch.setattr(sizing.archive, 'archive_dir', lambda: tmp_path)
    variables = _fake_bowl(monkeypatch)
    near = {'W.sw': 31.0, 'FCLK': 1.05e8}      # cost ≈ 0.0034 on the bowl
    start_cost = sizing.optimizer.score(
        'skill_bootstrap', sizing.optimizer.evaluate('skill_bootstrap', near))
    for algo in ('cmaes', 'cmaes_surrogate'):
        run = sizing.optimize('skill_bootstrap', variables, budget=40,
                              algo=algo, workers=1, start=near)
        first_gen = min(c for _, c in run.history[:6])   # popsize 6
        assert first_gen <= start_cost + 1e-12, (algo, run.history[:6])
        assert 'warm start from a known point (σ 0.1' in run.notes
        assert run.best_cost < 1e-3
    run = sizing.optimize('skill_bootstrap', variables, budget=40,
                          algo='diff_evolution', workers=1, start=near)
    assert run.best_cost <= start_cost and 'warm start' in run.notes
    with pytest.raises(ValueError):
        sizing.optimize('skill_bootstrap', variables, budget=10,
                        algo='cmaes', start={'W.sw': 31.0})


def test_characterise_samples_the_box_into_the_archive(monkeypatch,
                                                       tmp_path):
    """'sobol' is not a search: budget points over the whole box, the
    default sizing first, every one archived; the best sampled point is
    the run's result."""
    monkeypatch.setattr(sizing.archive, 'archive_dir', lambda: tmp_path)
    monkeypatch.setattr(sizing.archive, 'score',
                        lambda c, m, ov=None: m.get('q', 1e9))
    variables = _fake_bowl(monkeypatch)
    run = sizing.optimize('skill_bootstrap', variables, budget=64,
                          algo='sobol', workers=1, seed=3)
    assert run.evals == 64 and sizing.archive_size('skill_bootstrap') == 64
    assert 'Sobol sample of the whole box, 64 points' in run.notes
    rows = sizing.archive.load('skill_bootstrap')
    defaults = {v.name: v.default for v in variables}
    assert rows[0]['values'] == defaults              # the default first
    assert run.best_cost == min(r['metrics']['q'] for r in rows)
    # the sample spans the box, not the default's neighbourhood
    ws = [r['values']['W.sw'] for r in rows]
    lo, hi = next(v for v in variables if v.name == 'W.sw').lo, \
        next(v for v in variables if v.name == 'W.sw').hi
    assert min(ws) < lo + 0.1 * (hi - lo) and max(ws) > hi - 0.1 * (hi - lo)


def test_metric_models_propose_near_the_optimum(monkeypatch, tmp_path):
    """Models trained on a characterised archive propose points under
    the current targets in seconds; verified in one batch, the best of
    them is the warm start.  On the bowl the models see the whole box
    and their proposals land near (30, 100 MHz) without a search on the
    real function."""
    pytest.importorskip('sklearn')
    pytest.importorskip('cma')
    monkeypatch.setattr(sizing.archive, 'archive_dir', lambda: tmp_path)
    fake_score = lambda c, m, ov=None: m.get('q', 1e9)   # noqa: E731
    monkeypatch.setattr(sizing.archive, 'score', fake_score)
    monkeypatch.setattr(sizing.models, 'score', fake_score)
    variables = _fake_bowl(monkeypatch)
    names = [v.name for v in variables]
    with pytest.raises(ValueError, match='characterise'):
        sizing.models.train('skill_bootstrap', names)
    sizing.optimize('skill_bootstrap', variables, budget=256, algo='sobol',
                    workers=1)
    # a few failed rows: the classifier learns where the box breaks
    for i in range(20):
        sizing.archive.record('skill_bootstrap',
                              {'W.sw': 60.0 + i, 'FCLK': 2e8}, {})
    # garbage rows, as a failed simulation leaves them: the fit must
    # still answer right at a known good point (a raw fit predicted 5.7
    # for a line regulation of 0.004 once the garbage set the scale)
    for i in range(12):
        sizing.archive.record('skill_bootstrap',
                              {'W.sw': 5.0 + i, 'FCLK': 1e7}, {'q': 1e6})
    mm = sizing.models.train('skill_bootstrap', names)
    assert mm.keys == ['q'] and mm.n == 268 and mm.clf is not None
    assert sizing.models.train('skill_bootstrap', names) is mm    # cached
    best = sizing.archive_best('skill_bootstrap', names)
    at_best = mm.cost(np.array([[best['values'][n] for n in names]]))[0]
    assert at_best < 0.5, (at_best, best['cost'])
    pts, pred, _ = sizing.models.propose('skill_bootstrap', variables, k=4)
    assert len(pts) == 4 and pred == sorted(pred)
    assert abs(pts[0]['W.sw'] - 30.0) < 4 and abs(pts[0]['FCLK'] - 1e8) < 2e7
    # through optimize: the proposals are verified, archived, and the
    # best verified point is the result
    before = sizing.archive_size('skill_bootstrap')
    run = sizing.optimize('skill_bootstrap', variables, budget=4,
                          algo='model_propose', workers=1)
    assert run.evals == 4 and sizing.archive_size('skill_bootstrap') == \
        before + 4
    assert run.best_cost < 0.05, run.best_cost
    assert '4 proposals from metric models trained on 268' in run.notes
    assert 'predicted -> verified' in run.notes


def test_de_powell_polishes_where_de_stopped(monkeypatch):
    variables = _fake_bowl(monkeypatch)
    run = sizing.optimize('skill_bootstrap', variables, budget=80,
                          algo='de_powell', workers=1)
    assert run.evals <= 80 and 'powell polish' in run.notes
    plain = sizing.optimize('skill_bootstrap', variables, budget=80,
                            algo='diff_evolution', workers=1)
    assert run.best_cost <= plain.best_cost      # the polish never hurts
    assert run.continuable                        # DE population kept


def test_cmaes_llm_finish_begins_when_the_search_stalls(monkeypatch):
    """The finish used to take its reserve from the end of the search
    regardless; on ldo_basic at seed 0 CMA-ES improved 1.08 to 0.84 in
    exactly those evaluations.  Now the search keeps its budget while it
    improves — here a bowl that keeps improving by hairs runs until one
    finish round is left — and what the finish leaves goes back to
    CMA-ES from the finished point."""
    pytest.importorskip('cma')
    from app.core import llm_sizing
    variables = _fake_bowl(monkeypatch)
    seen = []

    def fake_finish(circuit, variables, overrides, *, state, run_batch,
                    budget, workers, chat=None):
        seen.append((state['dispatched'], state['cap'], budget))
        return 'fake finish'

    monkeypatch.setattr(llm_sizing, 'run_finish', fake_finish)
    run = sizing.optimize('skill_bootstrap', variables, budget=300,
                          algo='cmaes_llm_finish', workers=1)
    assert len(seen) == 1
    at, cap, budget = seen[0]
    assert 300 - llm_sizing.FINISH_EVALS - 8 <= at <= 300 - llm_sizing.FINISH_EVALS
    assert cap == budget == 300
    assert 'llm finish: fake finish' in run.notes
    assert 'resumed CMA-ES from the finished point' in run.notes
    assert run.evals > at                        # the leftover was spent

    # a search that goes flat hands over early, and the finish's leftover
    # goes back to the search
    seen.clear()
    fake = sizing.optimizer.evaluate
    monkeypatch.setattr(sizing.optimizer, 'evaluate',
                        lambda c, v, **kw: {'q': max(fake(c, v)['q'], 0.05)})
    run = sizing.optimize('skill_bootstrap', variables, budget=300,
                          algo='cmaes_llm_finish', workers=1)
    at, cap, budget = seen[0]
    assert at < 200, at                          # stalled long before the cap
    assert 'stopped on stall' in run.notes
    assert run.evals >= 300 - 8                  # and the budget was spent


def test_signed_margin_and_slack():
    from app.core.sizing.spec import MetricSpec
    band = MetricSpec('pm', 'PM', 'deg', 60.0, 'max', 1.0, ceiling=90.0)
    assert sizing.signed_margin(band, 75.0, 60.0) == pytest.approx(
        min(15 / 60, 15 / 90))
    assert sizing.signed_margin(band, 50.0, 60.0) < 0
    assert sizing.signed_margin(band, 100.0, 60.0) < 0
    lo = MetricSpec('p', 'P', 'W', 1e-3, 'min', 1.0)
    assert sizing.signed_margin(lo, 0.5e-3, 1e-3) == pytest.approx(0.5)
    ab = MetricSpec('v', 'V', 'V', 1e-4, 'absmin', 1.0)
    assert sizing.signed_margin(ab, -0.5e-4, 1e-4) == pytest.approx(0.5)
    # a huge margin on one metric is capped: it cannot buy slack elsewhere
    perfect = dict(_PERFECT, dcgain=1000.0)
    assert sizing.slack('amp_hoilee_affc', perfect) <= 9 * 0.5
    assert sizing.slack('amp_hoilee_affc', None) < 0


@needs_ngspice
def test_de_constrained_micro_run():
    """Every metric a constraint, one parallel batch per generation, the
    objective read from what the constraint call cached: the budget is
    spent once, not twice."""
    variables = sizing.parse_variables('studio_cm_ota')
    run = sizing.optimize('studio_cm_ota', variables, budget=8,
                          algo='de_constrained', workers=4)
    assert run.evals == 8 and run.notes.startswith('constrained:')
    assert run.best_cost < float('inf')

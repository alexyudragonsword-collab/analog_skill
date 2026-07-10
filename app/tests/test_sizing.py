"""Tests for the AnalogGym sizing adapter (Sizing tab core)."""

import os
import shutil

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

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
                                  'skill_comparator_fast', 'skill_bootstrap'}
    # 15 amps + basic LDO + 4 variants + 6 circuit-skills (PTM)
    assert len(sizing.SIZING) == 26
    for key, spec in sizing.SIZING.items():
        assert spec.metrics, key
        assert sizing.parse_variables(key), key
        if spec.kind == 'skill':
            from app.core import circuits
            assert spec.skill_key in circuits.CIRCUITS, key
            assert sizing.schematic_path(key) is not None, key
            continue
        root = paths.analoggym_dir() / spec.kind
        assert (root / 'netlist' / spec.netlist).is_file(), key
        assert (root / 'variables' / spec.variables).is_file(), key
        assert (root / 'testbench' / spec.testbench).is_file(), key
        if spec.kind == 'amp':               # shared TB → subckt substituted
            assert spec.subckt == spec.netlist, key
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


def test_score_directions():
    spec_key = 'amp_hoilee_affc'
    perfect = {'dcgain': 120, 'gain_bandwidth_product': 2e6,
               'phase_in_deg': 60, 'dcpsrp': -80, 'dcpsrn': -80,
               'cmrrdc': -80, 'power': 0.1e-3, 'vos25': 1e-6, 'tc': 1e-6}
    assert sizing.score(spec_key, perfect) == 0.0
    worse = dict(perfect, dcgain=50)
    assert sizing.score(spec_key, worse) > 0
    assert sizing.score(spec_key, {}) > 10               # missing → penalty


def test_score_overrides_and_hard():
    key = 'amp_hoilee_affc'
    m = {'dcgain': 90, 'gain_bandwidth_product': 2e6, 'phase_in_deg': 60,
         'dcpsrp': -80, 'dcpsrn': -80, 'cmrrdc': -80, 'power': 0.1e-3,
         'vos25': 1e-6, 'tc': 1e-6}
    base = sizing.score(key, m)                          # dcgain 90 < 100
    assert base > 0
    # relaxing the target to 80 clears the violation
    assert sizing.score(key, m, {'dcgain': (80.0, False)}) == 0.0
    # hard flag multiplies the same violation by 10
    hard = sizing.score(key, m, {'dcgain': (100.0, True)})
    assert abs(hard - base * 10) < 1e-9


# ── real evaluations (ngspice) ───────────────────────────────────────────────
@needs_ngspice
def test_amp_evaluate_default():
    values = {v.name: v.default for v in
              sizing.parse_variables('amp_hoilee_affc')}
    m = sizing.evaluate('amp_hoilee_affc', values)
    # default HoiLee_AFFC sizing measured on ngspice-42 (see analysis doc)
    assert 80 < m['dcgain'] < 100
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


@needs_ngspice
def test_ldo_variant_evaluate():
    """ldo_1 exercises the ../simulations/ include mapping and the
    _ACDC wrdata prefix."""
    values = {v.name: v.default for v in sizing.parse_variables('ldo_1')}
    m = sizing.evaluate('ldo_1', values)
    for k in ('pm_maxload', 'gbw_maxload', 'lnr', 'lr', 'iq'):
        assert k in m, k


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

    monkeypatch.setattr(sizing, 'evaluate', fake)
    variables = sizing.parse_variables('skill_comparator_fast')
    run = sizing.optimize('skill_comparator_fast', variables, budget=3)
    monkeypatch.setattr(sizing, 'evaluate', orig)
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
    monkeypatch.setattr(sizing, 'runs_dir', lambda: tmp_path)
    sizing.save_run(_fake_run())
    sizing.save_run(_fake_run('skill_ota5t', cost=0.5))

    from app.core.worker import SimWorker
    from app.ui.sizing_tab import RunsDialog, SizingTab
    worker = SimWorker()
    try:
        tab = SizingTab(worker)
        dlg = RunsDialog(tab)
        assert dlg._list.rowCount() == 2
        n = tab.apply_best_to_table(_fake_run())
        assert n == 1                          # CURRENT_0_BIAS exists
        assert tab.circuit_combo.currentData() == 'amp_hoilee_affc'
        vals = {tab._table.item(r, 0).text(): tab._table.item(r, 1).text()
                for r in range(tab._table.rowCount())}
        assert vals['CURRENT_0_BIAS'] == '2.5e-06'
    finally:
        worker.stop()


@needs_ngspice
def test_diff_evolution_micro():
    variables = sizing.parse_variables('amp_hoilee_affc')
    run = sizing.optimize('amp_hoilee_affc', variables, budget=8,
                          algo='diff_evolution', workers=2)
    assert run.evals <= 8
    assert run.best_cost <= run.initial_cost

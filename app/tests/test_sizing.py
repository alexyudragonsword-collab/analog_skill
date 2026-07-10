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
    assert set(sizing.SIZING) >= {'amp_hoilee_affc', 'ldo_basic'}
    for key, spec in sizing.SIZING.items():
        root = paths.analoggym_dir() / spec.kind
        assert (root / 'netlist' / spec.netlist).is_file(), key
        assert (root / 'variables' / spec.variables).is_file(), key
        assert (root / 'testbench' / spec.testbench).is_file(), key
        assert spec.metrics, key
    assert (paths.analoggym_dir() / 'pdk' / 'sky130_pdk.zip').is_file()
    assert (paths.analoggym_dir() / 'LICENSE').is_file()   # BSD-3


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
def test_optimize_cancel():
    variables = sizing.parse_variables('amp_hoilee_affc')
    run = sizing.optimize('amp_hoilee_affc', variables, budget=50,
                          should_cancel=lambda: True)
    # cancelled before the second evaluation; the initial one is kept
    assert run.cancelled and run.evals <= 1

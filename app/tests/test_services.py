"""Unit tests for browser_service, ngspice_locator and paths' frozen branch.

None of these need ngspice — they cover the pure logic that previously had
zero coverage.
"""

import os
import shutil
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest


@pytest.fixture(scope='module', autouse=True)
def runtime():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app import paths
    paths.init_runtime()
    from app.core.model_registry import register_extra_models
    register_extra_models()


# ── browser_service ──────────────────────────────────────────────────────────
def test_node_key_families():
    from app.core.browser_service import node_key
    assert node_key('nmos45hp') == '45hp'
    assert node_key('pmos22hp') == '22hp'
    assert node_key('nmos180') == '180'
    # non-tuned nodes must NOT fall back to the 180nm table (its sweep
    # voltages exceed their VDD) — they take the VDD-derived branch
    assert node_key('nmos130') is None
    assert node_key('pmos32lp') is None


def test_node_params_hand_tuned_vs_derived():
    from app.core.browser_service import node_params_for, NODE_PARAMS
    # hand-tuned nodes return the exact table
    assert node_params_for('nmos45hp') is NODE_PARAMS['45hp']
    # derived nodes scale with VDD and carry all required keys
    import simulate_gmoverid as sg
    for model in ('nmos130', 'pmos32lp'):
        cfg = node_params_for(model)
        vdd = sg.MODEL_INFO[model]['vdd']
        for key in ('vds_list', 'vds_gds', 'vgs_bias', 'vgs_iv'):
            assert cfg[key], f'{model}: {key} empty'
            assert max(cfg[key]) <= vdd + 1e-9, f'{model}: {key} exceeds VDD'
        assert len(cfg['vgs_bias']) == 9


def test_polarity_dispatch():
    from app.core.browser_service import _polarity
    assert _polarity('nmos180') == 'nmos'
    assert _polarity('pmos45hp') == 'pmos'


# ── ngspice_locator ──────────────────────────────────────────────────────────
def test_prepend_path_element_wise(monkeypatch):
    from app.core.ngspice_locator import _prepend_path
    monkeypatch.setenv('PATH', '/usr/local/binx' + os.pathsep + '/usr/bin')
    # '/usr/local/bin' is a substring of '/usr/local/binx' but NOT an element
    _prepend_path('/usr/local/bin')
    entries = os.environ['PATH'].split(os.pathsep)
    assert entries[0] == '/usr/local/bin'
    # idempotent: prepending again must not duplicate
    _prepend_path('/usr/local/bin')
    assert os.environ['PATH'].split(os.pathsep).count('/usr/local/bin') == 1


def test_probe_rejects_garbage():
    from app.core.ngspice_locator import _probe
    assert _probe('/nonexistent/ngspice') is None


@pytest.mark.skipif(shutil.which('ngspice') is None,
                    reason='ngspice not installed')
def test_locate_finds_system_ngspice():
    from app.core.ngspice_locator import locate
    st = locate()
    assert st.ok and 'ngspice' in (st.version or '').lower()


# ── paths: frozen-mode sync ──────────────────────────────────────────────────
def test_sync_tree_atomic(tmp_path):
    from app.paths import _sync_tree
    src = tmp_path / 'src'
    (src / 'sub').mkdir(parents=True)
    (src / 'a.py').write_text('x = 1')
    (src / 'sub' / 'b.lib').write_text('* model')
    (src / 'logs').mkdir()
    (src / 'logs' / 'junk.log').write_text('junk')

    dst = tmp_path / 'dst'
    _sync_tree(src, dst)
    assert (dst / 'a.py').read_text() == 'x = 1'
    assert (dst / 'sub' / 'b.lib').exists()
    assert not (dst / 'logs').exists()          # ignored pattern
    assert not dst.with_name(dst.name + '.tmp').exists()

    # a stale .tmp from a crashed previous run must not break the sync
    dst2 = tmp_path / 'dst2'
    tmp_leftover = dst2.with_name(dst2.name + '.tmp')
    tmp_leftover.mkdir()
    (tmp_leftover / 'partial.py').write_text('broken')
    _sync_tree(src, dst2)
    assert (dst2 / 'a.py').exists()
    assert not tmp_leftover.exists()

    # already-synced dst is left untouched
    (dst / 'marker').write_text('keep')
    _sync_tree(src, dst)
    assert (dst / 'marker').exists()


def test_prune_old_workspaces(tmp_path):
    from app.paths import _prune_old_workspaces
    ws_root = tmp_path / 'workspace'
    current = ws_root / '0.7'
    old = ws_root / '0.6'
    for d in (current, old):
        d.mkdir(parents=True)
        (d / 'f').write_text('x')
    _prune_old_workspaces(current)
    assert current.exists() and not old.exists()


# ── gmid_service.extract_curves contract ─────────────────────────────────────
@pytest.mark.skipif(shutil.which('ngspice') is None,
                    reason='ngspice not installed')
def test_extract_curves_contract():
    import numpy as np
    from app.core import gmid_service
    tbl = gmid_service.build_table('nmos180', 10.0, 0.18, None)
    curves = gmid_service.extract_curves(tbl)
    for key in ('gmid', 'ft', 'id_w', 'gmro', 'vgs', 'vov'):
        assert key in curves and len(curves[key]) > 100
    assert np.all(np.diff(curves['gmid']) >= 0), 'gmid must be ascending'

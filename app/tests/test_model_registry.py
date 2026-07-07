"""Tests for extra bulk-node registration (needs ngspice for the build)."""

import os
import shutil

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest


@pytest.fixture(scope='module', autouse=True)
def runtime():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app import paths
    paths.init_runtime()


def test_register_extra_models_injects_bulk_nodes():
    from app.core.model_registry import register_extra_models
    import simulate_gmoverid as sg
    added = register_extra_models()
    assert 'nmos130' in added and 'pmos65' in added
    # idempotent
    assert register_extra_models() == []
    for key in ('nmos130', 'pmos130', 'nmos90', 'nmos65',
                'nmos45lp', 'nmos32hp', 'nmos32lp', 'nmos22lp'):
        assert key in sg.MODEL_INFO
        assert sg.MODEL_INFO[key]['file'].exists()


def test_nominal_L():
    from app.core.model_registry import nominal_L
    assert nominal_L('nmos130') == 0.13
    assert nominal_L('pmos65') == 0.065
    assert nominal_L('nmos180') == 0.18


@pytest.mark.skipif(shutil.which('ngspice') is None,
                    reason='ngspice not installed')
def test_build_table_for_new_node():
    from app.core.model_registry import register_extra_models
    from app.core import gmid_service
    register_extra_models()
    tbl = gmid_service.build_table('nmos130', 10.0, 0.13, None)
    op = tbl.size(gmid=12.0, Id=50e-6)
    assert op['W_um'] > 0 and op['ft_Hz'] > 0

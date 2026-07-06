"""Integration tests for the examples registry (needs ngspice)."""

import os
import shutil
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which('ngspice') is None, reason='ngspice not installed')


@pytest.fixture(scope='module', autouse=True)
def runtime():
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    from app import paths
    paths.init_runtime()


def test_run_dc_nmos_iv_with_patched_params():
    import importlib
    from app.core.examples import run_example

    sim = importlib.import_module('simulate_dc_nmos_iv')
    original_list = sim.VGS_LIST

    start = time.time()
    pngs = run_example('dc_nmos_iv', {
        'W_UM': 10.0, 'L_UM': 0.18, 'VGS_LIST': [0.8],
    })

    # module global restored after the run
    assert sim.VGS_LIST is original_list

    assert len(pngs) == 1
    assert pngs[0].exists()
    assert pngs[0].stat().st_mtime >= start


def test_si_to_spice():
    from app.core.examples import si_to_spice
    assert si_to_spice(1e3) == '1k'
    assert si_to_spice(1e-12) == '1p'
    assert si_to_spice(100e-6) == '100u'
    assert si_to_spice(2.2e3) == '2.2k'
    assert si_to_spice(0) == '0'

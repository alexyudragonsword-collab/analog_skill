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


def test_spice_to_si():
    from app.core.examples import _spice_to_si
    assert _spice_to_si('1Meg') == 1e6
    assert _spice_to_si('10G') == 1e10
    assert _spice_to_si('1p') == 1e-12
    assert _spice_to_si('2.2k') == 2200.0


def test_advanced_param_patch_and_restore():
    """Advanced params (VDD, freq) patch module globals and restore after."""
    import importlib
    from app.core.examples import run_example

    mod = importlib.import_module('simulate_ac_cs_amp')
    vdd0, fs0, fstop0 = mod.VDD, mod.FREQ_START, mod.FREQ_STOP
    pngs = run_example('ac_cs_amp', {
        'W_UM': 10.0, 'L_UM': 0.18, 'VGS_BIAS': 0.6, 'RD_K': 2.0,
        'CL_PF': 1.0, 'VDD': 2.0, 'FREQ_START': 1e4, 'FREQ_STOP': 50e9,
    })
    assert mod.VDD == vdd0 and mod.FREQ_START == fs0 and mod.FREQ_STOP == fstop0
    assert pngs[0].exists()


def test_all_specs_defaults_resolve():
    import importlib
    from app.core.examples import REGISTRY
    for spec in REGISTRY.values():
        mod = importlib.import_module(spec.sim_module)
        for p in spec.params:
            p.resolve_default(mod)   # must not raise

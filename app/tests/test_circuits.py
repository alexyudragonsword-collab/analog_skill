"""Tests for the circuit-skills adapters (Circuits tab core)."""

import os
import shutil
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from app import paths
paths.init_runtime()

needs_ngspice = pytest.mark.skipif(
    shutil.which('ngspice') is None, reason='ngspice not installed')


# ── registry sanity (no ngspice needed) ──────────────────────────────────────
def test_registry_shape():
    from app.core import circuits
    assert set(circuits.CIRCUITS) == {
        'comparator', 'ldo', 'ota5t', 'opamp2', 'bootstrap'}
    for key, spec in circuits.CIRCUITS.items():
        assert spec.analyses, key
        assert 'full' in spec.analyses, key
        d = paths.circuit_skills_dir() / spec.subdir
        assert d.is_dir(), d
        assert (d / f'{spec.common_mod}.py').exists(), spec.common_mod
        assert key in circuits._RUNNERS
        # every circuit ships a pre-rendered schematic (tools/gen_schematics)
        sch = circuits.schematic_path(key)
        assert sch is not None and sch.suffix == '.png', key


def test_param_attrs_exist_in_common():
    """Every registered Param must map to a real global (or dict entry)."""
    import ast
    from app.core import circuits
    for key, spec in circuits.CIRCUITS.items():
        src = (paths.circuit_skills_dir() / spec.subdir /
               f'{spec.common_mod}.py').read_text(errors='replace')
        tree = ast.parse(src)
        names = {t.id for node in tree.body if isinstance(node, ast.Assign)
                 for t in node.targets if isinstance(t, ast.Name)}
        for p in spec.params:
            base = p.attr.split('.', 1)[0]
            assert base in names, f'{key}: {p.attr} not in {spec.common_mod}'


def test_skill_context_isolation_and_restore():
    """Circuit imports must not leak into the app's module space."""
    from app.core import circuits
    import ngspice_common as before  # gmoverid/examples version
    assert 'circuit-skills' not in before.__file__

    scripts = paths.circuit_skills_dir() / 'comparator' / 'scripts'
    with circuits.skill_context(scripts):
        for mod in list(sys.modules):
            if mod == 'ngspice_common':
                del sys.modules[mod]
        import ngspice_common as inside
        assert 'comparator' in inside.__file__
    # restored afterwards: fresh import resolves to the examples version again
    sys.modules.pop('ngspice_common', None)
    import ngspice_common as after
    assert 'circuit-skills' not in after.__file__
    assert not [p for p in sys.path if 'circuit-skills' in str(p)]


# ── end-to-end (needs ngspice) ───────────────────────────────────────────────
@needs_ngspice
def test_ota_full_end_to_end():
    from app.core import circuits
    res = circuits.run_circuit('ota5t', 'full', {'W_IN_UM': 20.0})
    pngs, report = res.render()
    assert len(pngs) == 3                       # dc + ac + noise
    assert all(p.exists() and p.stat().st_size > 0 for p in pngs)
    assert 'UGB' in report and 'DC gain' in report


@needs_ngspice
def test_bootstrap_wave_model_patch():
    """bootstrap's hardcoded skill path must be redirected to the app copy."""
    from app.core import circuits
    res = circuits.run_circuit('bootstrap', 'wave', {})
    pngs, report = res.render()
    assert pngs and pngs[0].name == 'bts_waveform.png'
    assert 'Bootstrap voltage' in report


@needs_ngspice
def test_ldo_auto_design():
    from app.core import circuits
    res = circuits.run_circuit(
        'ldo', 'auto', {'vout': 1.8, 'vin': 2.3, 'iload_ma': 50.0})
    pngs, report = res.render()
    assert 'Auto-Design Report' in report
    assert pngs


def test_repoint_models_uses_workspace():
    """Every skill's model dir must resolve to the space-free workspace copy
    (NGSPICE_ASSETS), not its read-only install dir — an install path with a
    space breaks ngspice's unquoted .include (frozen Windows bug)."""
    import importlib
    from app.core import circuits
    for _skill, sub, common_mod, lib in (
            ('ota5t', 'five_transistor_ota/scripts', 'ota_common',
             'ptm180.lib'),
            ('comparator', 'comparator/scripts', 'comparator_common',
             'ptm45hp.lib')):
        scripts = paths.circuit_skills_dir() / sub
        with circuits.skill_context(scripts):
            common = importlib.import_module(common_mod)
            circuits._repoint_models(common, lib)
            # MODEL_PATH goes into a SPICE .include, so ngspice_common.spath
            # writes it with forward slashes on every platform — compare in
            # the same normalization, not against a native str(WindowsPath).
            assert paths.NGSPICE_ASSETS.as_posix() in str(common.MODEL_PATH)
            assert common.MODEL_PATH.endswith(lib)
            assert (paths.NGSPICE_ASSETS / 'models' / lib).is_file()

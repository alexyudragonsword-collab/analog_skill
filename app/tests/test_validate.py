"""Test the validate self-check wrapper (needs ngspice)."""

import os
import shutil

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which('ngspice') is None, reason='ngspice not installed')


@pytest.fixture(scope='module', autouse=True)
def runtime():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app import paths
    paths.init_runtime()


def test_run_validation_nmos180_all_pass():
    from app.core import gmid_service, validate_service
    tbl = gmid_service.build_table('nmos180', 10.0, 0.18, None)
    res = validate_service.run_validation('nmos180', 0.18, tbl.vds, tbl)
    assert len(res) == 5
    assert all(isinstance(r['ok'], bool) for r in res)
    # nmos180 is the reference node — every physics check should pass
    assert all(r['ok'] for r in res), [r['name'] for r in res if not r['ok']]

"""FinFET (BSIM-CMG via OSDI) tests.

The sweep/table tests need ngspice *with OSDI* plus the shipped bsimcmg.osdi;
they skip cleanly when either is absent.  The registry/modelcard tests are
pure and always run.
"""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest

# make the vendored skill importable and register the FinFET nodes before the
# skip markers below are evaluated at collection time.  We deliberately do NOT
# register the bulk nodes here — test_model_registry asserts it is the first to
# do so (register_extra_models returns the freshly-added keys).
from app import paths
paths.init_runtime()
from app.core.model_registry import register_finfet_models, finfet_available
register_finfet_models()

_needs_osdi = pytest.mark.skipif(
    not finfet_available(),
    reason='ngspice without OSDI or bsimcmg.osdi not shipped')


# ── pure: registration + modelcard transform ────────────────────────────────
def test_finfet_models_registered():
    from simulate_gmoverid import MODEL_INFO
    for key in ('nfin20lstp', 'pfin20lstp', 'nfin7hp', 'pfin7hp'):
        assert key in MODEL_INFO, key
        assert MODEL_INFO[key]['kind'] == 'finfet'
    # 5 nodes x 2 variants x 2 polarities = 20
    n = sum(1 for v in MODEL_INFO.values() if v.get('kind') == 'finfet')
    assert n == 20


def test_is_finfet_and_lg():
    from app.core import model_registry as mr
    assert mr.is_finfet('nfin20lstp')
    assert not mr.is_finfet('nmos180')
    assert abs(mr.nominal_L('nfin7hp') - 0.011) < 1e-9    # 7nm Lg = 11 nm
    assert abs(mr.nominal_L('nfin20lstp') - 0.024) < 1e-9


def test_osdi_modelcard_transform(tmp_path):
    from app.core import finfet_sim
    from simulate_gmoverid import MODEL_INFO
    info = MODEL_INFO['pfin20lstp']
    card = finfet_sim.osdi_modelcard(str(info['file']), 'pmos')
    text = card.read_text()
    assert 'bsimcmg_va' in text          # OSDI module type, not "pmos level=72"
    assert 'level = 72' not in text.replace('level =72', 'level = 72').lower() \
        or 'nmos level' not in text.lower()
    assert 'type = -1' in text.lower()   # PMOS in BSIM-CMG 112


def test_fin_geometry():
    from app.core import finfet_sim
    from simulate_gmoverid import MODEL_INFO
    wpf = finfet_sim.parse_fin_geom(str(MODEL_INFO['nfin20lstp']['file']))
    # 20nm: HFIN=28n, TFIN=15n -> Weff/fin = 2*28+15 = 71 nm
    assert abs(wpf - 71e-9) < 2e-9


# ── needs ngspice+OSDI: sweep + table ────────────────────────────────────────
@_needs_osdi
def test_sweep_schema_and_physics():
    from app.core import finfet_sim
    d = finfet_sim.sweep_vgs_finfet(vds=0.45, nfin=10, model='nfin20lstp',
                                    l_um=0.024)
    for k in ('vgs', 'id', 'gm', 'cgs', 'cgd', 'cgb', 'cgg', 'gmid', 'ft',
              'id_w', 'vov', 'vth'):
        assert k in d, k
    id_ = d['id']
    # Id monotonic non-decreasing (sorted device turn-on)
    assert np.all(np.diff(id_) >= -1e-9)
    # real caps are positive
    assert np.all(d['cgg'] > 0)
    # peak gm/Id in the FinFET band
    peak = np.nanmax(d['gmid'][id_ > 1e-12])
    assert 25.0 <= peak <= 40.0


@_needs_osdi
def test_finfet_table_size():
    from app.core.finfet_table import FinFetTable
    t = FinFetTable('nfin20lstp', NFIN=10)
    rng = t.operating_range()
    assert 25.0 <= rng['gmid_max'] <= 40.0
    op = t.size(gmid=12.0, Id=50e-6)
    assert op['kind'] == 'finfet'
    assert op['NFIN'] >= 1
    assert op['Id_A'] == pytest.approx(50e-6, rel=1e-6)
    # NFIN round-trip: sizing at that NFIN reproduces a consistent Weff
    op2 = t.size(gmid=12.0, W=op['NFIN'])
    assert op2['NFIN'] == op['NFIN']


@_needs_osdi
def test_pmos_finfet_positive_convention():
    from app.core import finfet_sim
    d = finfet_sim.sweep_vgs_finfet(vds=0.45, nfin=10, model='pfin20lstp',
                                    l_um=0.024)
    assert d['pol'] == 'pmos'
    assert np.all(d['id'] >= 0)                    # positive-convention Id
    assert d['vgs'][0] < d['vgs'][-1]              # |Vsg| ascending

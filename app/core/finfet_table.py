"""FinFET gm/ID sizing table.

Subclasses the skill's GmIdTable, replacing only the data-acquisition hooks
with BSIM-CMG (OSDI) sweeps that return the same schema.  All the table
machinery — right-branch extraction, gm·ro, lookup, size_from_ft/gmro — is
inherited unchanged.

The size variable is NFIN (number of fins), not W: id_w is the per-effective-
width current density, so a lookup yields Weff, and NFIN = ceil(Weff /
(2·HFIN + TFIN)).
"""

import math

from simulate_gmoverid import MODEL_INFO
from design_gmoverid import (
    GmIdTable, CACHE_DIR, _float_tag, _load_sweep, _save_sweep,
)

from app.core import finfet_sim


class FinFetTable(GmIdTable):
    """gm/ID lookup table for a BSIM-CMG FinFET node (size variable = NFIN)."""

    def __init__(self, model, NFIN=10, vds=None, force_resim=False, L=None):
        info = MODEL_INFO.get(model)
        if info is None or info.get('kind') != 'finfet':
            raise KeyError(f'{model!r} is not a registered FinFET model')

        self.model = model
        self.NFIN  = max(1, int(NFIN))
        self.W     = self.NFIN                 # parent uses self.W as the size knob
        self.L     = float(L if L is not None else info['lg'])
        self._info = info
        self._vdd  = float(info.get('vdd', 0.8))
        self._pol  = info.get('pol', 'nmos')
        self._vth0 = 0.4
        self._weff_per_fin = finfet_sim.parse_fin_geom(str(info['file']))  # [m]

        self.vds = round(self._vdd / 2.0, 3) if vds is None else float(vds)
        self._vgs_bias_list = []               # gds comes from finite-diff

        print(f'[FinFetTable] {model}  NFIN={self.NFIN}  L={self.L*1e3:.0f}nm  '
              f'Vds={self.vds}V')
        self._vgs_data = self._get_vgs_data(force_resim)
        self._vds_data = []
        self._build_tables()

    # ── data hooks (override GmIdTable) ─────────────────────────────────────
    def _cache_path(self, vds):
        ntag = self.NFIN
        ltag = _float_tag(self.L, 4)
        vtag = _float_tag(vds, 3)
        return CACHE_DIR / f'finfet_vgs_{self.model}_N{ntag}_L{ltag}_Vds{vtag}.json'

    def _get_vgs_data(self, force):
        path = self._cache_path(self.vds)
        if not force and path.exists():
            data = _load_sweep(path)
            if data is not None:
                print(f'  Vgs sweep  [cache]  ({path.name})')
                return data
        print('  Vgs sweep  [OSDI sim] ...')
        data = finfet_sim.sweep_vgs_finfet(self.vds, self.NFIN, self.model, self.L)
        _save_sweep(data, path)
        return data

    def _get_vgs_data_at(self, vds):
        path = self._cache_path(vds)
        if path.exists():
            data = _load_sweep(path)
            if data is not None:
                return data
        data = finfet_sim.sweep_vgs_finfet(vds, self.NFIN, self.model, self.L)
        _save_sweep(data, path)
        return data

    def _get_vds_data(self, force):
        return []

    # ── sizing (NFIN semantics) ─────────────────────────────────────────────
    def size(self, gmid, Id=None, W=None, gm=None):
        """Size the device.  ``W`` here is NFIN (integer); result adds NFIN/Weff.

        Kept W-named so the inherited size_from_ft / size_from_gmro (which call
        self.size(..., W=W)) keep working with NFIN semantics.
        """
        wpf_um = self._weff_per_fin * 1e6
        if W is not None:                       # caller gave NFIN
            op = super().size(gmid, W=max(1, int(round(W))) * wpf_um)
        else:
            op = super().size(gmid, Id=Id, gm=gm)

        weff_um = op['W_um']                     # parent's "W" is really Weff
        op['Weff_um'] = weff_um
        op['weff_per_fin_um'] = wpf_um
        op['NFIN'] = max(1, math.ceil(weff_um / wpf_um - 1e-9))
        op['kind'] = 'finfet'
        return op

"""Thin adapter between the GUI and the skill's GmIdTable.

All access to GmIdTable's private curve arrays is concentrated here
(extract_curves); if the vendored skill ever grows a public accessor,
this is the only place to update.
"""

from pathlib import Path

import numpy as np


def model_infos() -> dict:
    """The skill's MODEL_INFO table, with the extra PTM nodes injected.

    Imported lazily: the skill modules are only importable after
    paths.init_runtime() has put them on sys.path.
    """
    from simulate_gmoverid import MODEL_INFO
    return MODEL_INFO


def model_choices() -> list[tuple[str, str]]:
    """(display label, model key) pairs for model dropdowns."""
    return [(f"{name}  (VDD {info.get('vdd', 1.8)} V)", name)
            for name, info in model_infos().items()]


def default_L(model: str) -> float:
    """Nominal/minimum L per node family [um]."""
    from app.core.model_registry import nominal_L
    return nominal_L(model)


def is_finfet(model: str) -> bool:
    """Does this model need the BSIM-CMG/OSDI path (and NFIN, not W)?"""
    from app.core.model_registry import is_finfet as _isff
    return _isff(model)


def finfet_available() -> bool:
    """Can this ngspice load the bundled .osdi?  False greys out FinFET."""
    from app.core.model_registry import finfet_available as _avail
    return _avail()


def build_table(model: str, W: float, L: float, vds: float | None,
                force_resim: bool = False):
    """Runs in the worker thread — first build triggers ngspice sweeps.

    For FinFET models the size knob W carries NFIN (integer) and L is the
    node's fixed gate length; dispatch to FinFetTable (BSIM-CMG/OSDI).
    """
    if is_finfet(model):
        from app.core.finfet_table import FinFetTable
        return FinFetTable(model, NFIN=int(round(W)), vds=vds,
                           force_resim=force_resim, L=L)
    from design_gmoverid import GmIdTable
    return GmIdTable(model, W=W, L=L, vds=vds, force_resim=force_resim)


def gmid_log_dir() -> Path:
    """Where the skill writes its ngspice logs — attached to job failures."""
    from simulate_gmoverid import LOG_DIR
    return Path(LOG_DIR)


def extract_curves(tbl) -> dict[str, np.ndarray]:
    """Design-chart arrays vs gm/ID, ascending in gm/ID.

    Reaches into GmIdTable's private arrays (_gmid_arr is stored
    descending; flipped here to ascending for plotting).
    """
    order = slice(None, None, -1)
    return {
        'gmid': tbl._gmid_arr[order],
        'ft':   tbl._ft_arr[order],
        'id_w': tbl._idw_arr[order],
        'gmro': tbl._gmro_arr[order],
        'vgs':  tbl._vgs_arr[order],
        'vov':  tbl._vov_arr[order],
    }

"""Characterization-plot orchestration for the browser tab.

Replicates the sweep orchestration of run_gmoverid.py / run_multinode.py
(those scripts cannot be imported — they simulate at import time / are
entry points).  Per-node sweep configs mirror NODE_CFG in run_multinode.py
and the 180nm constants in run_gmoverid.py.
"""

from pathlib import Path

# Sweep configuration per node family (mirrors run_gmoverid / run_multinode)
NODE_PARAMS = {
    '180': dict(
        vds_list=[0.2, 0.5, 0.9],
        vds_gds=[0.5, 0.7, 0.9, 1.1, 1.3, 1.5],
        vgs_bias=[0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.10],
        vgs_iv=[0.6, 0.7, 0.8, 0.9, 1.0],
    ),
    '45hp': dict(
        vds_list=[0.2, 0.3, 0.4],
        vds_gds=[0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
        vgs_bias=[0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95],
        vgs_iv=[0.4, 0.5, 0.6, 0.7, 0.8],
    ),
    '22hp': dict(
        vds_list=[0.2, 0.3, 0.4],
        vds_gds=[0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
        vgs_bias=[0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80],
        vgs_iv=[0.3, 0.4, 0.5, 0.6, 0.7],
    ),
}

PLOT_TYPES = {
    'main': 'gm/ID four-quadrant',
    'iv': 'IV characteristics',
    'caps': 'Gate capacitances',
}


def node_key(model: str) -> str:
    for key in ('45hp', '22hp'):
        if key in model:
            return key
    return '180'


def _polarity(model: str) -> str:
    from simulate_gmoverid import MODEL_INFO
    return MODEL_INFO[model].get('pol', 'nmos')


def generate_plot(plot_type: str, model: str, W: float, L: float,
                  out_dir: Path) -> Path:
    """Run the sweeps for one plot type and save the PNG.  Worker thread."""
    from simulate_gmoverid import (
        run_vgs_sweeps, run_vds_sweeps, run_vsg_sweeps, run_vsd_sweeps)
    from plot_gmoverid import plot_main, plot_iv, plot_caps

    cfg = NODE_PARAMS[node_key(model)]
    pol = _polarity(model)
    out_dir.mkdir(parents=True, exist_ok=True)
    l_nm = round(L * 1000)
    stem = f'{model}_L{l_nm}nm_W{W:g}um'

    if pol == 'pmos':
        vgs_sweeps = lambda vds: run_vsg_sweeps(W, L, model=model,
                                                vsd_list=vds)
        vds_sweeps = lambda bias, w=W: run_vsd_sweeps(w, L, model=model,
                                                      vsg_bias_list=bias)
    else:
        vgs_sweeps = lambda vds: run_vgs_sweeps(W, L, model=model,
                                                vds_list=vds)
        vds_sweeps = lambda bias, w=W: run_vds_sweeps(w, L, model=model,
                                                      vgs_bias_list=bias)

    if plot_type == 'caps':
        out = out_dir / f'caps_{stem}.png'
        return Path(plot_caps(W, L, model, out_path=out))

    if plot_type == 'iv':
        vg = vgs_sweeps(cfg['vds_list'][-1:])
        if not vg:
            raise RuntimeError(f'Vgs sweep produced no data for {model}')
        w_iv = round(10 * L, 3)              # W/L = 10 output curves
        vd_iv = vds_sweeps(cfg['vgs_iv'], w=w_iv)
        out = out_dir / f'iv_{stem}.png'
        return Path(plot_iv(vg, vd_iv, W, L, w_iv_um=w_iv, model=model,
                            out_path=out))

    if plot_type == 'main':
        vg = vgs_sweeps(cfg['vds_list'])
        if not vg:
            raise RuntimeError(f'Vgs sweep produced no data for {model}')
        vd = vds_sweeps(cfg['vgs_bias'])
        vg_gds = vgs_sweeps(cfg['vds_gds'])
        out = out_dir / f'main_{stem}.png'
        return Path(plot_main(vg, vd, W, L, model, out_path=out,
                              vgs_gds_results=vg_gds))

    raise ValueError(f'Unknown plot type: {plot_type!r}')

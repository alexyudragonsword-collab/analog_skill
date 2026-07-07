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


def node_params_for(model: str) -> dict:
    """Sweep configuration for a model.

    Uses the three hand-tuned node configs when available; otherwise derives
    VDD-scaled bias/Vds lists from MODEL_INFO so newly-registered bulk nodes
    (130/90/65/32/…/LP) work without a bespoke table.
    """
    key = node_key(model)
    if key in NODE_PARAMS:
        return NODE_PARAMS[key]

    from simulate_gmoverid import MODEL_INFO
    vdd = float(MODEL_INFO[model].get('vdd', 1.8))
    # 9 gate biases spanning ~0.15·VDD .. 0.95·VDD; Vds fractions in saturation
    vgs_bias = [round(vdd * f, 3) for f in
                (0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95)]
    return dict(
        vds_list=[round(vdd * f, 3) for f in (0.25, 0.5, 0.9)],
        vds_gds=[round(vdd * f, 3) for f in
                 (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)],
        vgs_bias=vgs_bias,
        vgs_iv=[round(vdd * f, 3) for f in (0.4, 0.5, 0.6, 0.7, 0.8)],
    )


def _polarity(model: str) -> str:
    from simulate_gmoverid import MODEL_INFO
    return MODEL_INFO[model].get('pol', 'nmos')


def generate_plot(plot_type: str, model: str, W: float, L: float,
                  out_dir: Path) -> Path:
    """Run the sweeps for one plot type and save the PNG.  Worker thread."""
    from simulate_gmoverid import (
        run_vgs_sweeps, run_vds_sweeps, run_vsg_sweeps, run_vsd_sweeps)
    from plot_gmoverid import plot_main, plot_iv, plot_caps

    cfg = node_params_for(model)
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


# ─────────────────────────────────────────────────────────────────────────────
# Comparison plots (mirror run_gmoverid / run_multinode orchestration)
# ─────────────────────────────────────────────────────────────────────────────
def _run_comp(model, L):
    """Primary Vgs sweep + Vds output sweeps + gds sweep for one (model, L).

    Returns (vg, vd, vg_gds) — mirrors _run_comp in run_gmoverid/run_multinode.
    """
    from simulate_gmoverid import (
        run_vgs_sweeps, run_vds_sweeps, run_vsg_sweeps, run_vsd_sweeps)
    cfg = node_params_for(model)
    vds_comp = [cfg['vds_list'][-1]]         # single Vds ~ saturation
    if _polarity(model) == 'pmos':
        vg = run_vsg_sweeps(10.0, L, model=model, vsd_list=vds_comp)
        vd = run_vsd_sweeps(10.0, L, model=model, vsg_bias_list=cfg['vgs_bias'])
        vg_gds = run_vsg_sweeps(10.0, L, model=model, vsd_list=cfg['vds_gds'])
    else:
        vg = run_vgs_sweeps(10.0, L, model=model, vds_list=vds_comp)
        vd = run_vds_sweeps(10.0, L, model=model, vgs_bias_list=cfg['vgs_bias'])
        vg_gds = run_vgs_sweeps(10.0, L, model=model, vds_list=cfg['vds_gds'])
    return vg, vd, vg_gds


def generate_length_comparison(model, L_list, out_dir: Path) -> Path:
    """Overlay gm/ID four-quadrant curves for one model at several L values."""
    from plot_gmoverid import plot_comparison
    pol = _polarity(model)
    sweeps, vds_sweeps_list, gds_sweeps, labels = [], [], [], []
    for L in L_list:
        vg, vd, vg_gds = _run_comp(model, L)
        if not vg:
            raise RuntimeError(f'sweep produced no data for {model} L={L}')
        sweeps.append(vg)
        vds_sweeps_list.append(vd)
        gds_sweeps.append(vg_gds)
        labels.append(f'L = {round(L * 1000)} nm')
    out_dir.mkdir(parents=True, exist_ok=True)
    ls = '_'.join(str(round(L * 1000)) for L in L_list)
    out = out_dir / f'cmp_length_{model}_{ls}nm.png'
    return Path(plot_comparison(
        sweep_list=sweeps, vds_list=vds_sweeps_list, vgs_gds_list=gds_sweeps,
        param_labels=labels, polarity=pol,
        title=f'{model} Channel-Length Comparison',
        out_path=out))


def generate_node_comparison(models, out_dir: Path) -> Path:
    """Overlay gm/ID four-quadrant curves across several models (each at its
    nominal L)."""
    from plot_gmoverid import plot_comparison
    from app.core.model_registry import nominal_L
    pol = _polarity(models[0])
    sweeps, vds_sweeps_list, gds_sweeps, labels = [], [], [], []
    for model in models:
        if _polarity(model) != pol:
            raise ValueError('node comparison mixes nmos and pmos models')
        L = nominal_L(model)
        vg, vd, vg_gds = _run_comp(model, L)
        if not vg:
            raise RuntimeError(f'sweep produced no data for {model}')
        sweeps.append(vg)
        vds_sweeps_list.append(vd)
        gds_sweeps.append(vg_gds)
        labels.append(model)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f'cmp_node_{pol}_{"_".join(models)}.png'
    return Path(plot_comparison(
        sweep_list=sweeps, vds_list=vds_sweeps_list, vgs_gds_list=gds_sweeps,
        param_labels=labels, polarity=pol,
        title=f'{pol.upper()} Node Comparison',
        out_path=out))


def generate_caps_comparison(models, out_dir: Path) -> Path:
    """Cross-node gate-capacitance comparison (analytical, fast)."""
    from plot_gmoverid import plot_caps_comparison
    from app.core.model_registry import nominal_L
    pol = _polarity(models[0])
    node_configs = [(m, 10.0, nominal_L(m)) for m in models]
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f'cmp_caps_{pol}_{"_".join(models)}.png'
    return Path(plot_caps_comparison(node_configs, polarity=pol, out_path=out))

"""Register extra PTM bulk-CMOS nodes into gmoverid's MODEL_INFO.

gmoverid ships only 3 built-in nodes (180 / 45hp / 22hp).  The
transistor-models skill carries the full PTM bulk library; here we inject
the remaining bulk nodes as MODEL_INFO entries at runtime — no skill file is
edited.  MODEL_INFO['file'] accepts any Path, and every bulk .lib uses the
lowercase model names 'nmos' / 'pmos' (verified), so the existing
.include-based, W-swept netlist templates work unchanged.

FinFET nodes (7–20 nm) are deliberately NOT registered: they use BSIM-CMG
with .lib-section syntax and NFIN (not W), which is incompatible with the
current netlist templates and the W-based gm/ID flow — a separate effort.

Each entry mirrors the built-in schema:
    dict(pol, file=<Path>, model_name, vdd, vgs_stop, vds_stop)
By PTM convention vgs_stop = vds_stop = 1.2 x VDD (headroom for the sweeps),
matching how the built-ins are configured (e.g. 45hp: VDD 1.0, stop 1.2).
"""

# node tag -> (lib filename in bulk_cmos/, VDD)
_BULK_NODES = {
    '130':  ('ptm130.lib',  1.3),
    '90':   ('ptm90.lib',   1.2),
    '65':   ('ptm65.lib',   1.1),
    '45lp': ('ptm45lp.lib', 1.1),
    '32hp': ('ptm32hp.lib', 0.9),
    '32lp': ('ptm32lp.lib', 1.0),
    '22lp': ('ptm22lp.lib', 1.0),
}

# nominal channel length per node family [um] (for GUI L defaults)
NODE_L_UM = {
    '180': 0.18, '130': 0.13, '90': 0.09, '65': 0.065,
    '45': 0.045, '32': 0.032, '22': 0.022,
}


def _stop(vdd: float) -> float:
    return round(vdd * 1.2, 3)


def build_extra_models() -> dict:
    """Return the MODEL_INFO entries to inject (file paths resolved)."""
    from app import paths
    bulk_dir = paths.bulk_models_dir()
    extra = {}
    for tag, (libname, vdd) in _BULK_NODES.items():
        lib = bulk_dir / libname
        for pol in ('nmos', 'pmos'):
            extra[f'{pol}{tag}'] = dict(
                pol=pol,
                file=lib,
                model_name=pol,          # lowercase in every bulk PTM lib
                vdd=vdd,
                vgs_stop=_stop(vdd),
                vds_stop=_stop(vdd),
            )
    return extra


def register_extra_models() -> list[str]:
    """Inject extra bulk nodes into simulate_gmoverid.MODEL_INFO.

    Only adds entries whose .lib file actually exists; returns the list of
    registered model keys.  Idempotent.
    """
    import simulate_gmoverid as sg
    added = []
    for key, entry in build_extra_models().items():
        if key in sg.MODEL_INFO:
            continue
        if not entry['file'].exists():
            continue
        sg.MODEL_INFO[key] = entry
        added.append(key)
    return added


def nominal_L(model: str) -> float:
    """Nominal channel length [um] for a model key, e.g. 'nmos130' -> 0.13."""
    for tag in ('180', '130', '90', '65', '45', '32', '22'):
        if tag in model:
            return NODE_L_UM[tag]
    return 0.18

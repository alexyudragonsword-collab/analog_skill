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


# PTM convention: sweep stop voltage = 1.2 x VDD (matches the built-ins)
PTM_HEADROOM = 1.2


def _stop(vdd: float) -> float:
    return round(vdd * PTM_HEADROOM, 3)


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
    info = _finfet_info(model)
    if info is not None:
        return info['lg']
    for tag in ('180', '130', '90', '65', '45', '32', '22'):
        if tag in model:
            return NODE_L_UM[tag]
    return 0.18


# ─────────────────────────────────────────────────────────────────────────────
# FinFET (BSIM-CMG via OSDI) nodes — PTM-MG 7–20 nm, HP and LSTP
# ─────────────────────────────────────────────────────────────────────────────
# node tag -> (VDD, Lg [nm])   (from transistor-models/.../finfet/param.inc)
_FINFET_NODES = {
    '20': (0.90, 24), '16': (0.85, 20), '14': (0.80, 18),
    '10': (0.75, 14), '7': (0.70, 11),
}
_FINFET_VARIANTS = ('hp', 'lstp')


def _finfet_info(model: str) -> dict | None:
    """MODEL_INFO entry for a finfet model key, or None if not one."""
    import simulate_gmoverid as sg
    info = sg.MODEL_INFO.get(model)
    if info and info.get('kind') == 'finfet':
        return info
    return None


def build_finfet_models() -> dict:
    """MODEL_INFO entries for all PTM-MG FinFET devices (paths resolved)."""
    from app import paths
    root = paths.finfet_models_dir()
    extra = {}
    for tag, (vdd, lg_nm) in _FINFET_NODES.items():
        stop = _stop(vdd)
        for variant in _FINFET_VARIANTS:
            for pol, mname, pfx in (('nmos', 'nfet', 'nfin'),
                                    ('pmos', 'pfet', 'pfin')):
                pm = root / variant / f'{tag}{"n" if pol == "nmos" else "p"}fet.pm'
                extra[f'{pfx}{tag}{variant}'] = dict(
                    pol=pol, file=pm, model_name=mname, vdd=vdd,
                    vgs_stop=stop, vds_stop=stop,
                    kind='finfet', node=tag, variant=variant,
                    lg=lg_nm / 1000.0,   # µm
                )
    return extra


def register_finfet_models() -> list[str]:
    """Inject FinFET nodes into simulate_gmoverid.MODEL_INFO.

    Registered unconditionally (so the model list is stable); the GUI disables
    them when finfet_available() is False.  Only adds entries whose .pm exists.
    Idempotent.
    """
    import simulate_gmoverid as sg
    added = []
    for key, entry in build_finfet_models().items():
        if key in sg.MODEL_INFO:
            continue
        if not entry['file'].exists():
            continue
        sg.MODEL_INFO[key] = entry
        added.append(key)
    return added


def is_finfet(model: str) -> bool:
    return _finfet_info(model) is not None


def finfet_available() -> bool:
    """True if FinFET sims can actually run (osdi shipped + ngspice has OSDI)."""
    from app.core import finfet_sim
    return finfet_sim.osdi_path() is not None and finfet_sim.ngspice_has_osdi()

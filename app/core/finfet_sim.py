"""FinFET (BSIM-CMG) sweep engine for the gm/ID flow.

Stock ngspice has no built-in BSIM-CMG (level 72); the model is loaded at
runtime through ngspice's OSDI interface (``pre_osdi``) from a precompiled
``bsimcmg.osdi``.  Everything here mirrors the schema of the skill's
``simulate_gmoverid`` sweeps so ``FinFetTable`` can reuse GmIdTable's table
machinery unchanged — the one real difference is that gate capacitances are
read from the device's *actual* BSIM-CMG operating point (``@n1[cgg]`` …),
not the planar-MOS analytical Cox·W·L approximation (which is invalid for a
tri-gate fin).

Sizing uses the effective width  Weff = NFIN·(2·HFIN + TFIN); ``id_w`` is the
NFIN-independent current density Id/Weff [A/m], so a lookup at a target gm/ID
yields Weff → NFIN.
"""

import functools
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

# these come from the vendored skill (importable once paths.init_runtime ran)
from simulate_gmoverid import extract_vth


# ─────────────────────────────────────────────────────────────────────────────
# ngspice / OSDI helpers
# ─────────────────────────────────────────────────────────────────────────────
def _ngspice() -> str:
    for exe in ('ngspice_con', 'ngspice'):
        if shutil.which(exe):
            return exe
    raise RuntimeError('ngspice not found in PATH')


def osdi_path() -> Path | None:
    from app import paths
    return paths.finfet_osdi_path()


def _spath(p) -> str:
    return str(p).replace('\\', '/')


def _run(args, timeout=180):
    kw = dict(args=args, capture_output=True, text=True,
              timeout=timeout, stdin=subprocess.DEVNULL)
    if sys.platform == 'win32':
        kw['creationflags'] = subprocess.CREATE_NO_WINDOW
    r = subprocess.run(**kw)
    return r.returncode, (r.stdout + r.stderr).strip()


@functools.lru_cache(maxsize=64)
def ngspice_has_osdi() -> bool:
    """True if the ngspice on PATH understands the ``pre_osdi`` command."""
    try:
        exe = _ngspice()
    except RuntimeError:
        return False
    try:
        r = subprocess.run([exe, '-v'], capture_output=True, text=True,
                           timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return False
    # ngspice built with OSDI advertises it; fall back to a probe otherwise
    if 'osdi' in (r.stdout + r.stderr).lower():
        return True
    return _probe_osdi(exe)


_OSDI_FUNCTIONAL: bool | None = None


def osdi_functional() -> bool:
    """End-to-end micro-smoke: True only if the vendored bsimcmg.osdi
    actually loads AND simulates on this ngspice build.

    A shallow `pre_osdi is a known command` probe is not enough: some
    ngspice-42 builds (e.g. the KLU-solver build that appeared on GitHub
    ubuntu runners) accept pre_osdi but fail to run the BSIM-CMG module.
    Result is cached per process (~0.2 s once).
    """
    global _OSDI_FUNCTIONAL
    if _OSDI_FUNCTIONAL is None:
        try:
            _OSDI_FUNCTIONAL = _smoke_osdi()
        except Exception:
            _OSDI_FUNCTIONAL = False
    return _OSDI_FUNCTIONAL


def _smoke_osdi() -> bool:
    import tempfile
    from app import paths as _paths
    op = osdi_path()
    if op is None:
        return False
    pm = _paths.finfet_models_dir() / 'lstp' / '20nfet.pm'
    if not pm.is_file():
        return False
    card = osdi_modelcard(str(pm), 'nmos')
    with tempfile.TemporaryDirectory() as td:
        dat = Path(td) / 's.dat'
        deck = Path(td) / 's.cir'
        deck.write_text(
            '* osdi smoke\n'
            f'.include "{card}"\n'
            'Vgs vgs 0 DC 0\nVds vds 0 DC 0.45\n'
            'N1 vds vgs 0 0 nfet L=0.024u NFIN=10\n'
            '.control\n'
            f"  pre_osdi '{_spath(op)}'\n"
            '  dc Vgs 0 0.9 0.45\n'
            f"  wrdata '{_spath(dat)}' i(Vds)\n"
            '  quit\n.endc\n.end\n', encoding='ascii')
        try:
            _run([_ngspice(), '-b', str(deck)], timeout=60)
        except Exception:
            return False
        return dat.exists() and dat.stat().st_size > 0


def _probe_osdi(exe: str) -> bool:
    """Run a one-line deck that only succeeds if pre_osdi is a known command."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        deck = Path(td) / 'p.cir'
        deck.write_text('* probe\n.control\npre_osdi /nonexistent.osdi\nquit\n'
                        '.endc\n.end\n', encoding='ascii')
        try:
            r = subprocess.run([exe, '-b', _spath(deck)], capture_output=True,
                               text=True, timeout=15, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return False
        out = (r.stdout + r.stderr).lower()
        # unknown command → "pre_osdi" reported as unknown; known command →
        # it tries to open the (missing) file
        return 'error opening osdi' in out or 'osdi lib' in out


# ─────────────────────────────────────────────────────────────────────────────
# Modelcard adaptation:  built-in "nmos level=72" → OSDI module "bsimcmg_va"
# ─────────────────────────────────────────────────────────────────────────────
_MODEL_RE = re.compile(
    r'^\s*\.model\s+(\S+)\s+(nmos|pmos)\s+level\s*=\s*72\b', re.IGNORECASE)


@functools.lru_cache(maxsize=64)
def osdi_modelcard(pm_path: str, polarity: str) -> Path:
    """Return a path to an OSDI-typed copy of a PTM-MG .pm modelcard.

    The only change is the ``.model`` header: ``<name> nmos level=72`` becomes
    ``<name> bsimcmg_va`` with an explicit ``TYPE`` (1=nMOS, 0=pMOS, which the
    built-in card conveyed through the nmos/pmos keyword the OSDI model ignores).
    All electrical parameters pass through untouched.
    """
    from simulate_gmoverid import LOG_DIR
    cache = LOG_DIR / 'finfet_cards'
    cache.mkdir(parents=True, exist_ok=True)
    src = Path(pm_path)
    out = cache / f'{src.stem}_osdi.mod'

    # BSIM-CMG 112 TYPE: 1 = NMOS, -1 = PMOS (the built-in card conveyed this
    # via the nmos/pmos keyword the OSDI model ignores)
    type_val = 1 if polarity == 'nmos' else -1
    lines_out = []
    for line in src.read_text(encoding='utf-8', errors='replace').splitlines():
        m = _MODEL_RE.match(line)
        if m:
            lines_out.append(f'.model {m.group(1)} bsimcmg_va')
            lines_out.append(f'+ type = {type_val}')
        else:
            lines_out.append(line)
    out.write_text('\n'.join(lines_out) + '\n', encoding='ascii', errors='replace')
    return out


@functools.lru_cache(maxsize=64)
def parse_fin_geom(pm_path: str) -> float:
    """Effective width per fin  weff_per_fin = 2·HFIN + TFIN  [metres]."""
    hfin = tfin = None
    for line in Path(pm_path).read_text(encoding='utf-8', errors='replace').splitlines():
        for key in ('hfin', 'tfin'):
            m = re.search(rf'\b{key}\s*=\s*([0-9.eE+\-]+)', line, re.IGNORECASE)
            if m:
                try:
                    val = float(m.group(1))
                except ValueError:
                    continue
                if key == 'hfin':
                    hfin = val
                else:
                    tfin = val
    if hfin is None or tfin is None:
        raise RuntimeError(f'HFIN/TFIN not found in {pm_path}')
    return 2.0 * hfin + tfin


# ─────────────────────────────────────────────────────────────────────────────
# wrdata parsing (interleaved x,vec columns)
# ─────────────────────────────────────────────────────────────────────────────
def _parse_wrdata(path, n_vec):
    """Parse ``wrdata`` output of *n_vec* vectors → (x, [vec0, vec1, ...]).

    wrdata writes each vector preceded by the sweep variable, so the row is
    x v0 x v1 x v2 …  → 2·n_vec columns.
    """
    rows = []
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                float(line.split()[0])
            except (ValueError, IndexError):
                continue
            vals = []
            for tok in line.split():
                try:
                    vals.append(float(tok))
                except ValueError:
                    vals.append(0.0)
            if len(vals) >= 2 * n_vec:
                rows.append(vals[:2 * n_vec])
    if not rows:
        raise RuntimeError(f'No data in {path}')
    a = np.array(rows)
    x = a[:, 0]
    vecs = [a[:, 2 * i + 1] for i in range(n_vec)]
    return x, vecs


def _finalize_ft(ft):
    """Drop weak-inversion fT spikes (interior point < 10% of both neighbours)."""
    pad = np.where(np.isfinite(ft), ft, np.inf)
    spike = (np.isfinite(ft) &
             (ft < 0.1 * np.minimum(
                 np.concatenate([[np.inf], pad[:-1]]),
                 np.concatenate([pad[1:], [np.inf]]))))
    return np.where(spike, np.nan, ft)


# ─────────────────────────────────────────────────────────────────────────────
# Sweeps
# ─────────────────────────────────────────────────────────────────────────────
_VGS_STEP = 0.005    # 5 mV


def _tmpl(name):
    from app import paths
    return (paths.resources_dir() / 'netlist' / name).read_text(encoding='ascii')


def _model_entry(model):
    from simulate_gmoverid import MODEL_INFO
    return MODEL_INFO[model]


def _weff(info, nfin) -> float:
    """Effective width [m] for NFIN fins of this node."""
    wpf = info.get('weff_per_fin') or parse_fin_geom(str(info['file']))
    return nfin * wpf


def sweep_vgs_finfet(vds, nfin, model, l_um):
    """nMOS-convention Vgs sweep at fixed Vds; real BSIM-CMG caps.

    Returns the same dict schema as simulate_gmoverid.sweep_vgs (all positive):
      model, pol, vds, vgs, id, gm, cgs, cgd, cgb, cgg, gmid, ft, id_w, vov, vth
    plus gds/ro from the device operating point.
    """
    from simulate_gmoverid import LOG_DIR
    info = _model_entry(model)
    if info.get('pol') == 'pmos':
        return _sweep_vsg_finfet(vds, nfin, model, l_um)

    op = osdi_path()
    if op is None:
        raise RuntimeError('bsimcmg.osdi not available for this platform')
    vgs_stop = float(info.get('vgs_stop', 1.0))
    card = osdi_modelcard(str(info['file']), 'nmos')
    weff = _weff(info, nfin)

    tag = f'{model}_L{l_um*1000:.0f}nm_N{nfin}_vds{vds:.2f}'.replace('.', 'p')
    cir = LOG_DIR / f'_ff_vgs_{tag}.cir'
    dat = LOG_DIR / f'_ff_vgs_{tag}.dat'
    log = LOG_DIR / f'_ff_vgs_{tag}.log'
    if dat.exists():
        dat.unlink()

    nl = _tmpl('finfet_vgs.cir.tmpl').format(
        model_path=_spath(card), model=info['model_name'], osdi_path=_spath(op),
        vds_v=f'{vds:.4f}', l_um=f'{l_um:.5f}', nfin=int(nfin),
        vgs_start='0.000', vgs_stop=f'{vgs_stop:.3f}', vgs_step=f'{_VGS_STEP:.5f}',
        dat_path=_spath(dat))
    cir.write_text(nl, encoding='ascii')

    rc, out = _run([_ngspice(), '-b', '-o', _spath(log), _spath(cir)])
    if not dat.exists():
        lt = log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''
        raise RuntimeError(f'ngspice/OSDI failed (model={model} Vds={vds}V):\n'
                           + '\n'.join((out + '\n' + lt).splitlines()[:30]))

    vgs, (icur, gm, gds, cgg, cgs, cgd) = _parse_wrdata(dat, 6)
    return _assemble(model, 'nmos', vds, vgs, icur, icur_sign=-1.0,
                     gm=gm, gds=gds, cgg=cgg, cgs=cgs, cgd=cgd,
                     weff=weff, l_um=l_um)


def _sweep_vsg_finfet(vsd, nfin, model, l_um):
    """pMOS |Vsg| sweep at fixed |Vsd|; returns positive-convention dict."""
    from simulate_gmoverid import LOG_DIR
    info = _model_entry(model)
    op = osdi_path()
    if op is None:
        raise RuntimeError('bsimcmg.osdi not available for this platform')
    vdd = float(info.get('vdd', 0.8))
    card = osdi_modelcard(str(info['file']), 'pmos')
    weff = _weff(info, nfin)
    vd_v = vdd - vsd

    tag = f'{model}_L{l_um*1000:.0f}nm_N{nfin}_vsd{vsd:.2f}'.replace('.', 'p')
    cir = LOG_DIR / f'_ff_vsg_{tag}.cir'
    dat = LOG_DIR / f'_ff_vsg_{tag}.dat'
    log = LOG_DIR / f'_ff_vsg_{tag}.log'
    if dat.exists():
        dat.unlink()

    nl = _tmpl('finfet_pmos_vsg.cir.tmpl').format(
        model_path=_spath(card), model=info['model_name'], osdi_path=_spath(op),
        vdd_v=f'{vdd:.4f}', vd_v=f'{vd_v:.4f}', vsd_v=f'{vsd:.4f}',
        l_um=f'{l_um:.5f}', nfin=int(nfin),
        vg_step=f'{-_VGS_STEP:.5f}', dat_path=_spath(dat))
    cir.write_text(nl, encoding='ascii')

    rc, out = _run([_ngspice(), '-b', '-o', _spath(log), _spath(cir)])
    if not dat.exists():
        lt = log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''
        raise RuntimeError(f'ngspice/OSDI failed (model={model} |Vsd|={vsd}V):\n'
                           + '\n'.join((out + '\n' + lt).splitlines()[:30]))

    vg_abs, (icur, gm, gds, cgg, cgs, cgd) = _parse_wrdata(dat, 6)
    vsg = vdd - vg_abs                        # |Vsg| ascending 0 → VDD
    order = np.argsort(vsg)
    vsg = vsg[order]
    icur, gm, gds = icur[order], gm[order], gds[order]
    cgg, cgs, cgd = cgg[order], cgs[order], cgd[order]
    return _assemble(model, 'pmos', vsd, vsg, icur, icur_sign=+1.0,
                     gm=gm, gds=gds, cgg=cgg, cgs=cgs, cgd=cgd,
                     weff=weff, l_um=l_um)


def _assemble(model, pol, vds, vgs, icur, icur_sign, gm, gds, cgg, cgs, cgd,
              weff, l_um):
    """Build the unified positive-convention sweep dict from raw vectors.

    Same keys as simulate_gmoverid.sweep_vgs, all positive; caps are the real
    BSIM-CMG operating-point values (cgb derived as cgg − cgs − cgd).
    """
    vgs = np.asarray(vgs, dtype=float)
    id_ = np.maximum(icur_sign * np.asarray(icur, dtype=float), 0.0)
    gm  = np.maximum(np.asarray(gm,  dtype=float), 0.0)
    gds = np.maximum(np.asarray(gds, dtype=float), 1e-15)
    cgg = np.abs(np.asarray(cgg, dtype=float))
    cgs = np.abs(np.asarray(cgs, dtype=float))
    cgd = np.abs(np.asarray(cgd, dtype=float))
    cgb = np.maximum(cgg - cgs - cgd, 0.0)

    weff_um = weff * 1e6
    vth = extract_vth(vgs, id_, weff_um, l_um)
    id_thresh = 1e-13
    gmid = np.where(id_ > id_thresh, gm / np.maximum(id_, id_thresh), np.nan)
    ft   = np.where(cgg > 0, gm / (2.0 * np.pi * np.maximum(cgg, 1e-21)), np.nan)
    ft   = _finalize_ft(ft)
    id_w = id_ / weff          # A/m  (NFIN-independent current density)
    vov  = vgs - vth
    ro   = 1.0 / gds

    return dict(model=model, pol=pol, vds=float(vds), vgs=vgs,
                id=id_, gm=gm, cgs=cgs, cgd=cgd, cgb=cgb, cgg=cgg,
                gmid=gmid, ft=ft, id_w=id_w, vov=vov, vth=vth,
                gds=gds, ro=ro)


# ─────────────────────────────────────────────────────────────────────────────
# Vds output sweeps (for browser IV / output-resistance quadrant)
# ─────────────────────────────────────────────────────────────────────────────
_VDS_STEP = 0.005


def sweep_vds_finfet(vgs_bias, nfin, model, l_um):
    """Vds output sweep at fixed Vgs (nMOS) / |Vsd| at fixed |Vsg| (pMOS).

    Returns dict(model, pol, vgs, vds, id, gds, ro) — same schema as
    simulate_gmoverid.sweep_vds.
    """
    from simulate_gmoverid import LOG_DIR
    info = _model_entry(model)
    op = osdi_path()
    if op is None:
        raise RuntimeError('bsimcmg.osdi not available for this platform')
    vds_stop = float(info.get('vds_stop', 1.0))

    tag = f'{model}_L{l_um*1000:.0f}nm_N{nfin}_vgs{vgs_bias:.2f}'.replace('.', 'p')
    cir = LOG_DIR / f'_ff_vds_{tag}.cir'
    dat = LOG_DIR / f'_ff_vds_{tag}.dat'
    log = LOG_DIR / f'_ff_vds_{tag}.log'
    if dat.exists():
        dat.unlink()

    if info.get('pol') == 'pmos':
        vdd = float(info.get('vdd', 0.8))
        card = osdi_modelcard(str(info['file']), 'pmos')
        vg_v = vdd - vgs_bias
        vd_stop = vdd - vds_stop
        nl = _tmpl('finfet_pmos_vsd.cir.tmpl').format(
            model_path=_spath(card), model=info['model_name'], osdi_path=_spath(op),
            vdd_v=f'{vdd:.4f}', vg_v=f'{vg_v:.4f}', vsg_v=f'{vgs_bias:.4f}',
            l_um=f'{l_um:.5f}', nfin=int(nfin),
            vd_stop=f'{vd_stop:.4f}', vd_step=f'{-_VDS_STEP:.5f}', dat_path=_spath(dat))
    else:
        card = osdi_modelcard(str(info['file']), 'nmos')
        nl = _tmpl('finfet_vds.cir.tmpl').format(
            model_path=_spath(card), model=info['model_name'], osdi_path=_spath(op),
            vgs_v=f'{vgs_bias:.4f}', l_um=f'{l_um:.5f}', nfin=int(nfin),
            vds_start='0.000', vds_stop=f'{vds_stop:.3f}', vds_step=f'{_VDS_STEP:.5f}',
            dat_path=_spath(dat))
    cir.write_text(nl, encoding='ascii')

    rc, out = _run([_ngspice(), '-b', '-o', _spath(log), _spath(cir)])
    if not dat.exists():
        lt = log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''
        raise RuntimeError(f'ngspice/OSDI failed (model={model} vds-sweep):\n'
                           + '\n'.join((out + '\n' + lt).splitlines()[:30]))

    x, (icur, gds) = _parse_wrdata(dat, 2)
    if info.get('pol') == 'pmos':
        vdd = float(info.get('vdd', 0.8))
        vds = vdd - x
        id_ = np.maximum(icur, 0.0)
        order = np.argsort(vds)
        vds, id_, gds = vds[order], id_[order], gds[order]
    else:
        vds = x
        id_ = np.maximum(-icur, 0.0)
    gds = np.maximum(np.abs(gds), 1e-15)
    return dict(model=model, pol=info.get('pol', 'nmos'), vgs=float(vgs_bias),
                vds=vds, id=id_, gds=gds, ro=1.0 / gds)


# ─────────────────────────────────────────────────────────────────────────────
# Multi-point runners (mirror run_vgs_sweeps / run_vds_sweeps signatures)
# ─────────────────────────────────────────────────────────────────────────────
def run_vgs_sweeps_finfet(nfin, model, l_um, vds_list):
    out = []
    for vds in vds_list:
        try:
            out.append(sweep_vgs_finfet(vds, nfin, model, l_um))
        except RuntimeError as e:
            print(f'  [finfet vgs ERROR] {e}')
    return out


def run_vds_sweeps_finfet(nfin, model, l_um, vgs_bias_list):
    out = []
    for vgs in vgs_bias_list:
        try:
            out.append(sweep_vds_finfet(vgs, nfin, model, l_um))
        except RuntimeError as e:
            print(f'  [finfet vds ERROR] {e}')
    return out

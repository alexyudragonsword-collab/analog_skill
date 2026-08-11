"""Matplotlib rendering for the Sizing tab.

Convergence curves and the before/after wave overlays.  Every function
here must run on the GUI thread (matplotlib is not thread-safe) and
returns the path of the PNG it wrote.
"""

from pathlib import Path

import numpy as np

from app.core.sizing.evaluation import _run_dir
from app.core.sizing.registry import SIZING
from app.core.sizing.report import SizingRun
from app.core.sizing.runs import runs_dir


_WAVE_B = dict(color='#95a5a6', ls='--', lw=1.6)     # 'default' style


_WAVE_A = dict(color='#2874a6', lw=1.8)              # 'optimized' style


_WAVE_B2 = dict(color='#95a5a6', ls=':', lw=1.3)     # secondary pair


_WAVE_A2 = dict(color='#148f77', lw=1.5)


def _wave_panels_amp(axes, before, after):
    (ax_g, ax_p), (ax_r, ax_t) = axes
    if 'freq' in before and 'freq' in after:
        ax_g.semilogx(before['freq'], before['adm_db'],
                      label='default', **_WAVE_B)
        ax_g.semilogx(after['freq'], after['adm_db'],
                      label='optimized', **_WAVE_A)
        ax_g.axhline(0, color='#c0392b', ls=':', lw=1)
        # the amp TB doesn't `set units=degrees`, so vp() is radians
        ax_p.semilogx(before['freq'], np.degrees(before['adm_ph']), **_WAVE_B)
        ax_p.semilogx(after['freq'], np.degrees(after['adm_ph']), **_WAVE_A)
        ax_r.semilogx(before['freq'], before['psrp_db'],
                      label='PSRR+ default', **_WAVE_B)
        ax_r.semilogx(after['freq'], after['psrp_db'],
                      label='PSRR+ optimized', **_WAVE_A)
        ax_r.semilogx(before['freq'], before['psrn_db'],
                      label='PSRR− default', **_WAVE_B2)
        ax_r.semilogx(after['freq'], after['psrn_db'],
                      label='PSRR− optimized', **_WAVE_A2)
        ax_r.legend(fontsize=7)
    ax_g.set_xlabel('frequency (Hz)'); ax_g.set_ylabel('|Adm| (dB)')
    ax_g.set_title('Differential gain', fontsize=10); ax_g.legend(fontsize=8)
    ax_p.set_xlabel('frequency (Hz)'); ax_p.set_ylabel('phase (deg)')
    ax_p.set_title('Phase', fontsize=10)
    ax_r.set_xlabel('frequency (Hz)'); ax_r.set_ylabel('PSRR (dB)')
    ax_r.set_title('Supply rejection', fontsize=10)
    if 'temp' in before and 'temp' in after:
        ax_t.plot(before['temp'], before['vout'] * 1e3, **_WAVE_B)
        ax_t.plot(after['temp'], after['vout'] * 1e3, **_WAVE_A)
    ax_t.set_xlabel('temperature (°C)'); ax_t.set_ylabel('Vout (mV)')
    ax_t.set_title('Output vs temperature (offset drift)', fontsize=10)


def _wave_panels_ldo(axes, before, after):
    (ax_g, ax_p), (ax_r, ax_v) = axes
    for w, sty, sty2, lbl in ((before, _WAVE_B, _WAVE_B2, 'default'),
                              (after, _WAVE_A, _WAVE_A2, 'optimized')):
        if 'lg_max' in w:
            g = w['lg_max']
            ax_g.semilogx(g['freq'], g['gain_db'],
                          label=f'{lbl} (max load)', **sty)
            # LDO TBs `set units=degrees` — phase already in degrees
            ax_p.semilogx(g['freq'], g['phase'], **sty)
            ax_r.semilogx(g['freq'], g['psrr_db'], label=lbl, **sty)
        if 'lg_min' in w:
            g = w['lg_min']
            ax_g.semilogx(g['freq'], g['gain_db'],
                          label=f'{lbl} (min load)', **sty2)
            ax_p.semilogx(g['freq'], g['phase'], **sty2)
        if 'vin' in w:
            ax_v.plot(w['vin'], w['vout'], label=lbl, **sty)
    ax_g.axhline(0, color='#c0392b', ls=':', lw=1)
    ax_g.set_xlabel('frequency (Hz)'); ax_g.set_ylabel('loop gain (dB)')
    ax_g.set_title('Loop gain', fontsize=10); ax_g.legend(fontsize=7)
    ax_p.set_xlabel('frequency (Hz)'); ax_p.set_ylabel('phase (deg)')
    ax_p.set_title('Loop phase', fontsize=10)
    ax_r.set_xlabel('frequency (Hz)'); ax_r.set_ylabel('PSRR (dB)')
    ax_r.set_title('Supply rejection (max load)', fontsize=10)
    ax_r.legend(fontsize=8)
    ax_v.set_xlabel('VDD (V)'); ax_v.set_ylabel('Vout (V)')
    ax_v.set_title('Line regulation (Vout vs VDD)', fontsize=10)
    ax_v.legend(fontsize=8)


def _wave_panels_skill_ac(axes, before, after):
    ax_g, ax_p = axes
    for w, sty, lbl in ((before, _WAVE_B, 'default'),
                        (after, _WAVE_A, 'optimized')):
        if 'freq' in w:
            ax_g.semilogx(w['freq'], w['gain_db'], label=lbl, **sty)
            ax_p.semilogx(w['freq'], w['phase'], **sty)
    ax_g.axhline(0, color='#c0392b', ls=':', lw=1)
    ax_g.set_xlabel('frequency (Hz)'); ax_g.set_ylabel('gain (dB)')
    ax_g.set_title('Gain', fontsize=10); ax_g.legend(fontsize=8)
    ax_p.set_xlabel('frequency (Hz)'); ax_p.set_ylabel('phase (deg)')
    ax_p.set_title('Phase', fontsize=10)


def _wave_panels_skill_ldo(axes, before, after):
    (ax_g, ax_p), (ax_r, ax_z) = axes
    for w, sty, lbl in ((before, _WAVE_B, 'default'),
                        (after, _WAVE_A, 'optimized')):
        lg = w.get('loopgain')
        if lg:
            ax_g.semilogx(lg['freq'], lg['mag_db'], label=lbl, **sty)
            if 'phase_deg' in lg:
                ax_p.semilogx(lg['freq'], lg['phase_deg'], **sty)
        ps = w.get('psrr')
        if ps:
            ax_r.semilogx(ps['freq'], ps['mag_db'], label=lbl, **sty)
        zo = w.get('zout')
        if zo:
            ax_z.semilogx(zo['freq'], zo['mag_db'], label=lbl, **sty)
    ax_g.axhline(0, color='#c0392b', ls=':', lw=1)
    ax_g.set_xlabel('frequency (Hz)'); ax_g.set_ylabel('loop gain (dB)')
    ax_g.set_title('Loop gain (NaN past GBW by design)', fontsize=10)
    ax_g.legend(fontsize=8)
    ax_p.set_xlabel('frequency (Hz)'); ax_p.set_ylabel('phase (deg)')
    ax_p.set_title('Loop phase', fontsize=10)
    ax_r.set_xlabel('frequency (Hz)'); ax_r.set_ylabel('|vout/vdd| (dB)')
    ax_r.set_title('Supply rejection', fontsize=10); ax_r.legend(fontsize=8)
    ax_z.set_xlabel('frequency (Hz)'); ax_z.set_ylabel('|Zout| (dBΩ)')
    ax_z.set_title('Output impedance', fontsize=10); ax_z.legend(fontsize=8)


def _wave_panels_skill_wave(axes, before, after):
    ax_l, ax_o = axes
    for w, sty, sty2, lbl in ((before, _WAVE_B, _WAVE_B2, 'default'),
                              (after, _WAVE_A, _WAVE_A2, 'optimized')):
        if 'time' not in w:
            continue
        t = w['time'] * 1e9
        tau = w['metrics'].get('tau_ps')
        ax_l.plot(t, w['vlp'], label=f'{lbl} (τ={tau:.1f} ps)', **sty)
        ax_l.plot(t, w['vln'], **sty2)
        ax_o.plot(t, w['outp'], label=lbl, **sty)
        ax_o.plot(t, w['outn'], **sty2)
    ax_l.set_xlabel('time (ns)'); ax_l.set_ylabel('V')
    ax_l.set_title('Latch nodes vlp/vln (regeneration)', fontsize=10)
    ax_l.legend(fontsize=8)
    ax_o.set_xlabel('time (ns)'); ax_o.set_ylabel('V')
    ax_o.set_title('Outputs outp/outn', fontsize=10); ax_o.legend(fontsize=8)


def _wave_panels_skill_ron(axes, before, after):
    ax_b, ax_all = axes
    for w, sty, lbl in ((before, _WAVE_B, 'default'),
                        (after, _WAVE_A, 'optimized')):
        if 'vin_pts' in w and 'ron_bts' in w:
            ax_b.plot(w['vin_pts'], w['ron_bts'], label=lbl, **sty)
    ax_b.set_xlabel('Vin (V)'); ax_b.set_ylabel('Ron (Ω)')
    ax_b.set_title('Bootstrapped switch Ron vs Vin', fontsize=10)
    ax_b.legend(fontsize=8)
    styles = {'ron_bts': _WAVE_A, 'ron_cmos': _WAVE_A2,
              'ron_nmos': dict(color='#b03a2e', lw=1.3, ls='--'),
              'ron_pmos': dict(color='#7d3c98', lw=1.3, ls=':')}
    for k, sty in styles.items():
        if k in after and 'vin_pts' in after:
            ax_all.plot(after['vin_pts'], after[k],
                        label=k.replace('ron_', ''), **sty)
    ax_all.set_yscale('log')
    ax_all.set_xlabel('Vin (V)'); ax_all.set_ylabel('Ron (Ω, log)')
    ax_all.set_title('Optimized: switch-type comparison', fontsize=10)
    ax_all.legend(fontsize=8)


def render_convergence(run: SizingRun) -> Path:
    """Draw the convergence curve (GUI thread — matplotlib policy)."""
    import matplotlib
    matplotlib.use('Agg', force=False)
    import matplotlib.pyplot as plt
    xs = [h[0] for h in run.history]
    ys = [-h[1] for h in run.history]
    fig, ax = plt.subplots(figsize=(6.4, 4.2), constrained_layout=True)
    ax.plot(xs, ys, '-o', ms=3, color='#2874a6')
    ax.set_xlabel('evaluation')
    ax.set_ylabel('best FoM (= -cost, higher is better)')
    title = SIZING[run.circuit].title
    ax.set_title(f'Sizing convergence — {title}', fontsize=10)
    ax.grid(alpha=0.3)
    out = _run_dir(run.circuit) / 'convergence.png'
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def render_wave_comparison(circuit: str, before: dict, after: dict) -> Path:
    """Overlay the default-sizing vs best-sizing characterization sweeps
    (GUI thread — matplotlib policy).  Panel layout follows the wave kind
    from capture_waves (see its docstring): amps/LDOs get 2x2 frequency +
    DC panels; skill circuits get their family's natural curves."""
    import matplotlib
    matplotlib.use('Agg', force=False)
    import matplotlib.pyplot as plt
    kind = before.get('kind', 'amp')
    if kind in ('amp', 'ldo', 'skill_ldo'):
        fig, axes = plt.subplots(2, 2, figsize=(9.6, 7.0),
                                 constrained_layout=True)
    else:
        fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.0),
                                 constrained_layout=True)
    {'amp': _wave_panels_amp, 'ldo': _wave_panels_ldo,
     'skill_ac': _wave_panels_skill_ac, 'skill_ldo': _wave_panels_skill_ldo,
     'skill_wave': _wave_panels_skill_wave,
     'skill_ron': _wave_panels_skill_ron}[kind](axes, before, after)
    for ax in np.asarray(axes).flat:
        ax.grid(alpha=0.3, which='both')
    fig.suptitle(f'Before/after characterization — {SIZING[circuit].title}',
                 fontsize=11)
    out = _run_dir(circuit) / 'wave_compare.png'
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def render_comparison(runs: list[SizingRun]) -> Path:
    """Overlay the convergence curves of several saved runs
    (GUI thread — matplotlib policy)."""
    import matplotlib
    matplotlib.use('Agg', force=False)
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.4, 4.2), constrained_layout=True)
    for run in runs:
        xs = [h[0] for h in run.history]
        ys = [-h[1] for h in run.history]
        ax.plot(xs, ys, '-o', ms=3,
                label=f'{run.circuit}  ({run.evals} evals, '
                      f'FoM {-run.best_cost:.3f})')
    ax.set_xlabel('evaluation')
    ax.set_ylabel('best FoM (= -cost, higher is better)')
    ax.set_title('Sizing runs — convergence comparison', fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    out = runs_dir() / 'comparison.png'
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out

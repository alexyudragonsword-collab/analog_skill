"""Runtime path setup for Analog Studio.

Resolves where the skill asset trees live (repo checkout vs frozen bundle),
makes sure they are importable, and exposes the writable output locations.

Frozen mode: PyInstaller bundles the two asset trees under ``skill/`` next to
the executable.  Because every skill module writes logs/plots/cache relative
to its own ``__file__``, the trees are synced once per app version into a
user-writable workspace and *that* copy is imported — no patching of skill
code is needed for the write paths to land somewhere writable.
"""

import os
import shutil
import sys
from pathlib import Path

from app import __version__

_initialized = False

#: filled in by init_runtime()
NGSPICE_ASSETS: Path = None
GMOVERID_ASSETS: Path = None
BROWSER_PLOTS: Path = None


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    # sys.frozen: PyInstaller and Nuitka standalone both set it;
    # __compiled__ exists in every Nuitka-compiled module as a fallback.
    return bool(getattr(sys, 'frozen', False)) or '__compiled__' in globals()


def _bundle_skill_dir() -> Path:
    """Location of the bundled skill/ trees in a frozen app."""
    base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    cand = base / 'skill'
    if cand.is_dir():
        return cand
    # onedir layout: data files live in _internal next to the executable
    return Path(sys.executable).parent / '_internal' / 'skill'


def _workspace_root() -> Path:
    from PySide6.QtCore import QStandardPaths
    loc = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation)
    return Path(loc) / 'workspace' / __version__


def _sync_tree(src: Path, dst: Path):
    """Copy src → dst once, atomically.

    The copy lands in a sibling .tmp directory first and is renamed into
    place, so an interrupted first launch can never leave a half-copied tree
    that a later `dst.exists()` check would mistake for a complete one.
    """
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + '.tmp')
    if tmp.exists():                       # stale leftover from a crash
        shutil.rmtree(tmp)
    shutil.copytree(
        src, tmp,
        ignore=shutil.ignore_patterns('__pycache__', 'logs', 'plots'))
    os.replace(tmp, dst)


def _prune_old_workspaces(ws_version_dir: Path):
    """Delete workspace dirs left over from previous app versions."""
    parent = ws_version_dir.parent
    if not parent.is_dir():
        return
    for entry in parent.iterdir():
        if entry.is_dir() and entry != ws_version_dir:
            shutil.rmtree(entry, ignore_errors=True)


def bulk_models_dir() -> Path:
    """Directory holding the full PTM bulk-CMOS .lib library.

    Dev: transistor-models/assets/models/bulk_cmos in the repo.
    Frozen: bundled read-only copy (the .lib files are only read, never
    written, so no workspace sync is needed).
    """
    if is_frozen():
        base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
        for cand in (base / 'bulk_models',
                     Path(sys.executable).parent / '_internal' / 'bulk_models'):
            if cand.is_dir():
                return cand
    return (repo_root() / 'transistor-models' / 'assets' / 'models'
            / 'bulk_cmos')


def finfet_models_dir() -> Path:
    """Directory holding the PTM-MG FinFET modelcards + the OSDI model.

    Dev: transistor-models/assets/models/finfet in the repo.
    Frozen: bundled read-only copy (modelcards and the compiled .osdi are
    only read, never written).
    """
    if is_frozen():
        base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
        for cand in (base / 'finfet_models',
                     Path(sys.executable).parent / '_internal' / 'finfet_models'):
            if cand.is_dir():
                return cand
    return (repo_root() / 'transistor-models' / 'assets' / 'models' / 'finfet')


def finfet_osdi_path() -> Path | None:
    """Path to the platform-appropriate compiled bsimcmg.osdi, or None.

    FinFET simulation needs BSIM-CMG loaded into ngspice via OSDI; the .osdi
    is a per-platform compiled binary.  Returns the file for this OS/arch if
    it was shipped, else None (FinFET features then stay disabled).
    """
    import platform
    machine = platform.machine().lower()
    arch = 'amd64' if machine in ('x86_64', 'amd64') else machine
    plat = {'linux': 'linux', 'win32': 'windows', 'darwin': 'macos'}.get(
        sys.platform, sys.platform)
    cand = finfet_models_dir() / 'osdi' / f'{plat}_{arch}' / 'bsimcmg.osdi'
    return cand if cand.is_file() else None


def circuit_skills_dir() -> Path:
    """Root of the vendored analog-circuit-skills collection.

    Dev: circuit-skills/ in the repo.  Frozen: bundled read-only copy —
    the skills only *read* templates/models from their tree; all outputs
    go to the ANALOG_WORK_DIR set by init_runtime().
    """
    if is_frozen():
        base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
        for cand in (base / 'circuit_skills',
                     Path(sys.executable).parent / '_internal' / 'circuit_skills'):
            if cand.is_dir():
                return cand
    return repo_root() / 'circuit-skills'


def analoggym_dir() -> Path:
    """Root of the vendored AnalogGym subset (sizing benchmark assets).

    Dev: analoggym/ in the repo.  Frozen: bundled read-only copy — the
    netlists/testbenches are only read; rendered decks and outputs go to
    the workspace.
    """
    if is_frozen():
        base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
        for cand in (base / 'analoggym',
                     Path(sys.executable).parent / '_internal' / 'analoggym'):
            if cand.is_dir():
                return cand
    return repo_root() / 'analoggym'


def studio_circuits_dir() -> Path:
    """Root of the original (non-vendored) Analog Studio sizing circuits.

    Dev: studio_circuits/ in the repo.  Frozen: bundled read-only copy —
    same treatment as analoggym_dir(); the shared testbench + PDK still
    come from their own trees at render time.
    """
    if is_frozen():
        base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
        for cand in (base / 'studio_circuits',
                     Path(sys.executable).parent / '_internal'
                     / 'studio_circuits'):
            if cand.is_dir():
                return cand
    return repo_root() / 'studio_circuits'


def sky130_pdk_dir() -> Path:
    """SKY130 ngspice model root, extracted from the vendored zip on first
    use.  Lives *next to* the versioned workspace (it is version-independent
    and ~109 MB unpacked, so it survives app upgrades and workspace pruning).
    """
    return _workspace_root().parent.parent / 'sky130' / 'sky130_pdk'


def ensure_sky130() -> Path:
    """Extract analoggym/pdk/sky130_pdk.zip if not present yet (atomic)."""
    dst = sky130_pdk_dir().parent            # …/sky130
    if sky130_pdk_dir().is_dir():
        return sky130_pdk_dir()
    import zipfile
    zip_path = analoggym_dir() / 'pdk' / 'sky130_pdk.zip'
    tmp = dst.with_name(dst.name + '.tmp')
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    print('Extracting SKY130 PDK (first run, ~109 MB) ...')
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp)
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, dst)
    print('SKY130 PDK ready.')
    return sky130_pdk_dir()


def resources_dir() -> Path:
    """Location of app/resources (manual HTML + images).

    Dev: next to this file.  Frozen: bundled as data under 'app_resources'
    (PyInstaller: _internal/; Nuitka: next to the executable).
    """
    if is_frozen():
        base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
        for cand in (base / 'app_resources',
                     Path(sys.executable).parent / '_internal' / 'app_resources'):
            if cand.is_dir():
                return cand
    return Path(__file__).resolve().parent / 'resources'


def _trace(stage: str):
    """Optional startup tracing (set ANALOG_STUDIO_TRACE=1).

    Frozen builds run windowed; with Nuitka's --force-stderr-spec these
    lines land in AnalogStudio.err.txt, pinpointing the exact statement
    when startup dies without a Python traceback (e.g. a hard crash while
    an extension module loads).
    """
    if os.environ.get('ANALOG_STUDIO_TRACE'):
        print(f'init_runtime: {stage}', file=sys.stderr, flush=True)


def init_runtime():
    """Resolve asset roots, sync workspace if frozen, extend sys.path."""
    global _initialized, NGSPICE_ASSETS, GMOVERID_ASSETS, BROWSER_PLOTS
    if _initialized:
        return

    if is_frozen():
        _trace('frozen mode, locating bundle')
        bundle = _bundle_skill_dir()
        ws = _workspace_root()
        _trace(f'workspace {ws}')
        _prune_old_workspaces(ws)
        _trace('syncing skill trees')
        _sync_tree(bundle / 'ngspice_assets', ws / 'ngspice_assets')
        _sync_tree(bundle / 'gmoverid_assets', ws / 'gmoverid_assets')
        NGSPICE_ASSETS = ws / 'ngspice_assets'
        GMOVERID_ASSETS = ws / 'gmoverid_assets'
        BROWSER_PLOTS = ws / 'browser_plots'
    else:
        root = repo_root()
        NGSPICE_ASSETS = root / 'ngspice' / 'assets'
        GMOVERID_ASSETS = root / 'gmoverid' / 'assets'
        BROWSER_PLOTS = root / 'app_output' / 'browser_plots'

    BROWSER_PLOTS.mkdir(parents=True, exist_ok=True)

    # circuit-skills (comparator/LDO/OTA/opamp/bootstrap) route ALL their
    # outputs through this env var (read at their import time — set it before
    # any circuit module is imported); their own trees stay read-only.
    circuit_work = BROWSER_PLOTS.parent / 'circuit_work'
    circuit_work.mkdir(parents=True, exist_ok=True)
    os.environ['ANALOG_WORK_DIR'] = str(circuit_work)

    for p in (str(NGSPICE_ASSETS), str(GMOVERID_ASSETS)):
        if p not in sys.path:
            sys.path.insert(0, p)

    # Only the skill code uses scipy; import it here so PyInstaller's
    # analysis of app/ pulls it into the bundle (scipy.signal.medfilt is
    # used by plot_gmoverid's four-quadrant/comparison plots).
    _trace('importing scipy.stats')
    import scipy.stats   # noqa: F401
    _trace('importing scipy.signal')
    import scipy.signal  # noqa: F401
    _trace('done')

    _initialized = True

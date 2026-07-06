"""Runtime path setup for Analog Studio.

Resolves where the skill asset trees live (repo checkout vs frozen bundle),
makes sure they are importable, and exposes the writable output locations.

Frozen mode: PyInstaller bundles the two asset trees under ``skill/`` next to
the executable.  Because every skill module writes logs/plots/cache relative
to its own ``__file__``, the trees are synced once per app version into a
user-writable workspace and *that* copy is imported — no patching of skill
code is needed for the write paths to land somewhere writable.
"""

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
    """Copy src → dst once (skipped when dst already exists)."""
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns('__pycache__', 'logs', 'plots'))


def init_runtime():
    """Resolve asset roots, sync workspace if frozen, extend sys.path."""
    global _initialized, NGSPICE_ASSETS, GMOVERID_ASSETS, BROWSER_PLOTS
    if _initialized:
        return

    if is_frozen():
        bundle = _bundle_skill_dir()
        ws = _workspace_root()
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

    for p in (str(NGSPICE_ASSETS), str(GMOVERID_ASSETS)):
        if p not in sys.path:
            sys.path.insert(0, p)

    # Only the skill code uses scipy; import it here so PyInstaller's
    # analysis of app/ pulls it into the bundle.
    import scipy.stats  # noqa: F401

    _initialized = True

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Analog Studio (onedir, windowed).

Build:  pyinstaller app.spec
Result: dist/AnalogStudio/

The two skill asset trees are bundled as data under _internal/skill/ and
synced by app/paths.py into a writable per-user workspace on first launch,
so the frozen install directory is never written to at runtime.
"""

import sys
from pathlib import Path

REPO = Path(SPECPATH)

# strip and the GTK/EglFS pruning below are Linux-only: GNU `strip` corrupts
# Windows PE DLLs (the exe then hangs at startup), and the GTK widget stack /
# EglFS plugins simply don't exist in the Windows bundle.
IS_WINDOWS = sys.platform == 'win32'

EXCLUDE_DIRS = {'__pycache__', 'logs', 'plots'}


def collect_tree(src: Path, dest_prefix: str):
    out = []
    for p in src.rglob('*'):
        if not p.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(src).parts):
            continue
        if p.suffix in ('.pyc',):
            continue
        rel_parent = p.relative_to(src).parent
        out.append((str(p), str(Path(dest_prefix) / rel_parent)))
    return out


datas = (
    collect_tree(REPO / 'ngspice' / 'assets', 'skill/ngspice_assets')
    + collect_tree(REPO / 'gmoverid' / 'assets', 'skill/gmoverid_assets')
    + collect_tree(REPO / 'app' / 'resources', 'app_resources')
    # full PTM bulk-CMOS library for the extra registered nodes
    + collect_tree(REPO / 'transistor-models' / 'assets' / 'models'
                   / 'bulk_cmos', 'bulk_models')
    # PTM-MG FinFET modelcards + the BSIM-CMG OSDI model (per-platform .osdi)
    + collect_tree(REPO / 'transistor-models' / 'assets' / 'models'
                   / 'finfet', 'finfet_models')
    # vendored analog-circuit-skills (Circuits tab) — read-only at runtime,
    # outputs are routed through ANALOG_WORK_DIR
    + collect_tree(REPO / 'circuit-skills', 'circuit_skills')
    # vendored AnalogGym subset (Sizing tab): netlists/testbenches + PDK zip
    + collect_tree(REPO / 'analoggym', 'analoggym')
    # original (non-vendored) Analog Studio sizing circuits — same layout,
    # reuse the AnalogGym harness/PDK at render time
    + collect_tree(REPO / 'studio_circuits', 'studio_circuits')
)

a = Analysis(
    ['app/main.py'],
    pathex=[str(REPO)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'scipy.stats',
        'scipy.special',
        # skill code (loaded at runtime via sys.path, invisible to analysis)
        # uses scipy.signal.medfilt in plot_gmoverid's four-quadrant/comparison
        # gm*ro smoothing — must be forced in
        'scipy.signal',
        'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_agg',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter', 'PyQt5', 'PyQt6',
        # unused Qt modules — this is a QtWidgets-only app; the matplotlib
        # qtagg backend needs only QtCore/QtGui/QtWidgets
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D',
        'PySide6.QtQuickWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        'PySide6.QtNetwork', 'PySide6.QtDBus', 'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets', 'PySide6.QtVirtualKeyboard',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebChannel', 'PySide6.QtWebSockets', 'PySide6.QtSql',
        'PySide6.QtSensors', 'PySide6.QtPositioning', 'PySide6.QtBluetooth',
        'PySide6.QtNfc', 'PySide6.QtRemoteObjects', 'PySide6.QtScxml',
        # NOTE: PySide6.QtSvg must stay — matplotlib's qt_compat imports it
        'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtSvgWidgets', 'PySide6.QtTest', 'PySide6.QtXml',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
        # optuna is a source-only optional (requirements-dev.txt); the frozen
        # builds ship the built-in Sobol+Powell / DE optimizers and the GUI
        # hides the TPE option when optuna is absent.  Excluding it drops its
        # heavy dependency tree (SQLAlchemy, greenlet, alembic, Mako, ...).
        'optuna', 'sqlalchemy', 'greenlet', 'alembic', 'mako', 'colorlog',
    ],
    noarchive=False,
)

# Trim Qt payload the PySide6 hook copies wholesale:
#  - translation catalogs (~7 MB): no Qt-translated UI in this app
#  - shared libs of unused Qt modules (~25 MB): QtWidgets-only app; the
#    matplotlib qtagg backend needs only QtCore/QtGui/QtWidgets.  QtDBus is
#    kept (Linux platform plugins link it).  Substrings match both Linux
#    (libQt6Quick.so.6) and Windows (Qt6Quick.dll) names.
_QT_DROP = (
    'Qt6Quick', 'Qt6Qml', 'Qt6Pdf', 'Qt6Network', 'Qt6VirtualKeyboard',
    'Qt6Multimedia', 'Qt6WebEngine', 'Qt6WebChannel', 'Qt6WebSockets',
    'Qt6Sql', 'Qt6Sensors', 'Qt6Positioning', 'Qt6Bluetooth', 'Qt6Nfc',
    'Qt6RemoteObjects', 'Qt6Scxml', 'Qt6Charts', 'Qt6DataVisualization',
    'Qt63D', 'Qt6Test', 'Qt6Designer', 'Qt6Help', 'Qt6UiTools',
    'Qt6SerialPort', 'Qt6StateMachine', 'Qt6TextToSpeech',
    # EglFS is for embedded/kiosk (framebuffer) targets — never used on a
    # desktop; dropping it and its GTK platform-theme sibling lets the whole
    # GTK widget stack below be pruned
    'Qt6EglFSDeviceIntegration', 'Qt6EglFsKmsSupport',
)

# The GTK3 platform-theme plugin (libqgtk3) drags in the entire GTK widget
# toolkit (~12 MB on Linux) purely for native theming.  Without it Qt falls
# back to its Fusion style — fully functional.  These libs are pulled ONLY by
# libqgtk3; glib/gobject/gio/gthread are intentionally NOT here because Qt6's
# own Core/Gui/Widgets link libglib (verified via ldd) and must stay.
_GTKLIB_DROP = (
    'libgtk-3', 'libgdk-3', 'libgdk_pixbuf-2.0',
    'libpango-1.0', 'libpangocairo-1.0', 'libpangoft2-1.0', 'libcairo',
    'libcairo-gobject', 'libatk-1.0', 'libatk-bridge-2.0', 'libatspi',
    'libepoxy',
)


_DROP_PLUGIN_DIRS = ['/Qt/qml/', '/plugins/virtualkeyboard/',
                     '/plugins/multimedia/', '/plugins/position/',
                     '/plugins/sensors/', '/plugins/sqldrivers/',
                     '/plugins/tls/', '/plugins/networkinformation/']
if not IS_WINDOWS:
    # GTK platform-theme (libqgtk3) + EglFS plugins — Linux/embedded only
    _DROP_PLUGIN_DIRS += ['/plugins/platformthemes/',
                          '/plugins/egldeviceintegrations/']


def _keep(entry):
    name = entry[0].replace('\\', '/')
    if '/Qt/translations/' in name:
        return False
    base = name.rsplit('/', 1)[-1]
    if any(tag in base for tag in _QT_DROP):
        return False
    if not IS_WINDOWS and any(base.startswith(tag) for tag in _GTKLIB_DROP):
        return False
    for sub in _DROP_PLUGIN_DIRS:
        if sub in name:
            return False
    return True


a.datas = [d for d in a.datas if _keep(d)]
a.binaries = [b for b in a.binaries if _keep(b)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AnalogStudio',
    debug=False,
    strip=not IS_WINDOWS,   # ELF symbol strip on Linux; NEVER on Windows (GNU
    upx=False,              # strip corrupts PE DLLs → the exe hangs at startup)
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=not IS_WINDOWS,
    upx=False,
    name='AnalogStudio',
)

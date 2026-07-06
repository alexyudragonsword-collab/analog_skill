# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Analog Studio (onedir, windowed).

Build:  pyinstaller app.spec
Result: dist/AnalogStudio/

The two skill asset trees are bundled as data under _internal/skill/ and
synced by app/paths.py into a writable per-user workspace on first launch,
so the frozen install directory is never written to at runtime.
"""

from pathlib import Path

REPO = Path(SPECPATH)

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
)

a = Analysis(
    ['app/main.py'],
    pathex=[str(REPO)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'scipy.stats',
        'scipy.special',
        'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_agg',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt5', 'PyQt6'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AnalogStudio',
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='AnalogStudio',
)

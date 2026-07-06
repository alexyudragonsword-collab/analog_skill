"""ngspice detection for the GUI.

Never calls the skill's check_ngspice() — that one sys.exit()s when the
binary is missing.  Resolution order:

1. user-configured path from QSettings (prepended to PATH so all skill
   modules, which resolve via shutil.which, pick it up too)
2. a portable Spice64 install next to the frozen executable
3. ngspice_common.find_ngspice() (PATH + project-local portable install)

Each candidate is confirmed by actually running ``exe -v``.
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

SETTINGS_KEY = 'ngspice_path'


@dataclass
class NgspiceStatus:
    exe: str | None
    version: str | None

    @property
    def ok(self) -> bool:
        return self.exe is not None


def _probe(exe: str) -> str | None:
    """Return the version line if exe runs, else None."""
    try:
        kw = {}
        if sys.platform == 'win32':
            kw['creationflags'] = subprocess.CREATE_NO_WINDOW
        r = subprocess.run([exe, '-v'], capture_output=True, text=True,
                           timeout=10, stdin=subprocess.DEVNULL, **kw)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in (r.stdout or '').splitlines():
        if 'ngspice' in line.lower():
            return line.strip('* ').strip()
    return f'exit code {r.returncode}' if r.returncode == 0 else None


def _prepend_path(directory: str):
    if directory and directory not in os.environ.get('PATH', ''):
        os.environ['PATH'] = directory + os.pathsep + os.environ.get('PATH', '')


def set_user_path(exe_path: str):
    """Persist a user-chosen ngspice executable and activate it."""
    QSettings().setValue(SETTINGS_KEY, exe_path)
    _prepend_path(str(Path(exe_path).parent))


def locate() -> NgspiceStatus:
    # 1. user setting
    user = QSettings().value(SETTINGS_KEY, '')
    if user:
        _prepend_path(str(Path(str(user)).parent))
        ver = _probe(str(user))
        if ver:
            return NgspiceStatus(str(user), ver)

    # 2. portable install next to the frozen executable
    if getattr(sys, 'frozen', False):
        portable = Path(sys.executable).parent / 'ngspice' / 'Spice64' / 'bin'
        for name in ('ngspice_con.exe', 'ngspice.exe', 'ngspice'):
            cand = portable / name
            if cand.exists():
                ver = _probe(str(cand))
                if ver:
                    _prepend_path(str(portable))
                    return NgspiceStatus(str(cand), ver)

    # 3. skill's own finder (searches PATH, never exits)
    try:
        from ngspice_common import find_ngspice
        exe = find_ngspice()
    except ImportError:
        exe = 'ngspice'
    ver = _probe(exe)
    if ver:
        return NgspiceStatus(exe, ver)

    return NgspiceStatus(None, None)


INSTALL_HINT = (
    'ngspice was not found on this system.\n\n'
    '  Windows : download the ngspice zip from https://ngspice.sourceforge.io\n'
    '            and extract Spice64/ next to this application (or anywhere,\n'
    '            then set the path in Settings)\n'
    '  Linux   : sudo apt install ngspice\n'
    '  macOS   : brew install ngspice\n\n'
    'Simulations are disabled until ngspice is available; cached gm/ID\n'
    'tables can still be loaded.'
)

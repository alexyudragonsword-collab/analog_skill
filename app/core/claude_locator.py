"""Claude Code CLI detection for the subscription-backed LLM provider.

The same shape as ngspice_locator, and for the same reason: this is an
external program the app drives, not a library it bundles.  It cannot be
bundled — it is a Node CLI carrying the user's own login — so the frozen
builds detect it or do without it.

Resolution order:

1. user-configured path from QSettings
2. ``claude`` on PATH (shutil.which honours PATHEXT, so the Windows
   ``claude.cmd`` shim is found without special-casing)

`resolve()` is the cheap half — a PATH lookup, safe to call from a button
handler.  `locate()` is the half that actually runs the binary, which takes
a second or two and belongs in Settings ▸ Test.
"""

import shutil
import subprocess
import sys
from dataclasses import dataclass

from PySide6.QtCore import QSettings

SETTINGS_KEY = 'claude_code_path'

INSTALL_HINT = (
    'Claude Code not found. Install it (npm i -g @anthropic-ai/claude-code), '
    'run "claude" once to log in, then point Settings at it if it is not on '
    'PATH.')


@dataclass
class ClaudeStatus:
    exe: str | None
    version: str | None

    @property
    def ok(self) -> bool:
        return self.exe is not None


def _no_window() -> dict:
    """Keep a console window from flashing on every call.

    The frozen Windows builds are windowed (--windows-console-mode=disable),
    so a subprocess without this pops a black box in the user's face once
    per LLM call.
    """
    if sys.platform == 'win32':
        return {'creationflags': subprocess.CREATE_NO_WINDOW}
    return {}


def user_path() -> str:
    return str(QSettings().value(SETTINGS_KEY, '') or '').strip()


def set_user_path(path: str):
    s = QSettings()
    if path.strip():
        s.setValue(SETTINGS_KEY, path.strip())
    else:
        s.remove(SETTINGS_KEY)


def resolve() -> str | None:
    """The executable to use, without running it.  None if there is none."""
    configured = user_path()
    if configured:
        return configured
    return shutil.which('claude')


def _probe(exe: str) -> str | None:
    """Return the version string if `exe` answers --version, else None."""
    try:
        r = subprocess.run([exe, '--version'], capture_output=True, text=True,
                           timeout=30, stdin=subprocess.DEVNULL,
                           **_no_window())
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    # "2.1.270 (Claude Code)"
    line = (r.stdout or '').strip().splitlines()
    return line[0].strip() if line else None


def locate() -> ClaudeStatus:
    """Find the CLI and confirm it runs.  Costs a subprocess — do not call
    it from a paint or a hot path; `resolve()` answers "is it there?"."""
    exe = resolve()
    if not exe:
        return ClaudeStatus(None, None)
    version = _probe(exe)
    return ClaudeStatus(exe, version) if version else ClaudeStatus(None, None)

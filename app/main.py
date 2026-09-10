"""Analog Studio entry point.

Run with:  python -m app.main  [--smoke]

Two concerns beyond wiring the window up, both aimed at the same symptom —
a frozen build whose double-click appears to do nothing:

* the frozen builds run windowed (``--windows-console-mode=disable``), so an
  exception here reaches nobody unless we put it somewhere findable;
* the first launch unpacks the bundled assets (~100 MB for the onefile
  build) before any window exists, which reads exactly like a hang.
"""

import sys
from pathlib import Path


def _write_crash_file(exc_text: str) -> Path | None:
    """Drop the traceback somewhere the user can find and send.  Never
    raises — it runs when everything else already failed."""
    try:
        import tempfile
        import time
        from app import __version__
        path = Path(tempfile.gettempdir()) / 'AnalogStudio-crash.txt'
        path.write_text(
            f'Analog Studio {__version__} failed to start\n'
            f'{time.strftime("%Y-%m-%d %H:%M:%S")}\n'
            f'python     {sys.version}\n'
            f'executable {sys.executable}\n'
            f'argv       {sys.argv}\n\n{exc_text}',
            encoding='utf-8', errors='replace')
        return path
    except Exception:
        return None


def _interactive() -> bool:
    """Is there a human at a real display to read a modal dialog?

    A message box blocks until someone clicks OK, so raising one where
    nobody can is worse than useless: the CI smoke test would hang until the
    job timed out instead of failing fast with the traceback.  --smoke is
    non-interactive by definition, and the offscreen/minimal Qt platforms
    have no visible window to click.
    """
    import os
    if '--smoke' in sys.argv:
        return False
    return os.environ.get('QT_QPA_PLATFORM', '') not in ('offscreen',
                                                         'minimal')


def _report_fatal(exc_text: str):
    """Make a silent startup failure visible.  Never raises.

    The dialog is best-effort and deliberately does NOT create a
    QApplication of its own: if Qt is the thing that broke — a missing
    libEGL, a missing VC runtime, a bad DLL in the bundle — constructing one
    here would just fail again.  An existing instance is reused when there
    is one, otherwise Windows gets a native message box (which needs no Qt
    at all) and everyone else gets stderr, which the frozen builds already
    redirect to a file via --force-stderr-spec.

    *Both* dialogs sit behind _interactive(): each blocks until someone
    presses OK, and MessageBoxW blocks just as hard as QMessageBox.exec().
    Guarding only the Qt one left the Windows path open, and the Windows CI
    job then sat on this function for six hours until the runner's own
    limit killed it.
    """
    print(exc_text, file=sys.stderr, flush=True)
    crash = _write_crash_file(exc_text)
    last = exc_text.strip().splitlines()[-1] if exc_text.strip() else ''
    message = ('Analog Studio could not start.\n\n'
               f'{last}\n\n'
               + (f'Details were written to:\n{crash}\n\n'
                  'Please include that file if you report this.'
                  if crash else
                  'The details could not be written to a file.'))
    if not _interactive():
        return
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            box = QMessageBox(QMessageBox.Icon.Critical,
                              'Analog Studio', message)
            box.exec()
            return
    except Exception:
        pass
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(   # 0x10 = MB_ICONERROR
                None, message, 'Analog Studio', 0x10)
        except Exception:
            pass


def _start() -> int:
    # Import scipy before any Qt module: the Nuitka Windows build dies with
    # an access violation when scipy's extension modules load after Qt is
    # already up, while the reverse order is fine (paths.init_runtime keeps
    # its own scipy imports; they become no-ops here).  This is also why the
    # splash below cannot cover this import — there is no QApplication yet.
    import scipy.stats   # noqa: F401
    import scipy.signal  # noqa: F401

    from PySide6.QtWidgets import QApplication, QSplashScreen
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QPixmap

    app = QApplication(sys.argv)
    # No spaces: this name lands in the workspace path handed to ngspice
    app.setApplicationName('AnalogStudio')
    app.setOrganizationName('analog-studio')

    from app import paths

    icon_path = paths.resources_dir() / 'icons' / 'app_icon.png'
    splash = None
    if icon_path.is_file():
        pm = QPixmap(str(icon_path)).scaled(
            220, 220, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        splash = QSplashScreen(pm)
        splash.show()

    def stage(text: str):
        if splash is not None:
            splash.showMessage(text, Qt.AlignmentFlag.AlignHCenter
                               | Qt.AlignmentFlag.AlignBottom)
        app.processEvents()      # paint it before the blocking call below

    stage('Unpacking bundled assets (first run, one time only)…'
          if paths.first_run_expected() else 'Preparing workspace…')
    paths.init_runtime()

    from PySide6.QtGui import QIcon
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    stage('Loading device models…')
    from app.core.model_registry import (
        register_extra_models, register_finfet_models)
    register_extra_models()
    register_finfet_models()

    stage('Building the interface…')
    from app.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    if splash is not None:
        splash.finish(win)

    if '--smoke' in sys.argv:
        QTimer.singleShot(500, app.quit)

    return app.exec()


def main() -> int:
    try:
        return _start()
    except Exception:
        import traceback
        _report_fatal(traceback.format_exc())
        return 1


if __name__ == '__main__':
    sys.exit(main())

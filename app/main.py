"""Analog Studio entry point.

Run with:  python -m app.main  [--smoke]
"""

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer

    app = QApplication(sys.argv)
    # No spaces: this name lands in the workspace path handed to ngspice
    app.setApplicationName('AnalogStudio')
    app.setOrganizationName('analog-studio')

    from app import paths
    paths.init_runtime()

    from app.core.model_registry import register_extra_models
    register_extra_models()

    from app.ui.main_window import MainWindow
    win = MainWindow()
    win.show()

    if '--smoke' in sys.argv:
        QTimer.singleShot(500, app.quit)

    return app.exec()


if __name__ == '__main__':
    sys.exit(main())

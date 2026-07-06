"""Settings dialog — ngspice executable path."""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout,
)
from PySide6.QtCore import QSettings

from app.core import ngspice_locator


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.setMinimumWidth(480)

        self._path_edit = QLineEdit(
            str(QSettings().value(ngspice_locator.SETTINGS_KEY, '')))
        browse = QPushButton('Browse…')
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self._path_edit)
        row.addWidget(browse)

        self._status = QLabel('')
        self._status.setWordWrap(True)
        test = QPushButton('Test')
        test.clicked.connect(self._test)

        form = QFormLayout()
        form.addRow('ngspice executable', row)
        form.addRow('', test)
        form.addRow(self._status)

        hint = QLabel('Leave empty to auto-detect from PATH (or a '
                      'Spice64/ folder next to the app).')
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(buttons)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select ngspice executable')
        if path:
            self._path_edit.setText(path)

    def _test(self):
        path = self._path_edit.text().strip()
        if not path:
            st = ngspice_locator.locate()
            msg = (f'Auto-detected: {st.version}' if st.ok
                   else 'Not found via auto-detection.')
        else:
            ver = ngspice_locator._probe(path)
            msg = ver or 'Executable did not respond to -v.'
        self._status.setText(msg)

    def _accept(self):
        path = self._path_edit.text().strip()
        if path:
            ngspice_locator.set_user_path(path)
        else:
            QSettings().remove(ngspice_locator.SETTINGS_KEY)
        self.accept()

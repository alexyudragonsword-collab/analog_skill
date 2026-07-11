"""Settings dialog — ngspice executable path + optional LLM API access."""

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCursor

from app.core import llm_client, ngspice_locator


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.setMinimumWidth(520)

        # ── ngspice ────────────────────────────────────────────────────────
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

        ng_box = QGroupBox('ngspice')
        form = QFormLayout(ng_box)
        form.addRow('ngspice executable', row)
        form.addRow('', test)
        form.addRow(self._status)

        hint = QLabel('Leave empty to auto-detect from PATH (or a '
                      'Spice64/ folder next to the app).')
        hint.setWordWrap(True)

        # ── LLM (optional) ─────────────────────────────────────────────────
        cfg = llm_client.get_config()
        self._llm_provider = QComboBox()
        self._llm_provider.addItem('OpenAI-compatible (OpenAI / DeepSeek / '
                                   'Qwen / Ollama …)', userData='openai')
        self._llm_provider.addItem('Anthropic (Claude)', userData='anthropic')
        self._llm_provider.setCurrentIndex(
            1 if cfg['provider'] == 'anthropic' else 0)
        self._llm_base = QLineEdit(cfg['base_url'])
        self._llm_base.setPlaceholderText(
            'empty = provider default; e.g. https://api.deepseek.com/v1 '
            'or http://localhost:11434/v1')
        self._llm_key = QLineEdit(cfg['api_key'])
        self._llm_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_key.setPlaceholderText('optional for local endpoints '
                                         '(Ollama)')
        self._llm_model = QLineEdit(cfg['model'])
        self._llm_model.setPlaceholderText(
            'e.g. deepseek-chat / gpt-4o-mini / claude-sonnet-4-5')
        self._llm_status = QLabel('')
        self._llm_status.setWordWrap(True)
        llm_test = QPushButton('Test')
        llm_test.clicked.connect(self._test_llm)

        llm_box = QGroupBox('LLM for AI-assisted sizing (optional)')
        lf = QFormLayout(llm_box)
        lf.addRow('Provider', self._llm_provider)
        lf.addRow('Base URL', self._llm_base)
        lf.addRow('API key', self._llm_key)
        lf.addRow('Model', self._llm_model)
        lf.addRow('', llm_test)
        lf.addRow(self._llm_status)

        llm_hint = QLabel('Used by the Sizing tab (LLM-guided algorithm, '
                          'AI advise/explain).  Netlist excerpts and result '
                          'reports are sent to this endpoint.  Leave the '
                          'model empty to disable all AI features.')
        llm_hint.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(ng_box)
        lay.addWidget(hint)
        lay.addWidget(llm_box)
        lay.addWidget(llm_hint)
        lay.addWidget(buttons)

    # ── ngspice ────────────────────────────────────────────────────────────
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

    # ── LLM ────────────────────────────────────────────────────────────────
    def _llm_cfg(self) -> dict:
        return {'provider': self._llm_provider.currentData(),
                'base_url': self._llm_base.text().strip(),
                'api_key': self._llm_key.text().strip(),
                'model': self._llm_model.text().strip()}

    def _test_llm(self):
        cfg = self._llm_cfg()
        if not llm_client.configured(cfg):
            self._llm_status.setText('Set at least a model plus an API key '
                                     'or base URL.')
            return
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            msg = llm_client.test_connection(cfg)
        except llm_client.LLMError as exc:
            msg = f'<font color="red">{exc}</font>'
        finally:
            QApplication.restoreOverrideCursor()
        self._llm_status.setText(msg)

    def _accept(self):
        path = self._path_edit.text().strip()
        if path:
            ngspice_locator.set_user_path(path)
        else:
            QSettings().remove(ngspice_locator.SETTINGS_KEY)
        cfg = self._llm_cfg()
        llm_client.set_config(cfg['provider'], cfg['base_url'],
                              cfg['api_key'], cfg['model'])
        self.accept()

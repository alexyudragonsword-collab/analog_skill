"""Settings dialog — ngspice executable path + optional LLM API access."""

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCursor

from app.core import claude_locator, llm_client, ngspice_locator


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
        self._llm_provider.addItem('Claude Code CLI — uses your own login, '
                                   'no API key', userData='claude_code')
        idx = self._llm_provider.findData(cfg['provider'])
        self._llm_provider.setCurrentIndex(max(idx, 0))
        self._llm_provider.currentIndexChanged.connect(self._on_provider)
        self._llm_base = QLineEdit(cfg['base_url'])
        self._llm_base.setPlaceholderText(
            'empty = provider default; e.g. https://api.deepseek.com/v1 '
            'or http://localhost:11434/v1')
        self._llm_key = QLineEdit(cfg['api_key'])
        self._llm_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_key.setPlaceholderText('optional for local endpoints '
                                         '(Ollama)')
        # A key from the environment is shown but not editable: the field is
        # saved on OK, and saving this one would write to disk the very key
        # the user set in the environment to keep off it.
        self._key_from_env = bool(cfg.get('api_key_from_env'))
        if self._key_from_env:
            self._llm_key.setReadOnly(True)
            self._llm_key.setToolTip(
                f'Supplied by ${llm_client.ENV_API_KEY}; not saved to disk.')
        self._llm_model = QLineEdit(cfg['model'])
        self._llm_model.setPlaceholderText(
            'e.g. deepseek-chat / gpt-4o-mini / claude-sonnet-4-5')

        # Claude Code needs a binary rather than a key; same shape as the
        # ngspice row above, and empty means "find it on PATH".
        self._cc_path = QLineEdit(claude_locator.user_path())
        self._cc_path.setPlaceholderText(
            'empty = auto-detect "claude" on PATH')
        cc_browse = QPushButton('Browse…')
        cc_browse.clicked.connect(self._browse_claude)
        self._cc_row = QWidget()
        cc_row = QHBoxLayout(self._cc_row)
        cc_row.setContentsMargins(0, 0, 0, 0)
        cc_row.addWidget(self._cc_path)
        cc_row.addWidget(cc_browse)
        self._llm_status = QLabel('')
        self._llm_status.setWordWrap(True)
        llm_test = QPushButton('Test')
        llm_test.clicked.connect(self._test_llm)

        llm_box = QGroupBox('LLM for AI-assisted sizing (optional)')
        lf = QFormLayout(llm_box)
        lf.addRow('Provider', self._llm_provider)
        self._base_label = QLabel('Base URL')
        lf.addRow(self._base_label, self._llm_base)
        self._key_label = QLabel('API key')
        lf.addRow(self._key_label, self._llm_key)
        self._cc_label = QLabel('Claude Code')
        lf.addRow(self._cc_label, self._cc_row)
        lf.addRow('Model', self._llm_model)
        lf.addRow('', llm_test)
        lf.addRow(self._llm_status)
        self._on_provider()          # show the fields this provider uses

        llm_hint = QLabel(
            'Used by the Sizing tab (LLM-guided algorithm, AI '
            'advise/explain).  Netlist excerpts and result reports are sent '
            'to this endpoint.  Leave the model empty to disable all AI '
            'features.<br><b>The API key is saved in plain text</b> (registry '
            'on Windows, an ini file elsewhere).  On a machine you share, set '
            f'<code>{llm_client.ENV_API_KEY}</code> in the environment '
            'instead — it overrides this field and is never written to disk.'
            + (f'<br><i>Currently supplied by ${llm_client.ENV_API_KEY}.</i>'
               if cfg.get('api_key_from_env') else '')
            + '<br><b>Claude Code</b> spends your own subscription instead of '
              'an API key — it needs the CLI installed and logged in, and '
              'each call costs a few seconds more than a direct API request. '
              'It is driven with its tools switched off and your CLAUDE.md, '
              'hooks and MCP servers excluded.')
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
    def _on_provider(self, *_):
        """Show only the fields the selected provider actually uses.

        Hidden rather than merely disabled: a greyed-out API key box next
        to a provider that has no API key still invites someone to look
        for one.
        """
        cc = self._llm_provider.currentData() == 'claude_code'
        for widget in (self._llm_base, self._base_label,
                       self._llm_key, self._key_label):
            widget.setVisible(not cc)
        for widget in (self._cc_row, self._cc_label):
            widget.setVisible(cc)
        self._llm_model.setPlaceholderText(
            'sonnet / opus / haiku, or a full model id'
            if cc else 'e.g. deepseek-chat / gpt-4o-mini / claude-sonnet-4-5')

    def _browse_claude(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select the Claude Code executable')
        if path:
            self._cc_path.setText(path)

    def _llm_cfg(self) -> dict:
        return {'provider': self._llm_provider.currentData(),
                'base_url': self._llm_base.text().strip(),
                'api_key': self._llm_key.text().strip(),
                'model': self._llm_model.text().strip()}

    def _test_llm(self):
        cfg = self._llm_cfg()
        if cfg['provider'] == 'claude_code':
            # the path box is only saved on OK, so honour it here too —
            # otherwise Test answers about the old setting
            claude_locator.set_user_path(self._cc_path.text())
            st = claude_locator.locate()
            if not st.ok:
                self._llm_status.setText(
                    f'<font color="red">{claude_locator.INSTALL_HINT}</font>')
                return
            self._llm_status.setText(f'Found {st.version} — asking it…')
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
        claude_locator.set_user_path(self._cc_path.text())
        cfg = self._llm_cfg()
        llm_client.set_config(cfg['provider'], cfg['base_url'],
                              cfg['api_key'], cfg['model'],
                              store_api_key=not self._key_from_env)
        self.accept()

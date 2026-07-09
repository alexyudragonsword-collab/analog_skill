"""User manual viewer with a language switcher (中文 / English)."""

from PySide6.QtCore import QSettings, QLocale
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout,
)

from app import paths

LANGS = [
    ('zh', '中文', 'manual_zh.html'),
    ('en', 'English', 'manual_en.html'),
]
SETTINGS_KEY = 'manual_lang'


class ManualDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('User Manual / 用户手册')
        self.resize(960, 720)

        self._manual_dir = paths.resources_dir() / 'manual'

        self._lang_combo = QComboBox()
        for code, label, _file in LANGS:
            self._lang_combo.addItem(label, userData=code)
        top = QHBoxLayout()
        top.addWidget(QLabel('Language / 语言:'))
        top.addWidget(self._lang_combo)
        top.addStretch(1)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        # resolve relative img src against the manual directory (img/...)
        # and the resources root (schematics/...)
        self._browser.setSearchPaths([str(self._manual_dir),
                                      str(paths.resources_dir())])

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self._browser)

        # default language: last choice, else system locale
        saved = str(QSettings().value(SETTINGS_KEY, ''))
        if not saved:
            saved = 'zh' if QLocale.system().name().startswith('zh') else 'en'
        idx = next((i for i, (c, _l, _f) in enumerate(LANGS) if c == saved), 0)
        self._lang_combo.setCurrentIndex(idx)
        self._load(idx)
        self._lang_combo.currentIndexChanged.connect(self._on_lang)

    def _on_lang(self, idx: int):
        QSettings().setValue(SETTINGS_KEY, LANGS[idx][0])
        self._load(idx)

    def _load(self, idx: int):
        path = self._manual_dir / LANGS[idx][2]
        if path.exists():
            self._browser.setHtml(path.read_text(encoding='utf-8'))
        else:
            self._browser.setHtml(
                f'<h2>Manual file missing</h2><p>{path}</p>')

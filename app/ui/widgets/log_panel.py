"""Shared log console fed by SimWorker.log_line."""

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit

MAX_BLOCKS = 5000


class LogPanel(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(MAX_BLOCKS)
        font = QFont('Monospace')
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.setFont(font)

    def append_line(self, line: str):
        self.appendPlainText(line)
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

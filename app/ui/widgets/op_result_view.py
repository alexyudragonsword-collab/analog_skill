"""Formatted display of a GmIdTable.size() operating-point dict."""

from PySide6.QtWidgets import (
    QApplication, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QHeaderView,
)

_ROWS = [
    # (dict key, label, formatter)
    ('model',    'Model',        lambda v: str(v)),
    ('L_um',     'L',            lambda v: f'{v * 1e3:.0f} nm'),
    ('W_um',     'W',            lambda v: f'{v:.2f} um'),
    ('gmid',     'gm/ID',        lambda v: f'{v:.1f} V^-1'),
    ('Id_A',     'Id',           lambda v: f'{v * 1e6:.2f} uA'),
    ('gm_S',     'gm',           lambda v: f'{v * 1e3:.3f} mS'),
    ('Vgs_V',    'Vgs',          lambda v: f'{v:.3f} V'),
    ('Vov_V',    'Vov',          lambda v: f'{v:.3f} V'),
    ('ft_Hz',    'fT',           lambda v: f'{v / 1e9:.2f} GHz'),
    ('gmro',     'gm*ro',        lambda v: f'{v:.1f}'),
    ('id_w_Apm', 'Id/W',         lambda v: f'{v:.2f} uA/um'),
]

# FinFET: width knob is NFIN (integer); id_w is per effective width
_ROWS_FINFET = [
    ('model',    'Model',        lambda v: str(v)),
    ('L_um',     'L',            lambda v: f'{v * 1e3:.0f} nm'),
    ('NFIN',     'NFIN',         lambda v: f'{int(v)} fins'),
    ('Weff_um',  'Weff',         lambda v: f'{v:.3f} um'),
    ('gmid',     'gm/ID',        lambda v: f'{v:.1f} V^-1'),
    ('Id_A',     'Id',           lambda v: f'{v * 1e6:.2f} uA'),
    ('gm_S',     'gm',           lambda v: f'{v * 1e3:.3f} mS'),
    ('Vgs_V',    'Vgs',          lambda v: f'{v:.3f} V'),
    ('Vov_V',    'Vov',          lambda v: f'{v:.3f} V'),
    ('ft_Hz',    'fT',           lambda v: f'{v / 1e9:.2f} GHz'),
    ('gmro',     'gm*ro',        lambda v: f'{v:.1f}'),
    ('id_w_Apm', 'Id/Weff',      lambda v: f'{v:.2f} uA/um'),
]


class OpResultView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._table = QTableWidget(len(_ROWS), 2)
        self._table.setHorizontalHeaderLabels(['Parameter', 'Value'])
        self._table.verticalHeader().hide()
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)

        self._copy_btn = QPushButton('Copy as text')
        self._copy_btn.clicked.connect(self._copy)
        self._copy_btn.setEnabled(False)
        self._text = ''

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._table)
        lay.addWidget(self._copy_btn)
        self.clear()

    def clear(self):
        for i, (_, label, _f) in enumerate(_ROWS):
            self._table.setItem(i, 0, QTableWidgetItem(label))
            self._table.setItem(i, 1, QTableWidgetItem('—'))
        self._text = ''
        self._copy_btn.setEnabled(False)

    def show_op(self, op: dict):
        rows = _ROWS_FINFET if op.get('kind') == 'finfet' else _ROWS
        self._table.setRowCount(len(rows))
        lines = ['Transistor Operating Point', '-' * 34]
        for i, (key, label, fmt) in enumerate(rows):
            val = fmt(op[key]) if key in op else '—'
            self._table.setItem(i, 0, QTableWidgetItem(label))
            self._table.setItem(i, 1, QTableWidgetItem(val))
            lines.append(f'{label:<10s}: {val}')
        self._text = '\n'.join(lines)
        self._copy_btn.setEnabled(True)

    def _copy(self):
        if self._text:
            QApplication.clipboard().setText(self._text)

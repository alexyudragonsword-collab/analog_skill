"""Tab (b): run the nine ngspice teaching examples."""

import importlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QSpinBox, QSplitter,
    QVBoxLayout, QWidget,
)

from app.core.examples import REGISTRY, run_example, example_log_dir
from app.core.worker import Job, SimWorker
from app.ui.widgets.png_viewer import PngViewer


class ExamplesTab(QWidget):
    def __init__(self, worker: SimWorker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self._pending_job: str | None = None
        self._fields: dict[str, QWidget] = {}
        self._spec = None

        # left: example list + parameter form
        self._list = QListWidget()
        for spec in REGISTRY.values():
            item = QListWidgetItem(spec.title)
            item.setData(Qt.ItemDataRole.UserRole, spec.key)
            item.setToolTip(spec.description)
            self._list.addItem(item)
        self._list.currentItemChanged.connect(self._on_select)

        self._desc = QLabel('')
        self._desc.setWordWrap(True)

        self._form_box = QGroupBox('Parameters')
        self._form = QFormLayout(self._form_box)

        self._reset_btn = QPushButton('Reset defaults')
        self._reset_btn.clicked.connect(self._build_form)
        self.run_btn = QPushButton('Run simulation')
        self.run_btn.clicked.connect(self._run)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._reset_btn)
        btn_row.addWidget(self.run_btn)

        self._status = QLabel('')
        self._status.setWordWrap(True)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.addWidget(self._list, stretch=2)
        left_lay.addWidget(self._desc)
        left_lay.addWidget(self._form_box, stretch=1)
        left_lay.addLayout(btn_row)
        left_lay.addWidget(self._status)

        # right: plot viewer
        self._viewer = PngViewer()

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self._viewer)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)

        lay = QHBoxLayout(self)
        lay.addWidget(split)

        worker.job_finished.connect(self._on_finished)
        worker.job_failed.connect(self._on_failed)
        self._list.setCurrentRow(0)

    # ── form handling ─────────────────────────────────────────────────────
    def _on_select(self, current, _prev=None):
        if current is None:
            return
        self._spec = REGISTRY[current.data(Qt.ItemDataRole.UserRole)]
        self._desc.setText(self._spec.description)
        self._build_form()

    def _build_form(self):
        while self._form.rowCount():
            self._form.removeRow(0)
        self._fields.clear()
        if self._spec is None:
            return
        module = importlib.import_module(self._spec.sim_module)
        for p in self._spec.params:
            default = p.resolve_default(module)
            if p.kind == 'float':
                w = QDoubleSpinBox()
                w.setRange(p.minimum, p.maximum)
                w.setDecimals(p.decimals)
                w.setValue(float(default))
            elif p.kind == 'int':
                w = QSpinBox()
                w.setRange(int(p.minimum), int(p.maximum))
                w.setValue(int(default))
            else:   # floatlist
                w = QLineEdit(', '.join(f'{v:g}' for v in default))
            label = f'{p.label} [{p.unit}]' if p.unit else p.label
            self._form.addRow(label, w)
            self._fields[p.key] = w

    def _collect_values(self) -> dict | None:
        values = {}
        for p in self._spec.params:
            w = self._fields[p.key]
            if p.kind == 'float':
                values[p.key] = w.value()
            elif p.kind == 'int':
                values[p.key] = w.value()
            else:
                try:
                    values[p.key] = [float(t) for t in
                                     w.text().replace(',', ' ').split()]
                except ValueError:
                    self._status.setText(
                        f'<font color="red">Invalid number list for '
                        f'{p.label}</font>')
                    return None
                if not values[p.key]:
                    self._status.setText(
                        f'<font color="red">{p.label} must not be '
                        f'empty</font>')
                    return None
        return values

    # ── run / results ─────────────────────────────────────────────────────
    def _run(self):
        if self._spec is None or self._pending_job:
            return
        values = self._collect_values()
        if values is None:
            return
        key = self._spec.key
        job = Job(
            kind='example',
            fn=lambda: run_example(key, values),
            label=f'example: {key}',
            log_dir=example_log_dir(),
        )
        self._pending_job = self._worker.submit(job)
        self.run_btn.setEnabled(False)
        self._status.setText(f'Running {key} …')

    def _on_finished(self, job_id, result):
        if job_id != self._pending_job:
            return
        self._pending_job = None
        self.run_btn.setEnabled(True)
        self._status.setText('Done.')
        self._viewer.show_pngs(result)

    def _on_failed(self, job_id, err):
        if job_id != self._pending_job:
            return
        self._pending_job = None
        self.run_btn.setEnabled(True)
        first = err.strip().splitlines()[-1] if err.strip() else 'failed'
        self._status.setText(
            f'<font color="red">Failed: {first} (see log panel)</font>')

    def set_sim_enabled(self, enabled: bool):
        self.run_btn.setEnabled(enabled and not self._pending_job)

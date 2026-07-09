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
from app.ui.job_mixin import JobTabMixin, fail_text
from app.ui.layout_util import scroll_wrap
from app.ui.widgets.png_viewer import PngViewer


class ExamplesTab(QWidget, JobTabMixin):
    def __init__(self, worker: SimWorker, parent=None):
        super().__init__(parent)
        self.init_job_runner(worker)
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
        box_lay = QVBoxLayout(self._form_box)
        self._form = QFormLayout()            # basic params
        box_lay.addLayout(self._form)
        self._adv_box = QGroupBox('Advanced parameters')
        self._adv_box.setCheckable(True)
        self._adv_box.setChecked(False)       # collapsed by default
        self._adv_form = QFormLayout(self._adv_box)
        self._adv_box.toggled.connect(self._adv_form_container_toggle)
        box_lay.addWidget(self._adv_box)

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
        split.addWidget(scroll_wrap(left))
        split.addWidget(self._viewer)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)

        lay = QHBoxLayout(self)
        lay.addWidget(split)

        self._list.setCurrentRow(0)

    # ── form handling ─────────────────────────────────────────────────────
    def _on_select(self, current, _prev=None):
        if current is None:
            return
        self._spec = REGISTRY[current.data(Qt.ItemDataRole.UserRole)]
        self._desc.setText(self._spec.description)
        self._build_form()

    def _adv_form_container_toggle(self, on: bool):
        # checkable groupbox hides its child widgets when unchecked
        for i in range(self._adv_form.count()):
            item = self._adv_form.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(on)

    def _make_field(self, p, module):
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
        return w

    def _build_form(self):
        for form in (self._form, self._adv_form):
            while form.rowCount():
                form.removeRow(0)
        self._fields.clear()
        if self._spec is None:
            return
        module = importlib.import_module(self._spec.sim_module)
        has_adv = False
        for p in self._spec.params:
            w = self._make_field(p, module)
            label = f'{p.label} [{p.unit}]' if p.unit else p.label
            (self._adv_form if p.advanced else self._form).addRow(label, w)
            self._fields[p.key] = w
            has_adv = has_adv or p.advanced
        self._adv_box.setVisible(has_adv)
        self._adv_form_container_toggle(self._adv_box.isChecked())

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
        if self._spec is None or self.has_job('run'):
            return
        values = self._collect_values()
        if values is None:
            return
        key = self._spec.key
        self.submit_job('run', Job(
            kind='example',
            fn=lambda: run_example(key, values),
            label=f'example: {key}',
            log_dir=example_log_dir(),
        ))
        self.run_btn.setEnabled(False)
        self._status.setText(f'Running {key} …')

    def on_job_finished(self, slot, render):
        # render closure executes on the GUI thread (matplotlib single-thread)
        self.run_btn.setEnabled(True)
        try:
            pngs = render()
        except Exception as exc:
            self._status.setText(f'<font color="red">Plot failed: {exc}</font>')
            return
        self._status.setText('Done.')
        self._viewer.show_pngs(pngs)

    def on_job_failed(self, slot, err):
        self.run_btn.setEnabled(True)
        self._status.setText(fail_text(err))

    def set_sim_enabled(self, enabled: bool):
        self.run_btn.setEnabled(enabled and not self.has_job('run'))

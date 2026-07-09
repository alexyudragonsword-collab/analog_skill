"""Tab: block-level circuit simulations (vendored analog-circuit-skills).

Five circuits (StrongArm comparator, LDO, bootstrapped switch, 5T OTA,
two-stage op amp) with per-circuit analyses and editable parameters.  The
worker runs the ngspice sweeps; the returned closure renders all plots on
the GUI thread and yields (png_paths, report_text).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from app.core import circuits, gmid_service
from app.core.worker import Job, SimWorker
from app.ui.job_mixin import JobTabMixin, fail_text
from app.ui.layout_util import scroll_wrap
from app.ui.widgets.png_viewer import PngViewer


class CircuitsTab(QWidget, JobTabMixin):
    def __init__(self, worker: SimWorker, parent=None):
        super().__init__(parent)
        self.init_job_runner(worker)
        self._fields: dict[str, QDoubleSpinBox] = {}

        self.circuit_combo = QComboBox()
        for key, spec in circuits.CIRCUITS.items():
            self.circuit_combo.addItem(spec.title, userData=key)
        self.circuit_combo.currentIndexChanged.connect(self._on_circuit)

        self.analysis_combo = QComboBox()
        self.analysis_combo.currentIndexChanged.connect(self._on_analysis)

        # parameter forms (rebuilt per circuit/analysis)
        self._form_box = QGroupBox('Parameters')
        box_lay = QVBoxLayout(self._form_box)
        self._form = QFormLayout()
        box_lay.addLayout(self._form)
        self._adv_box = QGroupBox('Advanced parameters')
        self._adv_box.setCheckable(True)
        self._adv_box.setChecked(False)
        self._adv_form = QFormLayout(self._adv_box)
        self._adv_box.toggled.connect(self._toggle_adv)
        box_lay.addWidget(self._adv_box)

        self.run_btn = QPushButton('Run simulation')
        self.run_btn.clicked.connect(self._run)

        self._status = QLabel('')
        self._status.setWordWrap(True)

        self._report = QPlainTextEdit()
        self._report.setReadOnly(True)
        self._report.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._report.setPlaceholderText('Metrics report appears here.')

        sel_box = QGroupBox('Circuit')
        sf = QFormLayout(sel_box)
        sf.addRow('Circuit', self.circuit_combo)
        sf.addRow('Analysis', self.analysis_combo)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(sel_box)
        ll.addWidget(self._form_box)
        ll.addWidget(self.run_btn)
        ll.addWidget(self._status)
        ll.addWidget(QLabel('Report:'))
        ll.addWidget(self._report, stretch=1)

        self._viewer = PngViewer()

        split = QSplitter()
        split.addWidget(scroll_wrap(left))
        split.addWidget(self._viewer)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        lay = QHBoxLayout(self)
        lay.addWidget(split)

        self._on_circuit()

    # ── selection / forms ─────────────────────────────────────────────────
    def _spec(self) -> circuits.CircuitSpec:
        return circuits.CIRCUITS[self.circuit_combo.currentData()]

    def _current_params(self) -> list:
        ana = self._spec().analyses.get(self.analysis_combo.currentData())
        if ana is not None and ana.params is not None:
            return ana.params
        return self._spec().params

    def _on_circuit(self, *_):
        spec = self._spec()
        self.analysis_combo.blockSignals(True)
        self.analysis_combo.clear()
        for key, ana in spec.analyses.items():
            self.analysis_combo.addItem(ana.label, userData=key)
        self.analysis_combo.blockSignals(False)
        self._build_form()
        # show the pre-rendered schematic immediately on selection
        sch = circuits.schematic_path(self.circuit_combo.currentData())
        if sch is not None:
            self._viewer.show_pngs([sch])

    def _on_analysis(self, *_):
        self._build_form()

    def _toggle_adv(self, on):
        for i in range(self._adv_form.count()):
            w = self._adv_form.itemAt(i).widget()
            if w is not None:
                w.setVisible(on)

    def _build_form(self):
        for form in (self._form, self._adv_form):
            while form.count():
                item = form.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        self._fields.clear()
        for p in self._current_params():
            spin = QDoubleSpinBox()
            spin.setRange(p.minv, p.maxv)
            spin.setDecimals(0 if p.kind == 'int' else p.decimals)
            spin.setValue(p.default)
            if p.unit:
                spin.setSuffix(f' {p.unit}')
            form = self._adv_form if p.advanced else self._form
            form.addRow(p.label, spin)
            self._fields[p.attr] = spin
        self._toggle_adv(self._adv_box.isChecked())

    # ── run ───────────────────────────────────────────────────────────────
    def _run(self):
        if self.has_job('run'):
            return
        circuit = self.circuit_combo.currentData()
        analysis = self.analysis_combo.currentData()
        values = {attr: spin.value() for attr, spin in self._fields.items()}
        ana = self._spec().analyses[analysis]
        self.submit_job('run', Job(
            kind='circuit',
            fn=lambda: circuits.run_circuit(circuit, analysis, values),
            label=f'circuit: {circuit}/{analysis}',
            log_dir=gmid_service.gmid_log_dir(),
        ))
        self.run_btn.setEnabled(False)
        note = f' — {ana.note}' if ana.note else ''
        self._status.setText(f'Running {analysis} …{note}')

    def on_job_finished(self, slot, result):
        # render closure executes here on the GUI thread (matplotlib policy)
        self.run_btn.setEnabled(True)
        try:
            pngs, report = result.render()
        except Exception as exc:
            self._status.setText(f'<font color="red">Plot failed: {exc}</font>')
            return
        self._status.setText('Done.')
        self._report.setPlainText(report)
        if pngs:
            # keep the schematic first in the thumbnail strip, but focus the
            # first fresh result
            sch = circuits.schematic_path(self.circuit_combo.currentData())
            if sch is not None:
                self._viewer.show_pngs([sch] + pngs, current=1)
            else:
                self._viewer.show_pngs(pngs)

    def on_job_failed(self, slot, err):
        self.run_btn.setEnabled(True)
        self._status.setText(fail_text(err))

    def set_sim_enabled(self, enabled: bool):
        self.run_btn.setEnabled(enabled and not self.has_job('run'))

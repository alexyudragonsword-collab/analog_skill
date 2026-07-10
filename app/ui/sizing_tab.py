"""Tab: sizing optimization over the vendored AnalogGym circuits.

Pick a SKY130 topology, edit the design-variable bounds, set an evaluation
budget and run: the worker executes the evaluate→score→Powell loop
(cancellable between evaluations); the GUI shows live progress in the log
panel and, on completion, the convergence curve plus the best metrics and
sizing (exportable as a .PARAM file).
"""

import threading

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.core import sizing
from app.core.worker import Job, SimWorker
from app.ui.job_mixin import JobTabMixin, fail_text
from app.ui.layout_util import scroll_wrap
from app.ui.widgets.png_viewer import PngViewer


class SizingTab(QWidget, JobTabMixin):
    def __init__(self, worker: SimWorker, parent=None):
        super().__init__(parent)
        self.init_job_runner(worker)
        self._cancel = threading.Event()
        self._last_run: sizing.SizingRun | None = None

        self.circuit_combo = QComboBox()
        for key, spec in sizing.SIZING.items():
            self.circuit_combo.addItem(spec.title, userData=key)
        self.circuit_combo.currentIndexChanged.connect(self._on_circuit)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(['variable', 'init', 'lo', 'hi'])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)

        self._targets = QTableWidget(0, 3)
        self._targets.setHorizontalHeaderLabels(['metric', 'target', 'hard'])
        self._targets.horizontalHeader().setStretchLastSection(True)
        self._targets.verticalHeader().setVisible(False)
        self._targets.setMaximumHeight(220)

        self.algo_combo = QComboBox()
        self.algo_combo.addItem('Sobol + Powell (built-in)',
                                userData='sobol_powell')
        if sizing.optuna_available():
            self.algo_combo.addItem('Optuna TPE', userData='optuna')

        self.budget_spin = QSpinBox()
        self.budget_spin.setRange(10, 2000)
        self.budget_spin.setValue(150)
        self.budget_spin.valueChanged.connect(self._update_estimate)
        self._estimate = QLabel('')

        self.run_btn = QPushButton('Optimize')
        self.run_btn.clicked.connect(self._run)
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel.set)
        self.export_btn = QPushButton('Export best .PARAM…')
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)

        self._status = QLabel('')
        self._status.setWordWrap(True)

        self._report = QPlainTextEdit()
        self._report.setReadOnly(True)
        self._report.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._report.setPlaceholderText(
            'Best metrics / sizing appear here after a run.')

        sel_box = QGroupBox('Circuit (AnalogGym, SKY130)')
        sf = QFormLayout(sel_box)
        sf.addRow('Circuit', self.circuit_combo)
        sf.addRow('Algorithm', self.algo_combo)
        sf.addRow('Budget (evals)', self.budget_spin)
        sf.addRow('', self._estimate)

        tgt_box = QGroupBox('Targets (editable; hard = 10x weight)')
        tb = QVBoxLayout(tgt_box)
        tb.addWidget(self._targets)

        var_box = QGroupBox('Design variables (bounds editable)')
        vb = QVBoxLayout(var_box)
        vb.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.export_btn)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(sel_box)
        ll.addWidget(tgt_box)
        ll.addWidget(var_box, stretch=1)
        ll.addLayout(btn_row)
        ll.addWidget(self._status)
        ll.addWidget(QLabel('Result:'))
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

    # ── selection ─────────────────────────────────────────────────────────
    def _key(self) -> str:
        return self.circuit_combo.currentData()

    def _on_circuit(self, *_):
        variables = sizing.parse_variables(self._key())
        self._table.setRowCount(len(variables))
        for row, v in enumerate(variables):
            name_item = QTableWidgetItem(v.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, name_item)
            for col, val in ((1, v.default), (2, v.lo), (3, v.hi)):
                self._table.setItem(row, col, QTableWidgetItem(f'{val:g}'))
        self._table.resizeColumnsToContents()
        metrics = sizing.SIZING[self._key()].metrics
        self._targets.setRowCount(len(metrics))
        for row, ms in enumerate(metrics):
            lbl = QTableWidgetItem(f'{ms.label} [{ms.unit}] ({ms.direction})')
            lbl.setFlags(lbl.flags() & ~Qt.ItemFlag.ItemIsEditable)
            lbl.setData(Qt.ItemDataRole.UserRole, ms.key)
            self._targets.setItem(row, 0, lbl)
            self._targets.setItem(row, 1, QTableWidgetItem(f'{ms.target:g}'))
            hard = QTableWidgetItem()
            hard.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                          | Qt.ItemFlag.ItemIsEnabled)
            hard.setCheckState(Qt.CheckState.Checked if ms.hard
                               else Qt.CheckState.Unchecked)
            self._targets.setItem(row, 2, hard)
        self._targets.resizeColumnsToContents()
        self._update_estimate()
        sch = sizing.schematic_path(self._key())
        if sch is not None:
            self._viewer.show_pngs([sch])

    def _update_estimate(self, *_):
        secs = sizing.SIZING[self._key()].eval_seconds * self.budget_spin.value()
        self._estimate.setText(f'≈ {secs / 60:.0f} min estimated')

    def _read_table(self) -> list:
        variables = []
        base = {v.name: v for v in sizing.parse_variables(self._key())}
        for row in range(self._table.rowCount()):
            name = self._table.item(row, 0).text()
            try:
                init = float(self._table.item(row, 1).text())
                lo = float(self._table.item(row, 2).text())
                hi = float(self._table.item(row, 3).text())
            except (TypeError, ValueError):
                raise ValueError(f'row {row + 1} ({name}): not a number')
            if not (lo <= init <= hi):
                raise ValueError(f'{name}: need lo <= init <= hi')
            variables.append(sizing.VarSpec(
                name, init, lo, hi, base[name].is_int if name in base
                else False))
        return variables

    def _read_targets(self) -> dict:
        overrides = {}
        for row in range(self._targets.rowCount()):
            key = self._targets.item(row, 0).data(Qt.ItemDataRole.UserRole)
            try:
                target = float(self._targets.item(row, 1).text())
            except (TypeError, ValueError):
                raise ValueError(f'target row {row + 1}: not a number')
            hard = (self._targets.item(row, 2).checkState()
                    == Qt.CheckState.Checked)
            overrides[key] = (target, hard)
        return overrides

    # ── run / cancel ──────────────────────────────────────────────────────
    def _run(self):
        if self.has_job('opt'):
            return
        try:
            variables = self._read_table()
            overrides = self._read_targets()
        except ValueError as exc:
            self._status.setText(f'<font color="red">{exc}</font>')
            return
        key = self._key()
        budget = self.budget_spin.value()
        algo = self.algo_combo.currentData()
        self._cancel.clear()

        def job():
            def progress(n, best, _metrics):
                if n % 5 == 0 or n == 1:
                    print(f'sizing {key}: eval {n}/{budget}  '
                          f'best cost {best:.4f}')
            return sizing.optimize(key, variables, budget=budget,
                                   progress=progress,
                                   should_cancel=self._cancel.is_set,
                                   overrides=overrides, algo=algo)

        self.submit_job('opt', Job(kind='sizing', fn=job,
                                   label=f'sizing: {key} ({budget} evals)'))
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._status.setText(f'Optimizing ({budget} evaluations)… '
                             'progress in the log panel below.')

    def on_job_finished(self, slot, run: sizing.SizingRun):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._last_run = run
        self.export_btn.setEnabled(True)
        note = ' (cancelled — best-so-far kept)' if run.cancelled else ''
        self._status.setText(
            f'Done{note}: cost {run.initial_cost:.3f} → {run.best_cost:.3f} '
            f'in {run.evals} evaluations.')
        self._report.setPlainText(run.report())
        try:
            png = sizing.render_convergence(run)   # GUI thread (mpl policy)
        except Exception as exc:
            self._status.setText(f'<font color="red">Plot failed: {exc}</font>')
            return
        pngs = [png]
        sch = sizing.schematic_path(run.circuit)
        if sch is not None:
            pngs.insert(0, sch)
        self._viewer.show_pngs(pngs, current=len(pngs) - 1)

    def on_job_failed(self, slot, err):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._status.setText(fail_text(err))

    def _export(self):
        if self._last_run is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export best sizing', f'{self._last_run.circuit}_best.spice',
            'SPICE param files (*.spice);;All files (*)')
        if path:
            with open(path, 'w') as f:
                f.write(self._last_run.params_text())
            self._status.setText(f'Exported to {path}')

    def set_sim_enabled(self, enabled: bool):
        self.run_btn.setEnabled(enabled and not self.has_job('opt'))

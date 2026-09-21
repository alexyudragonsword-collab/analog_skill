"""Tab: sizing optimization over the vendored AnalogGym circuits.

Pick a SKY130 topology, edit the design-variable bounds, set an evaluation
budget and run: the worker executes the evaluate→score→Powell loop
(cancellable between evaluations); the GUI shows live progress in the log
panel and, on completion, the convergence curve plus the best metrics and
sizing (exportable as a .PARAM file).
"""

import math
import threading

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from app.core import llm_client, sizing
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
        self._last_pngs: list = []
        self._pending_import: str | None = None

        sizing.load_user_circuits()          # re-register workspace imports
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
        self._targets.itemChanged.connect(lambda *_: self._refresh_known())
        self._targets.horizontalHeader().setStretchLastSection(True)
        self._targets.verticalHeader().setVisible(False)
        self._targets.setMaximumHeight(220)

        self.algo_combo = QComboBox()
        if sizing.cmaes_available():
            self.algo_combo.addItem('CMA-ES with restarts (pycma)',
                                    userData='cmaes')
            self.algo_combo.addItem('CMA-ES + AI finish (CMA-ES searches, '
                                    'AI names the fix, line search lands it)',
                                    userData='cmaes_llm_finish')
            self.algo_combo.addItem('CMA-ES + surrogate (lq-CMA-ES: a '
                                    'quadratic model ranks the population; '
                                    'pilot)', userData='cmaes_surrogate')
        self.algo_combo.addItem('Sobol + Powell (built-in)',
                                userData='sobol_powell')
        self.algo_combo.addItem('Differential evolution (global, '
                                'large budgets)', userData='diff_evolution')
        self.algo_combo.addItem('DE + AI finish (DE searches, AI names '
                                'the fix, line search lands it)',
                                userData='de_llm_finish')
        self.algo_combo.addItem('DE + Powell polish (local finish, no AI)',
                                userData='de_powell')
        self.algo_combo.addItem('DE, constrained (targets as constraints, '
                                'then widen the margins)',
                                userData='de_constrained')
        if sizing.optuna_available():
            self.algo_combo.addItem('Optuna TPE', userData='optuna')
        self.algo_combo.addItem('LLM-guided (AI — configure in Settings)',
                                userData='llm')
        self.algo_combo.addItem('LLM agent (AI drives, Claude Code only)',
                                userData='llm_agent')
        # the amortised surrogate: characterise once (Sobol over the whole
        # box, hours are fine), then metric models trained on the archive
        # propose candidates for any new targets in seconds and `budget`
        # of them are verified; start the next search from the best
        self.algo_combo.addItem('Characterise: Sobol sample of the whole '
                                'box (no search; feeds the metric models)',
                                userData='sobol')
        if sizing.models_available():
            self.algo_combo.addItem('Model proposals: metric models on the '
                                    'archive pick `budget` points, verified '
                                    'here', userData='model_propose')
        # the default is the measured winner — CMA-ES, feasible on 12 of
        # 18 circuit-seed rows against DE's 6 — with the finish when a
        # model is configured, and DE when the cma package is absent.
        # Sobol+Powell stays in the list; at 60 evaluations in 33
        # dimensions it does nothing at all.
        base = 'cmaes' if sizing.cmaes_available() else 'diff_evolution'
        if llm_client.configured():
            base = base.replace('cmaes', 'cmaes_llm_finish').replace(
                'diff_evolution', 'de_llm_finish')
        self.algo_combo.setCurrentIndex(self.algo_combo.findData(base))
        self.algo_combo.currentIndexChanged.connect(self._update_estimate)

        self.budget_spin = QSpinBox()
        self.budget_spin.setRange(10, 5000)
        # 600: where DE converges on the amplifiers (the finish keeps 48 of
        # it).  150 left DE one generation; the estimate says the cost.
        self.budget_spin.setValue(600)
        self.budget_spin.valueChanged.connect(self._update_estimate)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 9999)
        self.seed_spin.setToolTip(
            'Search seed. A different seed is the cheapest second opinion: '
            'on every circuit the search did not finish, two seeds ended in '
            'different places, in both directions.')
        import os
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 16)
        self.workers_spin.setValue(min(4, os.cpu_count() or 1))
        self.workers_spin.setToolTip(
            'Concurrent ngspice evaluations (AnalogGym circuits only; '
            'circuit-skills circuits always run serially).')
        self.workers_spin.valueChanged.connect(self._update_estimate)
        self._estimate = QLabel('')
        # every evaluation of a circuit is archived; re-scored under the
        # current targets, the best of them beat a cold search at 200
        # evaluations on six of eight target sets (cairn/pitfalls.md)
        self.known_chk = QCheckBox('Start from the best known point')
        self.known_chk.setToolTip(
            'Search from the archived evaluation that scores best under '
            'the current targets instead of the default sizing.  CMA-ES '
            'then takes a tight step (σ 0.1) with the point injected.')
        self.known_chk.toggled.connect(self._refresh_known)
        self._known_lbl = QLabel('')
        self._known: dict | None = None
        self._loading = False

        self.run_btn = QPushButton('Optimize')
        # clicked() carries a `checked` bool; _run's first parameter is the
        # run to resume, so the button must not pass it through
        self.run_btn.clicked.connect(lambda: self._run())
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel.set)
        self.export_btn = QPushButton('Export best .PARAM…')
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        self.runs_btn = QPushButton('Runs…')
        self.runs_btn.setToolTip('Saved optimization runs: load, compare '
                                 'convergence, warm-start from a best point.')
        self.runs_btn.clicked.connect(self._open_runs)
        self.next_btn = QPushButton('Try next')
        self.next_btn.setEnabled(False)
        self.next_btn.setToolTip('Apply the suggested next step (seed, '
                                 'budget or algorithm) and run it.')
        self.next_btn.clicked.connect(self._try_next)
        self._next: dict | None = None
        self.advise_btn = QPushButton('AI advise…')
        self.advise_btn.setToolTip('Ask the configured LLM for suggested '
                                   'bounds / starting point / budget.')
        self.advise_btn.clicked.connect(self._ai_advise)
        self.explain_btn = QPushButton('AI explain')
        self.explain_btn.setToolTip("Ask the configured LLM to analyse the "
                                    "last run's report (Chinese).")
        self.explain_btn.setEnabled(False)
        self.explain_btn.clicked.connect(self._ai_explain)
        self.waves_btn = QPushButton('Waves…')
        self.waves_btn.setToolTip(
            'Re-characterize the default and the optimized sizing with the '
            'swept curves captured, and overlay them. Panels per family: '
            'amps — gain/phase/PSRR± vs frequency + Vout vs temperature; '
            'LDOs — loop gain/phase (max+min load), PSRR, line regulation; '
            '5T OTA / op amp — gain/phase Bode; skill LDO — loop gain/'
            'phase/PSRR/Zout; comparator — latch + output transients with '
            'τ; bootstrap — Ron vs Vin. Two extra evaluations '
            '(seconds for skill circuits, ~10-20 s for amps/LDOs).')
        self.waves_btn.setEnabled(False)
        self.waves_btn.clicked.connect(self._compare_waves)
        self.import_btn = QPushButton('Import ▾')
        imp_menu = QMenu(self.import_btn)
        act = QAction('Sizing values (.PARAM)…', imp_menu)
        act.triggered.connect(self._import_params)
        imp_menu.addAction(act)
        act = QAction('Custom circuit (netlist + .PARAM)…', imp_menu)
        act.triggered.connect(self._import_circuit)
        imp_menu.addAction(act)
        self.import_btn.setMenu(imp_menu)
        self.import_btn.setToolTip(
            'Import a sizing back into the init column, or import your own '
            'amplifier design (.subckt <name> gnda vdda vinn vinp vout on '
            'SKY130, self-biased, plus its .PARAM design-variables file) as '
            'a new optimizable circuit — it persists across app upgrades and '
            'gets the full pipeline (metrics, waves, change summary).')
        self.netlist_btn = QPushButton('Netlist…')
        self.netlist_btn.setToolTip(
            "View the current circuit's design files: DUT netlist, design "
            'variables (with the current table values) and the fully '
            'rendered testbench; skill circuits show their templates.')
        self.netlist_btn.clicked.connect(self._show_netlist)

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
        sf.addRow('Seed', self.seed_spin)
        sf.addRow('Parallel evals', self.workers_spin)
        sf.addRow('', self._estimate)
        sf.addRow(self.known_chk, self._known_lbl)

        tgt_box = QGroupBox('Targets (editable; hard = 10x weight)')
        tb = QVBoxLayout(tgt_box)
        tb.addWidget(self._targets)

        var_box = QGroupBox('Design variables (bounds editable)')
        vb = QVBoxLayout(var_box)
        vb.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.next_btn)
        btn_row.addWidget(self.export_btn)
        btn_row.addWidget(self.runs_btn)
        ai_row = QHBoxLayout()
        ai_row.addWidget(self.advise_btn)
        ai_row.addWidget(self.explain_btn)
        ai_row.addWidget(self.waves_btn)
        ai_row.addWidget(self.import_btn)
        ai_row.addWidget(self.netlist_btn)
        ai_row.addStretch(1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(sel_box)
        ll.addWidget(tgt_box)
        ll.addWidget(var_box, stretch=1)
        ll.addLayout(btn_row)
        ll.addLayout(ai_row)
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
        self._loading = True                 # target cells being filled
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
            lbl = QTableWidgetItem(f'{ms.label} [{ms.unit}] ({ms.rule})')
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
        self._loading = False
        self._update_estimate()
        self._refresh_known()
        sch = sizing.schematic_path(self._key())
        if sch is not None:
            self._viewer.show_pngs([sch])

    def _refresh_known(self, *_):
        """The archive's best point under the targets as edited now."""
        if self._loading:
            return
        try:
            names = [v.name for v in self._read_table()]
            overrides = self._read_targets()
        except ValueError:
            self._known = None
            self._known_lbl.setText('')
            return
        self._known = sizing.archive_best(self._key(), names, overrides)
        if self._known is None:
            n = sizing.archive_size(self._key())
            self._known_lbl.setText(
                'no archived evaluations yet' if not n
                else f'{n} archived, none with these variables')
        else:
            self._known_lbl.setText(
                f'{self._known["n"]} archived; best under these targets '
                f'costs {self._known["cost"]:.4f}')

    def _update_estimate(self, *_):
        spec = sizing.SIZING[self._key()]
        is_skill = spec.kind == 'skill'
        self.workers_spin.setEnabled(not is_skill)
        workers = 1 if is_skill else self.workers_spin.value()
        budget = self.budget_spin.value()
        secs = spec.eval_seconds * budget / workers
        note = ''
        if self.algo_combo.currentData() == 'llm_agent':
            # one invocation for the whole search, and the model decides how
            # many simulations to ask for at a time — there are no rounds to
            # count, so say so rather than inventing a number
            note = '  (+ AI time, varies)'
        elif self.algo_combo.currentData() in ('de_llm_finish',
                                               'cmaes_llm_finish'):
            from app.core.llm_sizing import (
                FINISH_EFFORT, FINISH_PROPOSALS, FINISH_ROUNDS)
            # the proposals of a round run in parallel: wall clock is
            # one call per round
            secs += FINISH_ROUNDS * llm_client.round_seconds(
                effort=FINISH_EFFORT)
            note = (f'  (+ up to {FINISH_ROUNDS} AI rounds of '
                    f'{FINISH_PROPOSALS} calls)')
        elif self.algo_combo.currentData() == 'model_propose':
            secs = spec.eval_seconds * budget / workers + 15
            note = ('  (training on the archive ~15 s; budget = proposals '
                    'verified)')
        elif self.algo_combo.currentData() == 'llm':
            # The simulations are the small half here.  One round is one LLM
            # call plus min(workers, 4) evaluations, and the call can be a
            # hundred times longer than an evaluation — an estimate counting
            # only ngspice was reading "2 min" for an hour of work.
            from app.core.llm_sizing import LOOP_EFFORT
            per_round = llm_client.round_seconds(effort=LOOP_EFFORT)
            rounds = math.ceil(budget / max(1, min(workers, 4)))
            secs += rounds * per_round
            note = f'  ({rounds} AI rounds)'
        self._estimate.setText(f'≈ {secs / 60:.0f} min estimated{note}')

    def _read_table(self) -> list:
        variables = []
        base = {v.name: v for v in sizing.parse_variables(self._key())}
        for row in range(self._table.rowCount()):
            name = self._table.item(row, 0).text()
            try:
                init = float(self._table.item(row, 1).text())
                lo = float(self._table.item(row, 2).text())
                hi = float(self._table.item(row, 3).text())
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f'row {row + 1} ({name}): not a number') from exc
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
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f'target row {row + 1}: not a number') from exc
            hard = (self._targets.item(row, 2).checkState()
                    == Qt.CheckState.Checked)
            overrides[key] = (target, hard)
        return overrides

    # ── run / cancel ──────────────────────────────────────────────────────
    def _run(self, resume: sizing.SizingRun | None = None):
        """Start an optimization; with `resume`, carry that run on from
        its DE population for `budget` more evaluations."""
        if self.has_job('opt'):
            return
        if not isinstance(resume, sizing.SizingRun):   # a stray signal arg
            resume = None
        try:
            variables = self._read_table()
            overrides = self._read_targets()
        except ValueError as exc:
            self._status.setText(f'<font color="red">{exc}</font>')
            return
        key = self._key()
        budget = self.budget_spin.value()
        seed = self.seed_spin.value()
        algo = self.algo_combo.currentData()
        if (algo in ('llm', 'de_llm_finish', 'cmaes_llm_finish')
                and not llm_client.configured()):
            self._status.setText('<font color="red">LLM not configured — '
                                 'set model + API key in Settings.</font>')
            return
        workers = (1 if sizing.SIZING[key].kind == 'skill'
                   else self.workers_spin.value())
        if resume is not None and (resume.circuit != key
                                   or not resume.continuable):
            self._status.setText('<font color="red">That run cannot be '
                                 'continued here.</font>')
            return
        start = None
        if self.known_chk.isChecked() and resume is None:
            self._refresh_known()
            if self._known is None:
                self._status.setText('<font color="red">No archived '
                                     'evaluation of this circuit with these '
                                     'variables to start from.</font>')
                return
            start = dict(self._known['values'])
        self._cancel.clear()
        origin = getattr(resume, '_saved_as', '') if resume else ''

        def job():
            def progress(n, best, _metrics):
                if n % 5 == 0 or n == 1:
                    print(f'sizing {key}: eval {n}/{budget}  '
                          f'best cost {best:.4f}')
            run = sizing.optimize(key, variables, budget=budget,
                                  progress=progress,
                                  should_cancel=self._cancel.is_set,
                                  overrides=overrides, algo=algo,
                                  workers=workers, seed=seed, resume=resume,
                                  start=start)
            run.continued_from = origin
            return run

        what = 'continue' if resume is not None else 'sizing'
        self.submit_job('opt', Job(kind='sizing', fn=job,
                                   label=f'{what}: {key} ({budget} evals)'))
        self.run_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._status.setText(
            f'Optimizing ({budget} evaluations)'
            + (f' from the best known point (cost '
               f'{self._known["cost"]:.4f})' if start else '')
            + '… progress in the log panel below.')

    def on_job_finished(self, slot, result):
        if slot == 'advise':
            self._show_advice(result)
            return
        self._refresh_known()
        if slot == 'explain':
            self.explain_btn.setEnabled(True)
            self._report.appendPlainText('\n─── AI analysis ───\n'
                                         + str(result))
            self._status.setText('AI analysis appended below the report.')
            return
        if slot == 'import_check':
            key, metrics = result
            self._pending_import = None
            spec = sizing.SIZING.get(key)
            if metrics and spec is not None:
                shown = ', '.join(f'{ms.label} {metrics[ms.key]:.4g} {ms.unit}'
                                  for ms in spec.metrics
                                  if ms.key in metrics)[:200]
                self._status.setText(
                    f'{spec.subckt} imported and validated: {shown}')
            else:
                # a netlist that yields no metrics is broken — don't keep it
                self._drop_user_circuit(key)
                QMessageBox.warning(
                    self, 'Import failed',
                    'The imported circuit produced no metrics (ngspice '
                    'could not characterize it) and has been removed.\n'
                    'Check the netlist against an AnalogGym amp: '
                    '.subckt <name> gnda vdda vinn vinp vout, SKY130 '
                    'devices, self-biased, sized via the .PARAM file.')
            return
        if slot == 'waves':
            key, before, after = result
            self.waves_btn.setEnabled(True)
            try:
                png = sizing.render_wave_comparison(key, before, after)
            except Exception as exc:
                self._status.setText(
                    f'<font color="red">Wave plot failed: {exc}</font>')
                return
            pngs = list(getattr(self, '_last_pngs', [])) + [png]
            self._last_pngs = pngs
            self._viewer.show_pngs(pngs, current=len(pngs) - 1)
            self._status.setText('Waveform comparison added '
                                 '(default vs optimized).')
            return
        run: sizing.SizingRun = result
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        saved, infos = '', []
        try:
            path = sizing.save_run(run)
            run._saved_as = path.name        # what a continuation cites
            saved = f'  Saved as {path.name}.'
            for p in sizing.list_runs():
                try:
                    infos.append(sizing.run_info(p))
                except Exception:               # noqa: BLE001
                    continue
        except OSError:
            pass
        # "Done: 1.50 -> 1.50" said nothing a user could act on.  Say
        # which targets are still short and, from the measured order —
        # finish when close, another seed, then more budget — what to try.
        # _refresh_known ran first: the archive's best under the targets
        # as edited, this run's own points included
        self._next = sizing.next_step(run, infos,
                                      finish_available=llm_client.configured(),
                                      known=self._known)
        self.next_btn.setEnabled(self._next['action'] is not None)
        self._status.setText(
            f'Done: cost {run.initial_cost:.3f} → {run.best_cost:.3f} '
            f'in {run.evals} evaluations.{saved}  '
            + self._next['text'])
        self._show_run(run)

    def _try_next(self):
        """Apply the suggested settings and run.  Everything else — the
        circuit, bounds, targets, workers — stays as it is."""
        nxt = self._next
        if not nxt or nxt['action'] is None or self.has_job('opt'):
            return
        self.seed_spin.setValue(nxt['seed'])
        self.budget_spin.setValue(min(self.budget_spin.maximum(),
                                      nxt['budget']))
        idx = self.algo_combo.findData(nxt['algo'])
        if idx >= 0:
            self.algo_combo.setCurrentIndex(idx)
        if nxt['action'] == 'warm':
            self.known_chk.setChecked(True)
        self._run(resume=self._last_run if nxt.get('resume') else None)

    def _show_run(self, run: sizing.SizingRun):
        """Display a run's report + convergence curve (GUI thread)."""
        self._last_run = run
        self.export_btn.setEnabled(True)
        self.explain_btn.setEnabled(True)
        self.waves_btn.setEnabled(True)     # all kinds have wave capture
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
        self._last_pngs = pngs
        self._viewer.show_pngs(pngs, current=len(pngs) - 1)

    # ── before/after waveform comparison (two evals on the worker) ────────
    def _compare_waves(self):
        if self.has_job('waves') or self._last_run is None:
            return
        run = self._last_run
        key = run.circuit
        defaults = {v.name: v.default for v in sizing.parse_variables(key)}

        def job():
            before = sizing.capture_waves(key, defaults, 'before')
            after = sizing.capture_waves(key, run.best_values, 'after')
            return key, before, after

        self.submit_job('waves', Job(kind='sizing', fn=job,
                                     label=f'waves: {key} (2 evals)'))
        self.waves_btn.setEnabled(False)
        self._status.setText('Characterizing default vs optimized sizing '
                             '(2 ngspice runs)…')

    # ── design import + netlist viewer ────────────────────────────────────
    def _fill_init_values(self, values: dict) -> int:
        """Write matching values into the init column; returns #updated."""
        updated = 0
        for row in range(self._table.rowCount()):
            name = self._table.item(row, 0).text()
            if name in values:
                self._table.item(row, 1).setText(f'{values[name]:g}')
                updated += 1
        return updated

    def _import_params(self):
        fn, _ = QFileDialog.getOpenFileName(
            self, 'Import sizing values', '',
            'SPICE params (*.spice *.param *.txt);;All files (*)')
        if not fn:
            return
        values = sizing.parse_param_file(sizing.Path(fn))
        if not values:
            self._status.setText('<font color="red">No name=value '
                                 'parameters found in that file.</font>')
            return
        n = self._fill_init_values(values)
        skipped = len(values) - n
        note = f' ({skipped} name(s) not in this circuit)' if skipped else ''
        self._status.setText(
            f'Imported {n} init value(s) from {sizing.Path(fn).name}{note}.')

    def _import_circuit(self):
        nl, _ = QFileDialog.getOpenFileName(
            self, 'Import circuit netlist (.subckt <name> gnda vdda vinn '
            'vinp vout)', '', 'All files (*)')
        if not nl:
            return
        vars_fn, _ = QFileDialog.getOpenFileName(
            self, 'Design-variables file (.PARAM) for the circuit', '',
            'SPICE params (*.spice *.param *.txt);;All files (*)')
        if not vars_fn:
            return
        try:
            key = sizing.import_user_circuit(sizing.Path(nl),
                                             sizing.Path(vars_fn))
        except (ValueError, OSError) as exc:
            self._status.setText(f'<font color="red">{exc}</font>')
            return
        spec = sizing.SIZING[key]
        self.circuit_combo.addItem(spec.title, userData=key)
        self.circuit_combo.setCurrentIndex(self.circuit_combo.count() - 1)
        defaults = {v.name: v.default for v in sizing.parse_variables(key)}
        self._pending_import = key
        self.submit_job('import_check',
                        Job(kind='sizing',
                            fn=lambda: (key, sizing.evaluate(key, defaults)),
                            label=f'import check: {key}'))
        self._status.setText(f'Imported {spec.subckt} — validating with one '
                             'evaluation…')

    def _drop_user_circuit(self, key: str | None):
        """Unregister a (failed) user import and drop its combo entry."""
        if not key:
            return
        try:
            sizing.remove_user_circuit(key)
        except ValueError:
            pass
        idx = self.circuit_combo.findData(key)
        if idx >= 0:
            self.circuit_combo.removeItem(idx)
        self._pending_import = None

    def _show_netlist(self):
        key = self._key()
        try:
            values = {v.name: v.default for v in self._read_table()}
        except ValueError:
            values = None
        try:
            texts = sizing.netlist_texts(key, values)
        except OSError as exc:
            self._status.setText(f'<font color="red">{exc}</font>')
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f'Design files — {sizing.SIZING[key].title}')
        dlg.resize(860, 640)
        lay = QVBoxLayout(dlg)
        tabs = QTabWidget()
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        for title, text in texts:
            ed = QPlainTextEdit()
            ed.setReadOnly(True)
            ed.setFont(mono)
            ed.setPlainText(text)
            tabs.addTab(ed, title)
        lay.addWidget(tabs)
        row = QHBoxLayout()
        if sizing.SIZING[key].pkg == 'user':
            rm = QPushButton('Remove this imported circuit')
            rm.clicked.connect(lambda: self._remove_user(key, dlg))
            row.addWidget(rm)
        row.addStretch(1)
        close = QPushButton('Close')
        close.clicked.connect(dlg.accept)
        row.addWidget(close)
        lay.addLayout(row)
        dlg.exec()

    def _remove_user(self, key: str, dlg: QDialog):
        if QMessageBox.question(
                dlg, 'Remove circuit',
                f'Remove {key} and delete its files from the workspace?') \
                != QMessageBox.StandardButton.Yes:
            return
        sizing.remove_user_circuit(key)
        idx = self.circuit_combo.findData(key)
        if idx >= 0:
            self.circuit_combo.removeItem(idx)
        dlg.accept()
        self._status.setText(f'{key} removed.')

    def on_job_failed(self, slot, err):
        if slot == 'advise':
            self.advise_btn.setEnabled(True)
        elif slot == 'explain':
            self.explain_btn.setEnabled(self._last_run is not None)
        elif slot == 'waves':
            self.waves_btn.setEnabled(self._last_run is not None)
        elif slot == 'import_check':
            self._drop_user_circuit(self._pending_import)
        else:
            self.run_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
        self._status.setText(fail_text(err))

    # ── AI advise / explain (one-shot LLM calls on the worker) ────────────
    def _ai_advise(self):
        if self.has_job('advise'):
            return
        if not llm_client.configured():
            self._status.setText('<font color="red">LLM not configured — '
                                 'set model + API key in Settings.</font>')
            return
        try:
            variables = self._read_table()
            overrides = self._read_targets()
        except ValueError as exc:
            self._status.setText(f'<font color="red">{exc}</font>')
            return
        key = self._key()

        def job():
            from app.core import llm_sizing
            return llm_sizing.suggest_setup(key, variables, overrides)

        self.advise_btn.setEnabled(False)
        self.submit_job('advise', Job(kind='sizing', fn=job,
                                      label=f'AI advice: {key}'))
        self._status.setText('Asking the LLM for setup advice…')

    def _show_advice(self, result):
        self.advise_btn.setEnabled(True)
        suggestions, rationale = result
        budget = suggestions.pop('_budget', None)
        if not suggestions and budget is None:
            self._status.setText('AI returned no applicable suggestion.')
            return
        lines = [f'{n}:  init {d["init"]:g},  range '
                 f'[{d["lo"]:g}, {d["hi"]:g}]'
                 for n, d in suggestions.items()]
        if budget is not None:
            lines.append(f'budget: {budget} evaluations')
        answer = QMessageBox.question(
            self, 'AI setup advice',
            (rationale + '\n\n' if rationale else '')
            + '\n'.join(lines) + '\n\nApply to the tables?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        applied = 0
        for row in range(self._table.rowCount()):
            name = self._table.item(row, 0).text()
            if name in suggestions:
                d = suggestions[name]
                for col, val in ((1, d['init']), (2, d['lo']),
                                 (3, d['hi'])):
                    self._table.item(row, col).setText(f'{val:g}')
                applied += 1
        if budget is not None:
            self.budget_spin.setValue(int(budget))
        self._status.setText(f'Applied AI suggestions to {applied} '
                             'variable(s).')

    def _ai_explain(self):
        if self._last_run is None or self.has_job('explain'):
            return
        if not llm_client.configured():
            self._status.setText('<font color="red">LLM not configured — '
                                 'set model + API key in Settings.</font>')
            return
        run = self._last_run
        variables = sizing.parse_variables(run.circuit)

        def job():
            from app.core import llm_sizing
            return llm_sizing.explain_run(run, variables)

        self.explain_btn.setEnabled(False)
        self.submit_job('explain', Job(kind='sizing', fn=job,
                                       label='AI explain'))
        self._status.setText('Asking the LLM to analyse the report…')

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

    # ── saved runs: load / compare / warm start ───────────────────────────
    def _open_runs(self):
        dlg = RunsDialog(self)
        dlg.exec()

    def apply_best_to_table(self, run: sizing.SizingRun) -> int:
        """Warm start: write a run's best values into the init column of the
        variables table (same circuit only).  Returns #cells updated."""
        if run.circuit != self._key():
            idx = self.circuit_combo.findData(run.circuit)
            if idx < 0:
                return 0
            self.circuit_combo.setCurrentIndex(idx)   # repopulates the table
        return self._fill_init_values(run.best_values)

    def set_sim_enabled(self, enabled: bool):
        self.run_btn.setEnabled(enabled and not self.has_job('opt'))


class RunsDialog(QDialog):
    """Saved sizing runs: load a report, overlay convergence curves,
    warm-start the variables table from a best point, or delete files."""

    def __init__(self, tab: SizingTab):
        super().__init__(tab)
        self._tab = tab
        self.setWindowTitle('Saved sizing runs')
        self.resize(640, 360)

        self._list = QTableWidget(0, 5)
        self._list.setHorizontalHeaderLabels(
            ['saved', 'circuit', 'evals', 'best cost', 'file'])
        self._list.horizontalHeader().setStretchLastSection(True)
        self._list.verticalHeader().setVisible(False)
        self._list.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._list.itemSelectionChanged.connect(self._on_selection)
        self._list.itemDoubleClicked.connect(lambda *_: self._load())

        self.load_btn = QPushButton('Load')
        self.load_btn.clicked.connect(self._load)
        self.compare_btn = QPushButton('Compare')
        self.compare_btn.setToolTip('Overlay the convergence curves of the '
                                    'selected runs (select 2+).')
        self.compare_btn.clicked.connect(self._compare)
        self.warm_btn = QPushButton('Use best as init')
        self.warm_btn.setToolTip("Write the selected run's best sizing into "
                                 'the init column (warm start).')
        self.warm_btn.clicked.connect(self._warm_start)
        self.continue_btn = QPushButton('Continue')
        self.continue_btn.setToolTip(
            "Carry the selected DE run on from its last population for the "
            "tab's budget of new evaluations. Re-running at a larger budget "
            'replays the first half; this does not.')
        self.continue_btn.clicked.connect(self._continue)
        self.delete_btn = QPushButton('Delete')
        self.delete_btn.clicked.connect(self._delete)
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.accept)

        btns = QHBoxLayout()
        for b in (self.load_btn, self.compare_btn, self.warm_btn,
                  self.continue_btn, self.delete_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(close_btn)

        lay = QVBoxLayout(self)
        lay.addWidget(self._list)
        lay.addLayout(btns)

        self._refresh()

    def _refresh(self):
        self._infos = []
        for p in sizing.list_runs():
            try:
                self._infos.append(sizing.run_info(p))
            except Exception:
                continue                     # unreadable/foreign file: skip
        self._list.setRowCount(len(self._infos))
        for row, info in enumerate(self._infos):
            cost = f"{info['best_cost']:.4f}" + (
                '  (cancelled)' if info['cancelled'] else '')
            for col, text in enumerate((info['saved_at'], info['title'],
                                        str(info['evals']), cost,
                                        info['path'].name)):
                self._list.setItem(row, col, QTableWidgetItem(text))
        self._list.resizeColumnsToContents()
        self._on_selection()

    def _selected(self) -> list:
        rows = sorted({i.row() for i in self._list.selectedItems()})
        return [self._infos[r] for r in rows]

    def _on_selection(self):
        n = len(self._selected())
        self.load_btn.setEnabled(n == 1)
        self.warm_btn.setEnabled(n == 1)
        sel = self._selected()
        self.continue_btn.setEnabled(
            n == 1 and bool(sel[0].get('continuable')))
        self.compare_btn.setEnabled(n >= 2)
        self.delete_btn.setEnabled(n >= 1)

    def _load_one(self) -> sizing.SizingRun | None:
        sel = self._selected()
        if len(sel) != 1:
            return None
        try:
            return sizing.load_run(sel[0]['path'])
        except Exception as exc:
            QMessageBox.warning(self, 'Load failed', str(exc))
            return None

    def _load(self):
        run = self._load_one()
        if run is None:
            return
        idx = self._tab.circuit_combo.findData(run.circuit)
        if idx >= 0:
            self._tab.circuit_combo.setCurrentIndex(idx)
        self._tab._show_run(run)
        self.accept()

    def _compare(self):
        sel = self._selected()
        runs = []
        for info in sel:
            try:
                runs.append(sizing.load_run(info['path']))
            except Exception:
                continue
        if len(runs) < 2:
            return
        png = sizing.render_comparison(runs)   # GUI thread (mpl policy)
        self._tab._viewer.show_pngs([png])
        self.accept()

    def _continue(self):
        run = self._load_one()
        if run is None:
            return
        run._saved_as = self._selected()[0]['path'].name
        tab = self._tab
        idx = tab.circuit_combo.findData(run.circuit)
        if idx < 0:
            return
        tab.circuit_combo.setCurrentIndex(idx)
        tab.seed_spin.setValue(run.seed)
        algo = tab.algo_combo.findData(run.algo)
        if algo >= 0:
            tab.algo_combo.setCurrentIndex(algo)
        self.accept()
        tab._run(resume=run)

    def _warm_start(self):
        run = self._load_one()
        if run is None:
            return
        n = self._tab.apply_best_to_table(run)
        self._tab._status.setText(
            f'Warm start: {n} init value(s) taken from {run.circuit} best.')
        self.accept()

    def _delete(self):
        sel = self._selected()
        if not sel:
            return
        if QMessageBox.question(
                self, 'Delete runs',
                f'Delete {len(sel)} saved run(s)?') != \
                QMessageBox.StandardButton.Yes:
            return
        for info in sel:
            try:
                info['path'].unlink()
            except OSError:
                pass
        self._refresh()

"""Tab (a): gm/ID designer — build a GmIdTable, size a transistor, view
design charts with the chosen operating point marked."""

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QRadioButton, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from app.core import gmid_service
from app.core.worker import Job, SimWorker
from app.ui.widgets.mpl_canvas import MplCanvas
from app.ui.widgets.op_result_view import OpResultView

# quantity key -> (label, unit, scale to display)
_LOOKUP_QTYS = [
    ('id_w', 'Id/W', 'uA/um', 1.0),
    ('ft',   'fT',   'GHz',   1e-9),
    ('vgs',  'Vgs',  'V',     1.0),
    ('vov',  'Vov',  'V',     1.0),
    ('gmro', 'gm*ro', '',     1.0),
    ('gm',   'gm',   'mS',    1e3),
    ('id',   'Id',   'uA',    1e6),
]


class GmIdTab(QWidget):
    def __init__(self, worker: SimWorker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self._pending_job: str | None = None
        self._check_job: str | None = None
        self._tbl = None
        self._curves = None

        infos = gmid_service.model_infos()

        # ── table-build form ──────────────────────────────────────────────
        self.model_combo = QComboBox()
        for name, info in infos.items():
            self.model_combo.addItem(
                f"{name}  (VDD {info.get('vdd', 1.8)} V)", userData=name)
        self.model_combo.currentIndexChanged.connect(self._on_model_change)

        self.w_spin = QDoubleSpinBox()
        self.w_spin.setRange(0.1, 1000.0)
        self.w_spin.setValue(10.0)
        self.w_spin.setSuffix(' um')

        self.l_spin = QDoubleSpinBox()
        self.l_spin.setRange(0.018, 10.0)
        self.l_spin.setDecimals(3)
        self.l_spin.setValue(0.18)
        self.l_spin.setSuffix(' um')

        self.vds_auto = QCheckBox('auto (VDD/2)')
        self.vds_auto.setChecked(True)
        self.vds_auto.toggled.connect(
            lambda on: self.vds_spin.setEnabled(not on))
        self.vds_spin = QDoubleSpinBox()
        self.vds_spin.setRange(0.05, 2.0)
        self.vds_spin.setDecimals(3)
        self.vds_spin.setValue(0.9)
        self.vds_spin.setSuffix(' V')
        self.vds_spin.setEnabled(False)
        vds_row = QHBoxLayout()
        vds_row.addWidget(self.vds_spin)
        vds_row.addWidget(self.vds_auto)

        self.build_btn = QPushButton('Build / Load Table')
        self.build_btn.clicked.connect(self._build_table)

        self._range_lbl = QLabel('No table loaded.')
        self._range_lbl.setWordWrap(True)

        build_box = QGroupBox('Lookup table')
        bf = QFormLayout(build_box)
        bf.addRow('Model', self.model_combo)
        bf.addRow('W (ref)', self.w_spin)
        bf.addRow('L', self.l_spin)
        bf.addRow('Vds', vds_row)
        bf.addRow(self.build_btn)
        bf.addRow(self._range_lbl)

        # ── sizing form ───────────────────────────────────────────────────
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            'Size by gm/ID',
            'Size for fT >= target',
            'Size for gm*ro >= target',
        ])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_change)

        # page 0: gm/ID + constraint (Id / W / gm)
        self.gmid_spin = QDoubleSpinBox()
        self.gmid_spin.setRange(2.0, 40.0)
        self.gmid_spin.setValue(15.0)
        self.gmid_spin.setSuffix(' V^-1')

        self._con_group = QButtonGroup(self)
        self.rb_id = QRadioButton('Id')
        self.rb_w = QRadioButton('W')
        self.rb_gm = QRadioButton('gm')
        self.rb_id.setChecked(True)
        for rb in (self.rb_id, self.rb_w, self.rb_gm):
            self._con_group.addButton(rb)
            rb.toggled.connect(self._on_constraint_change)
        con_row = QHBoxLayout()
        for rb in (self.rb_id, self.rb_w, self.rb_gm):
            con_row.addWidget(rb)

        self.con_value = QDoubleSpinBox()
        self.con_value.setRange(0.0001, 1e6)
        self.con_value.setDecimals(4)
        self.con_value.setValue(100.0)
        self.con_value.setSuffix(' uA')

        page0 = QWidget()
        f0 = QFormLayout(page0)
        f0.addRow('gm/ID', self.gmid_spin)
        f0.addRow('Fix', con_row)
        f0.addRow('Value', self.con_value)

        # page 1: fT target + Id/W constraint
        self.ft_spin = QDoubleSpinBox()
        self.ft_spin.setRange(0.01, 2000.0)
        self.ft_spin.setValue(5.0)
        self.ft_spin.setSuffix(' GHz')
        self._ft_rb_id = QRadioButton('Id')
        self._ft_rb_w = QRadioButton('W')
        self._ft_rb_w.setChecked(True)
        ftg = QButtonGroup(self)
        ftg.addButton(self._ft_rb_id)
        ftg.addButton(self._ft_rb_w)
        self._ft_rb_id.toggled.connect(self._on_constraint_change)
        ft_row = QHBoxLayout()
        ft_row.addWidget(self._ft_rb_id)
        ft_row.addWidget(self._ft_rb_w)
        self.ft_con_value = QDoubleSpinBox()
        self.ft_con_value.setRange(0.0001, 1e6)
        self.ft_con_value.setDecimals(4)
        self.ft_con_value.setValue(20.0)
        self.ft_con_value.setSuffix(' um')
        page1 = QWidget()
        f1 = QFormLayout(page1)
        f1.addRow('fT target', self.ft_spin)
        f1.addRow('Fix', ft_row)
        f1.addRow('Value', self.ft_con_value)

        # page 2: gm*ro target + Id/W constraint
        self.gmro_spin = QDoubleSpinBox()
        self.gmro_spin.setRange(1.0, 1000.0)
        self.gmro_spin.setValue(35.0)
        self._gr_rb_id = QRadioButton('Id')
        self._gr_rb_w = QRadioButton('W')
        self._gr_rb_id.setChecked(True)
        grg = QButtonGroup(self)
        grg.addButton(self._gr_rb_id)
        grg.addButton(self._gr_rb_w)
        self._gr_rb_id.toggled.connect(self._on_constraint_change)
        gr_row = QHBoxLayout()
        gr_row.addWidget(self._gr_rb_id)
        gr_row.addWidget(self._gr_rb_w)
        self.gr_con_value = QDoubleSpinBox()
        self.gr_con_value.setRange(0.0001, 1e6)
        self.gr_con_value.setDecimals(4)
        self.gr_con_value.setValue(50.0)
        self.gr_con_value.setSuffix(' uA')
        page2 = QWidget()
        f2 = QFormLayout(page2)
        f2.addRow('gm*ro target', self.gmro_spin)
        f2.addRow('Fix', gr_row)
        f2.addRow('Value', self.gr_con_value)

        self._mode_stack = QStackedWidget()
        for p in (page0, page1, page2):
            self._mode_stack.addWidget(p)

        self.size_btn = QPushButton('Compute Operating Point')
        self.size_btn.clicked.connect(self._compute_op)
        self.size_btn.setEnabled(False)

        self._err_lbl = QLabel('')
        self._err_lbl.setWordWrap(True)

        size_box = QGroupBox('Sizing')
        sv = QVBoxLayout(size_box)
        sv.addWidget(self.mode_combo)
        sv.addWidget(self._mode_stack)
        sv.addWidget(self.size_btn)
        sv.addWidget(self._err_lbl)

        # ── Tools: quick lookup + self-check ──────────────────────────────
        self.lk_gmid = QDoubleSpinBox()
        self.lk_gmid.setRange(2.0, 40.0)
        self.lk_gmid.setValue(15.0)
        self.lk_gmid.setSuffix(' V^-1')
        self.lk_qty = QComboBox()
        for key, label, unit, _s in _LOOKUP_QTYS:
            self.lk_qty.addItem(f'{label} [{unit}]' if unit else label, key)
        self.lk_btn = QPushButton('Look up')
        self.lk_btn.clicked.connect(self._quick_lookup)
        self.lk_btn.setEnabled(False)
        self.lk_result = QLabel('—')
        lk_row = QHBoxLayout()
        lk_row.addWidget(self.lk_gmid)
        lk_row.addWidget(self.lk_qty)
        lk_row.addWidget(self.lk_btn)

        self.check_btn = QPushButton('Run self-check (5 physics tests)')
        self.check_btn.clicked.connect(self._run_selfcheck)
        self.check_btn.setEnabled(False)
        self._check_lbl = QLabel('')
        self._check_lbl.setWordWrap(True)
        self._check_lbl.setTextFormat(Qt.TextFormat.RichText)

        tools_box = QGroupBox('Tools')
        tv = QVBoxLayout(tools_box)
        tv.addWidget(QLabel('Quick lookup at a gm/ID:'))
        tv.addLayout(lk_row)
        tv.addWidget(self.lk_result)
        tv.addWidget(self.check_btn)
        tv.addWidget(self._check_lbl)

        self._op_view = OpResultView()

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.addWidget(build_box)
        left_lay.addWidget(size_box)
        left_lay.addWidget(tools_box)
        left_lay.addWidget(self._op_view, stretch=1)

        # ── right: 2x2 design charts ──────────────────────────────────────
        self._canvas = MplCanvas(2, 2, figsize=(9, 7))

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self._canvas)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        lay = QHBoxLayout(self)
        lay.addWidget(split)

        worker.job_finished.connect(self._on_finished)
        worker.job_failed.connect(self._on_failed)
        self._on_model_change()

    # ── model/L defaults ──────────────────────────────────────────────────
    def _current_model(self) -> str:
        return self.model_combo.currentData()

    def _on_model_change(self, *_):
        model = self._current_model()
        infos = gmid_service.model_infos()
        vdd = float(infos[model].get('vdd', 1.8))
        self.l_spin.setValue(gmid_service.default_L(model))
        if self.vds_auto.isChecked():
            self.vds_spin.setValue(round(vdd / 2, 3))

    def _on_mode_change(self, idx):
        self._mode_stack.setCurrentIndex(idx)
        self._on_constraint_change()

    def _on_constraint_change(self, *_):
        idx = self.mode_combo.currentIndex()
        if idx == 0:
            if self.rb_id.isChecked():
                self.con_value.setSuffix(' uA')
            elif self.rb_w.isChecked():
                self.con_value.setSuffix(' um')
            else:
                self.con_value.setSuffix(' mS')
        elif idx == 1:
            self.ft_con_value.setSuffix(
                ' uA' if self._ft_rb_id.isChecked() else ' um')
        else:
            self.gr_con_value.setSuffix(
                ' uA' if self._gr_rb_id.isChecked() else ' um')

    # ── table build ───────────────────────────────────────────────────────
    def _build_table(self):
        if self._pending_job:
            return
        model = self._current_model()
        W = self.w_spin.value()
        L = self.l_spin.value()
        vds = None if self.vds_auto.isChecked() else self.vds_spin.value()
        job = Job(
            kind='gmid_table',
            fn=lambda: gmid_service.build_table(model, W, L, vds),
            label=f'gm/ID table: {model} L={L}um',
            log_dir=gmid_service.gmid_log_dir(),
        )
        self._pending_job = self._worker.submit(job)
        self.build_btn.setEnabled(False)
        self._range_lbl.setText('Building table … (first run needs ngspice '
                                'sweeps; cached rebuilds are instant)')
        self._err_lbl.setText('')

    def _on_finished(self, job_id, result):
        if job_id == self._check_job:
            self._check_job = None
            self.check_btn.setEnabled(True)
            n_pass = sum(1 for r in result if r['ok'])
            rows = ''.join(
                f'<tr><td>{"✓" if r["ok"] else "✗"}</td>'
                f'<td><font color="{"#3fb950" if r["ok"] else "#f85149"}">'
                f'{r["name"]}</font></td></tr>' for r in result)
            self._check_lbl.setText(
                f'<b>{n_pass}/{len(result)} passed</b>'
                f'<table>{rows}</table>')
            return
        if job_id != self._pending_job:
            return
        self._pending_job = None
        self.build_btn.setEnabled(True)
        self._tbl = result
        self._curves = gmid_service.extract_curves(result)
        rng = result.operating_range()
        self._range_lbl.setText(
            f"gm/ID range [{rng['gmid_min']:.1f}, {rng['gmid_max']:.1f}] "
            f"V^-1 · fT max {rng['ft_max_Hz'] / 1e9:.1f} GHz · "
            f"gm*ro@15 {rng['gmro_at_15']:.1f}")
        self.size_btn.setEnabled(True)
        self.lk_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        self._plot_curves()

    def _on_failed(self, job_id, err):
        last = err.strip().splitlines()[-1] if err.strip() else 'failed'
        if job_id == self._check_job:
            self._check_job = None
            self.check_btn.setEnabled(True)
            self._check_lbl.setText(
                f'<font color="red">Self-check failed: {last}</font>')
            return
        if job_id != self._pending_job:
            return
        self._pending_job = None
        self.build_btn.setEnabled(True)
        self._range_lbl.setText(
            f'<font color="red">Build failed: {last} (see log panel)</font>')

    # ── tools: quick lookup + self-check ──────────────────────────────────
    def _quick_lookup(self):
        if self._tbl is None:
            return
        key, label, unit, scale = _LOOKUP_QTYS[self.lk_qty.currentIndex()]
        try:
            val = self._tbl.lookup(key, self.lk_gmid.value()) * scale
        except Exception as exc:
            self.lk_result.setText(f'<font color="red">{exc}</font>')
            return
        self.lk_result.setText(
            f'{label} @ gm/ID={self.lk_gmid.value():g} = '
            f'<b>{val:.4g} {unit}</b>')

    def _run_selfcheck(self):
        if self._tbl is None or self._check_job:
            return
        from app.core import validate_service
        model, L = self._tbl.model, self._tbl.L
        vds = self._tbl.vds
        tbl = self._tbl
        job = Job(
            kind='validate',
            fn=lambda: validate_service.run_validation(model, L, vds, tbl),
            label=f'self-check: {model} L={L}um',
            log_dir=gmid_service.gmid_log_dir(),
        )
        self._check_job = self._worker.submit(job)
        self.check_btn.setEnabled(False)
        self._check_lbl.setText('Running 5 physics self-checks …')

    # ── sizing ────────────────────────────────────────────────────────────
    def _compute_op(self):
        if self._tbl is None:
            return
        self._err_lbl.setText('')
        try:
            idx = self.mode_combo.currentIndex()
            if idx == 0:
                kw = {}
                v = self.con_value.value()
                if self.rb_id.isChecked():
                    kw['Id'] = v * 1e-6
                elif self.rb_w.isChecked():
                    kw['W'] = v
                else:
                    kw['gm'] = v * 1e-3
                op = self._tbl.size(self.gmid_spin.value(), **kw)
            elif idx == 1:
                v = self.ft_con_value.value()
                kw = ({'Id': v * 1e-6} if self._ft_rb_id.isChecked()
                      else {'W': v})
                op = self._tbl.size_from_ft(self.ft_spin.value() * 1e9, **kw)
            else:
                v = self.gr_con_value.value()
                kw = ({'Id': v * 1e-6} if self._gr_rb_id.isChecked()
                      else {'W': v})
                op = self._tbl.size_from_gmro(self.gmro_spin.value(), **kw)
        except ValueError as exc:
            self._err_lbl.setText(f'<font color="red">{exc}</font>')
            return
        self._op_view.show_op(op)
        self._plot_curves(mark_gmid=op['gmid'])

    # ── plotting ──────────────────────────────────────────────────────────
    def _plot_curves(self, mark_gmid: float | None = None):
        if self._curves is None:
            return
        c = self._curves
        axes = self._canvas.axes
        panels = [
            (axes[0][0], c['ft'] / 1e9, '$f_T$ [GHz]', False),
            (axes[0][1], c['id_w'], '$I_D/W$ [uA/um]', True),
            (axes[1][0], c['gmro'], '$g_m \\cdot r_o$', False),
            (axes[1][1], None, '$V_{GS}$, $V_{OV}$ [V]', False),
        ]
        for ax, y, ylabel, logy in panels:
            ax.clear()
            if y is not None:
                ax.plot(c['gmid'], y, color='tab:blue')
            else:
                ax.plot(c['gmid'], c['vgs'], color='tab:blue',
                        label='$V_{GS}$')
                ax.plot(c['gmid'], c['vov'], color='tab:orange', ls='--',
                        label='$V_{OV}$')
                ax.legend(fontsize=8)
            if logy:
                ax.set_yscale('log')
            ax.set_xlabel('$g_m/I_D$ [$V^{-1}$]')
            ax.set_ylabel(ylabel)
            ax.grid(True, alpha=0.3)
            ax.set_xlim(4, 24)
            if mark_gmid is not None:
                ax.axvline(mark_gmid, color='crimson', ls=':', lw=1.2)
        if mark_gmid is not None:
            x = c['gmid']
            for ax, key in ((axes[0][0], 'ft'), (axes[0][1], 'id_w'),
                            (axes[1][0], 'gmro')):
                yv = float(np.interp(mark_gmid, x, c[key]))
                ax.plot([mark_gmid], [yv / 1e9 if key == 'ft' else yv],
                        'o', color='crimson', ms=6)
        title = (f'{self._tbl.model}  W={self._tbl.W:g}um  '
                 f'L={self._tbl.L * 1e3:.0f}nm  Vds={self._tbl.vds}V')
        self._canvas.figure.suptitle(title, fontsize=10)
        self._canvas.draw()

    def set_sim_enabled(self, enabled: bool):
        # cached tables can still be loaded without ngspice, so the build
        # button stays enabled; sizing needs a table anyway.
        pass

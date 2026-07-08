"""Tab: cross-parameter comparison plots (channel-length / node / caps)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QPushButton, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget,
)

from app import paths
from app.core import browser_service, gmid_service
from app.core.worker import Job, SimWorker
from app.ui.job_mixin import JobTabMixin, fail_text
from app.ui.widgets.png_viewer import PngViewer


class ComparisonTab(QWidget, JobTabMixin):
    def __init__(self, worker: SimWorker, parent=None):
        super().__init__(parent)
        self.init_job_runner(worker)
        self._pending_key: tuple | None = None
        self._cache: dict[tuple, object] = {}

        self._models = list(gmid_service.model_infos().keys())

        self.mode_combo = QComboBox()
        self.mode_combo.addItem('Channel-length comparison', 'length')
        self.mode_combo.addItem('Cross-node comparison', 'node')
        self.mode_combo.addItem('Gate-capacitance comparison', 'caps')
        self.mode_combo.currentIndexChanged.connect(self._on_mode)

        # ── page 0: channel-length (one model + L list) ──
        self.len_model = QComboBox()
        self.len_model.addItems(self._models)
        self.len_list = QLineEdit('0.18, 0.36, 1.0')
        page_len = QWidget()
        fl = QFormLayout(page_len)
        fl.addRow('Model', self.len_model)
        fl.addRow('L list [um]', self.len_list)

        # ── page 1 & 2: multi-select models (node / caps) ──
        self.node_list = self._make_model_list()
        page_node = QWidget()
        nl = QVBoxLayout(page_node)
        nl.addWidget(QLabel('Select 2+ models of the same polarity:'))
        nl.addWidget(self.node_list)

        self.caps_list = self._make_model_list()
        page_caps = QWidget()
        cl = QVBoxLayout(page_caps)
        cl.addWidget(QLabel('Select 2+ models of the same polarity:'))
        cl.addWidget(self.caps_list)

        self._stack = QStackedWidget()
        for p in (page_len, page_node, page_caps):
            self._stack.addWidget(p)

        self.gen_btn = QPushButton('Generate')
        self.gen_btn.clicked.connect(self._generate)
        self._status = QLabel('')
        self._status.setWordWrap(True)

        box = QGroupBox('Comparison')
        bl = QVBoxLayout(box)
        bl.addWidget(self.mode_combo)
        bl.addWidget(self._stack)
        bl.addWidget(self.gen_btn)
        bl.addWidget(self._status)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.addWidget(box)
        left_lay.addStretch(1)

        self._viewer = PngViewer()
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self._viewer)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        lay = QHBoxLayout(self)
        lay.addWidget(split)

    def _make_model_list(self) -> QListWidget:
        w = QListWidget()
        w.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for m in self._models:
            w.addItem(m)
        return w

    def _on_mode(self, idx):
        self._stack.setCurrentIndex(idx)

    # ── run ───────────────────────────────────────────────────────────────
    def _generate(self):
        if self.has_job('gen'):
            return
        mode = self.mode_combo.currentData()
        try:
            fn, key = self._build_job(mode)
        except ValueError as exc:
            self._status.setText(f'<font color="red">{exc}</font>')
            return
        if key in self._cache:
            self._viewer.show_pngs([self._cache[key]])
            self._status.setText('Loaded from session cache.')
            return
        self._pending_key = key
        self.submit_job('gen', Job(
            kind='comparison', fn=fn, label=f'comparison: {mode}',
            log_dir=gmid_service.gmid_log_dir()))
        self.gen_btn.setEnabled(False)
        self._status.setText(f'Generating {mode} comparison …')

    def _build_job(self, mode):
        out = paths.BROWSER_PLOTS
        if mode == 'length':
            model = self.len_model.currentText()
            try:
                L_list = [float(t) for t in
                          self.len_list.text().replace(',', ' ').split()]
            except ValueError:
                raise ValueError('L list must be numbers')
            if len(L_list) < 2:
                raise ValueError('need at least 2 L values')
            key = ('length', model, tuple(L_list))
            return (lambda: browser_service.generate_length_comparison(
                model, L_list, out)), key

        selected = [i.text() for i in
                    (self.node_list if mode == 'node'
                     else self.caps_list).selectedItems()]
        if len(selected) < 2:
            raise ValueError('select at least 2 models')
        pols = {browser_service._polarity(m) for m in selected}
        if len(pols) > 1:
            raise ValueError('all models must be the same polarity '
                             '(all nmos or all pmos)')
        key = (mode, tuple(selected))
        if mode == 'node':
            return (lambda: browser_service.generate_node_comparison(
                selected, out)), key
        if any(gmid_service.is_finfet(m) for m in selected):
            raise ValueError(
                'Gate-capacitance comparison uses the planar analytical model, '
                'which is invalid for FinFET.  Use the Browser tab\'s '
                '"Gate capacitances" plot for real BSIM-CMG caps.')
        return (lambda: browser_service.generate_caps_comparison(
            selected, out)), key

    def on_job_finished(self, slot, render):
        # render closure executes on the GUI thread (matplotlib single-thread)
        self.gen_btn.setEnabled(True)
        try:
            png = render()
        except Exception as exc:
            self._status.setText(f'<font color="red">Plot failed: {exc}</font>')
            return
        self._cache[self._pending_key] = png
        self._status.setText('Done.')
        self._viewer.show_pngs([png])

    def on_job_failed(self, slot, err):
        self.gen_btn.setEnabled(True)
        self._status.setText(fail_text(err))

    def set_sim_enabled(self, enabled: bool):
        self.gen_btn.setEnabled(enabled and not self.has_job('gen'))

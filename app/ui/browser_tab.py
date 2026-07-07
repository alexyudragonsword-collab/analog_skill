"""Tab (c): characteristic curve browser."""

from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from app import paths
from app.core import browser_service, gmid_service
from app.core.worker import Job, SimWorker
from app.ui.job_mixin import JobTabMixin, fail_text
from app.ui.widgets.png_viewer import PngViewer


class BrowserTab(QWidget, JobTabMixin):
    def __init__(self, worker: SimWorker, parent=None):
        super().__init__(parent)
        self.init_job_runner(worker)
        self._pending_key: tuple | None = None
        self._cache: dict[tuple, object] = {}   # (type, model, W, L) -> Path

        self.model_combo = QComboBox()
        for label, name in gmid_service.model_choices():
            self.model_combo.addItem(label, userData=name)
        self.model_combo.currentIndexChanged.connect(self._on_model_change)

        self.type_combo = QComboBox()
        for key, label in browser_service.PLOT_TYPES.items():
            self.type_combo.addItem(label, userData=key)

        self.w_spin = QDoubleSpinBox()
        self.w_spin.setRange(0.1, 1000.0)
        self.w_spin.setValue(10.0)
        self.w_spin.setSuffix(' um')

        self.l_spin = QDoubleSpinBox()
        self.l_spin.setRange(0.018, 10.0)
        self.l_spin.setDecimals(3)
        self.l_spin.setValue(0.18)
        self.l_spin.setSuffix(' um')

        self.gen_btn = QPushButton('Generate / Show')
        self.gen_btn.clicked.connect(lambda: self._generate(force=False))
        self.regen_btn = QPushButton('Regenerate')
        self.regen_btn.clicked.connect(lambda: self._generate(force=True))
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.gen_btn)
        btn_row.addWidget(self.regen_btn)

        self._status = QLabel('')
        self._status.setWordWrap(True)

        box = QGroupBox('Characterization')
        form = QFormLayout(box)
        form.addRow('Model', self.model_combo)
        form.addRow('Plot', self.type_combo)
        form.addRow('W', self.w_spin)
        form.addRow('L', self.l_spin)
        form.addRow(btn_row)
        form.addRow(self._status)

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

        self._on_model_change()

    def _on_model_change(self, *_):
        model = self.model_combo.currentData()
        self.l_spin.setValue(gmid_service.default_L(model))

    def _key(self):
        return (self.type_combo.currentData(),
                self.model_combo.currentData(),
                round(self.w_spin.value(), 3),
                round(self.l_spin.value(), 4))

    def _generate(self, force: bool):
        if self.has_job('gen'):
            return
        key = self._key()
        if not force and key in self._cache:
            self._viewer.show_pngs([self._cache[key]])
            self._status.setText('Loaded from session cache.')
            return
        ptype, model, W, L = key
        self._pending_key = key
        self.submit_job('gen', Job(
            kind='browser_plot',
            fn=lambda: browser_service.generate_plot(
                ptype, model, W, L, paths.BROWSER_PLOTS),
            label=f'characterization: {ptype} {model}',
            log_dir=gmid_service.gmid_log_dir(),
        ))
        self.gen_btn.setEnabled(False)
        self.regen_btn.setEnabled(False)
        self._status.setText(f'Generating {ptype} for {model} …')

    def on_job_finished(self, slot, render):
        # render closure executes here, on the GUI thread — matplotlib is
        # not safe to use from more than one thread
        self.gen_btn.setEnabled(True)
        self.regen_btn.setEnabled(True)
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
        self.regen_btn.setEnabled(True)
        self._status.setText(fail_text(err))

    def set_sim_enabled(self, enabled: bool):
        idle = not self.has_job('gen')
        self.gen_btn.setEnabled(enabled and idle)
        self.regen_btn.setEnabled(enabled and idle)

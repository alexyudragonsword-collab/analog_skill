"""Tab (c): characteristic curve browser."""

from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from app import paths
from app.core import browser_service, gmid_service
from app.core.worker import Job, SimWorker
from app.ui.widgets.png_viewer import PngViewer


class BrowserTab(QWidget):
    def __init__(self, worker: SimWorker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self._pending_job: str | None = None
        self._cache: dict[tuple, object] = {}   # (type, model, W, L) -> Path

        self.model_combo = QComboBox()
        for name, info in gmid_service.model_infos().items():
            self.model_combo.addItem(
                f"{name}  (VDD {info.get('vdd', 1.8)} V)", userData=name)
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

        worker.job_finished.connect(self._on_finished)
        worker.job_failed.connect(self._on_failed)
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
        if self._pending_job:
            return
        key = self._key()
        if not force and key in self._cache:
            self._viewer.show_pngs([self._cache[key]])
            self._status.setText('Loaded from session cache.')
            return
        ptype, model, W, L = key
        job = Job(
            kind='browser_plot',
            fn=lambda: browser_service.generate_plot(
                ptype, model, W, L, paths.BROWSER_PLOTS),
            label=f'characterization: {ptype} {model}',
            log_dir=gmid_service.gmid_log_dir(),
        )
        self._pending_key = key
        self._pending_job = self._worker.submit(job)
        self.gen_btn.setEnabled(False)
        self.regen_btn.setEnabled(False)
        self._status.setText(f'Generating {ptype} for {model} …')

    def _on_finished(self, job_id, result):
        if job_id != self._pending_job:
            return
        self._pending_job = None
        self.gen_btn.setEnabled(True)
        self.regen_btn.setEnabled(True)
        self._cache[self._pending_key] = result
        self._status.setText('Done.')
        self._viewer.show_pngs([result])

    def _on_failed(self, job_id, err):
        if job_id != self._pending_job:
            return
        self._pending_job = None
        self.gen_btn.setEnabled(True)
        self.regen_btn.setEnabled(True)
        last = err.strip().splitlines()[-1] if err.strip() else 'failed'
        self._status.setText(
            f'<font color="red">Failed: {last} (see log panel)</font>')

    def set_sim_enabled(self, enabled: bool):
        self.gen_btn.setEnabled(enabled and not self._pending_job)
        self.regen_btn.setEnabled(enabled and not self._pending_job)

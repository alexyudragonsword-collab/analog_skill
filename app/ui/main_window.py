"""Analog Studio main window: three tabs, log dock, ngspice status bar."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget, QLabel, QMainWindow, QPushButton, QTabWidget, QHBoxLayout,
    QWidget,
)

from app.core.ngspice_locator import locate, INSTALL_HINT
from app.core.worker import SimWorker
from app.ui.widgets.log_panel import LogPanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Analog Studio — gm/ID & ngspice workbench')
        self.resize(1280, 820)

        self.worker = SimWorker(self)
        self.worker.start()

        # tabs (imported here so QApplication exists first)
        from app.ui.gmid_tab import GmIdTab
        from app.ui.examples_tab import ExamplesTab
        from app.ui.browser_tab import BrowserTab

        self.gmid_tab = GmIdTab(self.worker)
        self.examples_tab = ExamplesTab(self.worker)
        self.browser_tab = BrowserTab(self.worker)

        tabs = QTabWidget()
        tabs.addTab(self.gmid_tab, 'gm/ID Designer')
        tabs.addTab(self.examples_tab, 'ngspice Examples')
        tabs.addTab(self.browser_tab, 'Curve Browser')

        # ngspice-missing banner
        self._banner = QWidget()
        bl = QHBoxLayout(self._banner)
        bl.setContentsMargins(8, 4, 8, 4)
        self._banner_lbl = QLabel('')
        self._banner_lbl.setWordWrap(True)
        locate_btn = QPushButton('Locate…')
        locate_btn.clicked.connect(self._open_settings)
        bl.addWidget(self._banner_lbl, stretch=1)
        bl.addWidget(locate_btn)
        self._banner.setStyleSheet(
            'background: #7a2b2b; color: white; border-radius: 4px;')
        self._banner.hide()

        central = QWidget()
        from PySide6.QtWidgets import QVBoxLayout
        cl = QVBoxLayout(central)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.addWidget(self._banner)
        cl.addWidget(tabs)
        self.setCentralWidget(central)

        # log dock
        self.log_panel = LogPanel()
        dock = QDockWidget('Simulation log', self)
        dock.setWidget(self.log_panel)
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea |
                             Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

        # status bar
        self._job_lbl = QLabel('idle')
        self._ngspice_btn = QPushButton('ngspice: checking…')
        self._ngspice_btn.setFlat(True)
        self._ngspice_btn.clicked.connect(self._open_settings)
        self.statusBar().addWidget(self._job_lbl, 1)
        self.statusBar().addPermanentWidget(self._ngspice_btn)

        # worker signals
        self.worker.log_line.connect(self.log_panel.append_line)
        self.worker.job_started.connect(
            lambda _id, label: self._job_lbl.setText(f'running: {label}'))
        self.worker.job_finished.connect(
            lambda *_: self._job_lbl.setText('idle'))
        self.worker.job_failed.connect(self._on_job_failed)

        self.refresh_ngspice_status()

    # ── ngspice status ────────────────────────────────────────────────────
    def refresh_ngspice_status(self):
        st = locate()
        if st.ok:
            self._ngspice_btn.setText(f'ngspice ✓  ({st.version})')
            self._ngspice_btn.setStyleSheet('color: #3fb950;')
            self._banner.hide()
        else:
            self._ngspice_btn.setText('ngspice ✗  not found')
            self._ngspice_btn.setStyleSheet('color: #f85149;')
            self._banner_lbl.setText(
                'ngspice not found — simulations are disabled. '
                'Cached gm/ID tables can still be loaded.')
            self._banner.show()
        for tab in (self.examples_tab, self.browser_tab, self.gmid_tab):
            tab.set_sim_enabled(st.ok)
        if not st.ok:
            self.log_panel.append_line(INSTALL_HINT)

    def _open_settings(self):
        from app.ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        if dlg.exec():
            self.refresh_ngspice_status()

    def _on_job_failed(self, _id, err):
        self._job_lbl.setText('failed (see log)')
        for line in err.splitlines():
            self.log_panel.append_line(line)

    # ── shutdown ──────────────────────────────────────────────────────────
    def closeEvent(self, event):
        self.worker.stop()
        self.worker.wait(3000)
        super().closeEvent(event)

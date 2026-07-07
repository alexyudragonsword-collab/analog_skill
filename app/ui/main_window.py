"""Analog Studio main window: four tabs, log dock, ngspice status bar."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget, QLabel, QMainWindow, QPushButton, QTabWidget, QHBoxLayout,
    QWidget,
)

from app import __author__, __version__, APP_NAME
from app.core.ngspice_locator import locate, INSTALL_HINT
from app.core.worker import SimWorker
from app.ui.widgets.log_panel import LogPanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'{APP_NAME} — gm/ID & ngspice workbench')
        self.resize(1280, 820)
        self._build_menus()

        self.worker = SimWorker(self)
        self.worker.start()

        # tabs (imported here so QApplication exists first)
        from app.ui.gmid_tab import GmIdTab
        from app.ui.examples_tab import ExamplesTab
        from app.ui.browser_tab import BrowserTab
        from app.ui.comparison_tab import ComparisonTab

        self.gmid_tab = GmIdTab(self.worker)
        self.examples_tab = ExamplesTab(self.worker)
        self.browser_tab = BrowserTab(self.worker)
        self.comparison_tab = ComparisonTab(self.worker)

        tabs = QTabWidget()
        tabs.addTab(self.gmid_tab, 'gm/ID Designer')
        tabs.addTab(self.examples_tab, 'ngspice Examples')
        tabs.addTab(self.browser_tab, 'Curve Browser')
        tabs.addTab(self.comparison_tab, 'Comparison')

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

    # ── menus ─────────────────────────────────────────────────────────────
    def _build_menus(self):
        help_menu = self.menuBar().addMenu('&Help')

        manual_act = help_menu.addAction('User Manual / 用户手册')
        manual_act.setShortcut('F1')
        manual_act.triggered.connect(self._show_manual)

        help_menu.addSeparator()
        about_act = help_menu.addAction(f'About {APP_NAME} / 关于')
        about_act.triggered.connect(self._show_about)

    def _show_manual(self):
        from app.ui.manual_dialog import ManualDialog
        if getattr(self, '_manual_dlg', None) is None:
            self._manual_dlg = ManualDialog(self)
        self._manual_dlg.show()
        self._manual_dlg.raise_()
        self._manual_dlg.activateWindow()

    def _show_about(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.about(
            self, f'About {APP_NAME}',
            f'<h2>{APP_NAME}</h2>'
            f'<p><b>Version</b>: v{__version__}<br>'
            f'<b>Author</b>: {__author__}</p>'
            '<p>An analog IC design &amp; simulation workbench: '
            'gm/ID sizing, ngspice teaching examples and device '
            'characterization, built on ngspice + PySide6.</p>'
            '<p>模拟集成电路设计与仿真工作台:gm/ID 尺寸设计、ngspice '
            '教学案例与器件特性表征。</p>'
            '<p><small>PTM models © Arizona State University, '
            'free for academic research.</small></p>')

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
        for tab in (self.examples_tab, self.browser_tab, self.gmid_tab,
                    self.comparison_tab):
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
        # stop() drains queued jobs, so at most the in-flight one remains
        self.worker.stop()
        if not self.worker.wait(10000):
            # last resort at shutdown: better than Qt aborting on a QThread
            # destroyed while still running
            self.worker.terminate()
            self.worker.wait(2000)
        super().closeEvent(event)

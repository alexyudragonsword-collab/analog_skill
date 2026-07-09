"""Zoomable/pannable PNG display with an optional thumbnail strip."""

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QIcon, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
    QFileDialog, QLabel,
)


class _ZoomView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)


class PngViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths: list[Path] = []
        self._current: Path | None = None

        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        self._view = _ZoomView(self._scene)

        self._thumbs = QListWidget()
        self._thumbs.setViewMode(QListWidget.ViewMode.IconMode)
        self._thumbs.setIconSize(QSize(120, 90))
        self._thumbs.setFixedHeight(120)
        self._thumbs.setFlow(QListWidget.Flow.LeftToRight)
        self._thumbs.itemClicked.connect(self._on_thumb)
        self._thumbs.hide()

        self._placeholder = QLabel('No plot yet — run a simulation.')
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)

        fit_btn = QPushButton('Fit')
        fit_btn.clicked.connect(self.fit)
        save_btn = QPushButton('Save as…')
        save_btn.clicked.connect(self._save_as)
        open_btn = QPushButton('Open folder')
        open_btn.clicked.connect(self._open_folder)
        btns = QHBoxLayout()
        btns.addStretch(1)
        for b in (fit_btn, save_btn, open_btn):
            btns.addWidget(b)

        lay = QVBoxLayout(self)
        lay.addWidget(self._placeholder)
        lay.addWidget(self._view)
        lay.addWidget(self._thumbs)
        lay.addLayout(btns)
        self._view.hide()

    # ── public ────────────────────────────────────────────────────────────
    def show_pngs(self, paths: list[Path], current: int = 0):
        """Show a set of PNGs; `current` selects the one displayed first."""
        self._paths = [Path(p) for p in paths if Path(p).exists()]
        self._thumbs.clear()
        if not self._paths:
            self._view.hide()
            self._placeholder.show()
            return
        if len(self._paths) > 1:
            for p in self._paths:
                item = QListWidgetItem(QIcon(str(p)), p.name)
                item.setData(Qt.ItemDataRole.UserRole, str(p))
                self._thumbs.addItem(item)
            self._thumbs.show()
        else:
            self._thumbs.hide()
        self._show(self._paths[min(max(current, 0), len(self._paths) - 1)])

    def fit(self):
        if self._current:
            self._view.fitInView(self._item,
                                 Qt.AspectRatioMode.KeepAspectRatio)

    # ── private ───────────────────────────────────────────────────────────
    def _show(self, path: Path):
        self._current = path
        self._item.setPixmap(QPixmap(str(path)))
        self._placeholder.hide()
        self._view.show()
        self._view.resetTransform()
        self.fit()

    def _on_thumb(self, item: QListWidgetItem):
        self._show(Path(item.data(Qt.ItemDataRole.UserRole)))

    def _save_as(self):
        if not self._current:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, 'Save plot', self._current.name, 'PNG images (*.png)')
        if dest:
            QPixmap(str(self._current)).save(dest)

    def _open_folder(self):
        if self._current:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self._current.parent)))

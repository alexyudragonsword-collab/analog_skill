"""Backend-independent matplotlib canvas for GUI-native plots.

Uses matplotlib.figure.Figure directly (no pyplot), so the skill modules'
import-time ``matplotlib.use('Agg')`` has no effect on these canvases.

Thread policy: ALL matplotlib rendering in this app happens on the GUI
thread — worker jobs return render closures that the tabs execute in their
finished handlers.  matplotlib's process-global font objects are not safe to
use from more than one thread (crashes were observed even for sequential
cross-thread use), so no locking scheme can substitute for this policy.
"""

from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg, NavigationToolbar2QT)
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget


class MplCanvas(QWidget):
    def __init__(self, nrows=1, ncols=1, parent=None, figsize=(8, 6)):
        super().__init__(parent)
        self.figure = Figure(figsize=figsize, layout='constrained')
        self.axes = self.figure.subplots(nrows, ncols)
        self.canvas = FigureCanvasQTAgg(self.figure)
        # let a splitter shrink the plot on small screens instead of the
        # figure's sizeHint forcing the window taller
        self.canvas.setMinimumSize(240, 180)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas)

    def draw(self):
        self.canvas.draw_idle()

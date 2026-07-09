"""Small layout helpers shared by the tabs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget


def scroll_wrap(widget: QWidget) -> QScrollArea:
    """Wrap a control panel in a vertically-scrolling area.

    Lets a tall stack of control group-boxes scroll instead of forcing the
    window taller (or being clipped) on small / HiDPI-scaled screens.
    """
    area = QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area

"""Flow layout: wraps cards onto new rows as the width shrinks.

Adapted from the canonical Qt FlowLayout example, tuned for the RunHub
project card grid.
"""

from __future__ import annotations

from typing import List

from PyQt5.QtCore import QPoint, QRect, QSize, Qt
from PyQt5.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowLayout(QLayout):
    """Lays child widgets left-to-right, wrapping onto new lines."""

    def __init__(self, parent=None, margin: int = 0, spacing: int = 16) -> None:
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing
        self._items: List[QLayoutItem] = []

    # ------------------------------------------------------------------ #

    def addItem(self, item) -> None:  # noqa: N802 - Qt API
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        try:
            return self._items[index]
        except IndexError:
            return None

    def takeAt(self, index: int):
        try:
            return self._items.pop(index)
        except IndexError:
            return None

    def clear(self) -> None:
        while self._items:
            item = self._items.pop()
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
            item.setWidget(None)

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def spacing(self) -> int:  # noqa: D102
        return self._spacing

    def set_spacing(self, spacing: int) -> None:
        self._spacing = spacing
        self.update()

    # ------------------------------------------------------------------ #

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(),
                                  -margins.right(), -margins.bottom())
        x, y = effective.x(), effective.y()
        line_height = 0

        for item in self._items:
            hint = item.sizeHint()
            width, height = hint.width(), hint.height()
            next_x = x + width + self._spacing
            if x != effective.x() and next_x - self._spacing > effective.right():
                x = effective.x()
                y = y + line_height + self._spacing
                line_height = 0
                next_x = x + width + self._spacing
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, height)

        return y + line_height - rect.y() + margins.bottom()

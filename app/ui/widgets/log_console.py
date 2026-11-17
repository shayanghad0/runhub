"""Live log console widget.

Features required by the spec, all implemented here:

* auto scrolling (with pause-when-scrolled-up behaviour),
* level filtering (INFO / WARN / ERROR / SYS) via toggle chips,
* full-text search with match highlighting + Enter = next match,
* save to file, clear, font size controls, word-wrap toggle,
* error / warning highlighting via a QSyntaxHighlighter.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.services.log_manager import CMD, DBG, ERROR, INFO, SYS, WARN, LogRecord, _URL_RE
from app.ui.theme import Theme

log = logging.getLogger(__name__)


class LogHighlighter(QSyntaxHighlighter):
    """Colors timestamps, level tokens, URLs and error lines."""

    def __init__(self, document: QTextDocument, parent=None) -> None:
        super().__init__(document)
        self._theme = Theme.instance()
        Theme.instance().changed.connect(lambda: self.rehighlight())

    def _fmt(self, color: str, bold: bool = False,
             background: Optional[str] = None) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Bold)
        if background:
            fmt.setBackground(QColor(background))
        return fmt

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        palette = self._theme.palette()
        if not text:
            return

        # Timestamp prefix HH:MM:SS
        if len(text) >= 8 and text[2] == ":" and text[5] == ":":
            self.setFormat(0, 8, self._fmt(palette.text_faint))

        # Level token
        search_from = 8 if len(text) > 8 else 0
        for level, color in (
            (ERROR, palette.danger), (WARN, palette.warning),
            (SYS, palette.info), (CMD, palette.accent),
            (DBG, palette.text_faint), (INFO, palette.text_muted),
        ):
            index = text.find(level, search_from)
            if index >= 0:
                self.setFormat(index, len(level), self._fmt(color, bold=True))
                break

        # Error / warning line backgrounds
        upper = text.upper()
        if ERROR in upper or "TRACEBACK" in upper or "EXCEPTION" in upper:
            self.setFormat(0, len(text),
                           self._fmt(palette.danger, background=palette.danger_soft))
        elif WARN in upper or "DEPRECATION" in upper:
            self.setFormat(0, len(text),
                           self._fmt(palette.warning, background=palette.warning_soft))

        # URLs
        for match in _URL_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(),
                           self._fmt(palette.info, bold=True))


class LogConsole(QWidget):
    """Console panel bound to one project's log buffer."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project_id: Optional[str] = None
        self._log_manager = None
        self._levels = {INFO, WARN, ERROR, SYS}
        self._search_text = ""
        self._match_blocks: List[int] = []
        self._match_index = -1
        self._mono_pt = 9

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addLayout(self._build_toolbar())

        self._edit = QPlainTextEdit()
        self._edit.setObjectName("LogConsole")
        self._edit.setReadOnly(True)
        self._edit.setMaximumBlockCount(8000)
        self._edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._highlighter = LogHighlighter(self._edit.document())
        layout.addWidget(self._edit)

        Theme.instance().changed.connect(self._apply_fonts)
        self._apply_fonts()

    # ------------------------------------------------------------------ #
    # Toolbar
    # ------------------------------------------------------------------ #

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self._level_buttons = {}
        for level, label in ((INFO, "Info"), (WARN, "Warn"),
                             (ERROR, "Error"), (SYS, "System")):
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setChecked(level in self._levels)
            button.setStyleSheet("QToolButton { padding: 3px 10px; font-size: 11px; }")
            button.toggled.connect(lambda checked, lv=level: self._toggle_level(lv, checked))
            self._level_buttons[level] = button
            bar.addWidget(button)

        bar.addSpacing(4)
        self._search_edit = QLineEdit()
        self._search_edit.setObjectName("Search")
        self._search_edit.setPlaceholderText("Search in logs…  (Enter = next match)")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.returnPressed.connect(self._next_match)
        self._search_edit.textChanged.connect(self._on_search_changed)
        bar.addWidget(self._search_edit, 1)

        self._autoscroll_button = QToolButton()
        self._autoscroll_button.setText("Auto-scroll")
        self._autoscroll_button.setCheckable(True)
        self._autoscroll_button.setChecked(True)
        self._autoscroll_button.setStyleSheet(
            "QToolButton { padding: 3px 10px; font-size: 11px; }"
        )
        bar.addWidget(self._autoscroll_button)

        self._wrap_button = QToolButton()
        self._wrap_button.setText("Wrap")
        self._wrap_button.setCheckable(True)
        self._wrap_button.setStyleSheet("QToolButton { padding: 3px 10px; font-size: 11px; }")
        self._wrap_button.toggled.connect(self._toggle_wrap)
        bar.addWidget(self._wrap_button)

        smaller = QToolButton()
        smaller.setText("A-")
        smaller.setToolTip("Smaller console font")
        smaller.setStyleSheet("QToolButton { padding: 3px 8px; font-size: 11px; }")
        smaller.clicked.connect(lambda: self._change_font(-1))
        bar.addWidget(smaller)

        bigger = QToolButton()
        bigger.setText("A+")
        bigger.setToolTip("Larger console font")
        bigger.setStyleSheet("QToolButton { padding: 3px 8px; font-size: 11px; }")
        bigger.clicked.connect(lambda: self._change_font(+1))
        bar.addWidget(bigger)

        clear_button = QPushButton("Clear")
        clear_button.setObjectName("Ghost")
        clear_button.setToolTip("Clear the console view")
        clear_button.clicked.connect(self.clear)
        bar.addWidget(clear_button)

        save_button = QPushButton("Save…")
        save_button.setObjectName("Ghost")
        save_button.setToolTip("Save console contents to a file")
        save_button.clicked.connect(self.save_to_file)
        bar.addWidget(save_button)
        return bar

    # ------------------------------------------------------------------ #
    # Binding
    # ------------------------------------------------------------------ #

    def attach(self, project_id: str, log_manager) -> None:
        """Bind to a project's log stream and replay its buffer."""
        self.detach()
        self._project_id = project_id
        self._log_manager = log_manager
        if log_manager is not None:
            log_manager.record_added.connect(self._on_record_added)
        self.rebuild()

    def detach(self) -> None:
        if self._log_manager is not None and self._project_id:
            try:
                self._log_manager.record_added.disconnect(self._on_record_added)
            except TypeError:
                pass
        self._project_id = None
        self._log_manager = None

    def focus_search(self) -> None:
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def _on_record_added(self, project_id: str, record: LogRecord) -> None:
        if project_id != self._project_id or record.level not in self._levels:
            return
        at_bottom = self._at_bottom()
        self._edit.appendPlainText(f"{record.stamp}  {record.level:<5}  {record.text}")
        if at_bottom and self._autoscroll_button.isChecked():
            self._scroll_bottom()

    def rebuild(self) -> None:
        """Re-render the console from the buffer (filters/search applied)."""
        self._edit.setUpdatesEnabled(False)
        self._edit.clear()
        buffer = None
        if self._project_id and self._log_manager is not None:
            buffer = self._log_manager.log_for(self._project_id)
        if buffer is not None:
            query = self._search_text.lower().strip()
            for record in buffer.records:
                if record.level not in self._levels:
                    continue
                if query and query not in record.text.lower():
                    continue
                self._edit.appendPlainText(
                    f"{record.stamp}  {record.level:<5}  {record.text}"
                )
        self._edit.setUpdatesEnabled(True)
        self._scroll_bottom()
        self._apply_search_selections()

    def clear(self) -> None:
        self._edit.clear()

    def save_to_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save log",
            f"{self._project_id or 'runhub'}-console.log",
            "Log files (*.log *.txt);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self._edit.toPlainText())
            log.info("Saved console to %s", path)
        except OSError as exc:
            log.error("Cannot save console: %s", exc)

    # ------------------------------------------------------------------ #
    # Filters / search
    # ------------------------------------------------------------------ #

    def _toggle_level(self, level: str, checked: bool) -> None:
        if checked:
            self._levels.add(level)
        else:
            self._levels.discard(level)
        self.rebuild()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text
        self._match_index = -1
        self.rebuild()

    def _next_match(self) -> None:
        if not self._match_blocks:
            return
        self._match_index = (self._match_index + 1) % len(self._match_blocks)
        block = self._edit.document().findBlockByNumber(self._match_blocks[self._match_index])
        cursor = QTextCursor(block)
        cursor.select(QTextCursor.BlockUnderCursor)
        self._edit.setTextCursor(cursor)
        self._edit.centerCursor()

    def _apply_search_selections(self) -> None:
        """Highlight every search hit via extra selections."""
        query = self._search_text.lower().strip()
        self._match_blocks = []
        if not query:
            self._edit.setExtraSelections([])
            return
        palette = Theme.instance().palette()
        selection_format = QTextCharFormat()
        color = QColor(palette.warning)
        color.setAlpha(70)
        selection_format.setBackground(color)

        selections = []
        block = self._edit.document().firstBlock()
        while block.isValid():
            text = block.text().lower()
            if query in text:
                self._match_blocks.append(block.blockNumber())
                start = 0
                while True:
                    index = text.find(query, start)
                    if index < 0:
                        break
                    selection = QTextEdit.ExtraSelection()
                    cursor = QTextCursor(block)
                    cursor.setPosition(block.position() + index)
                    cursor.setPosition(block.position() + index + len(query),
                                       QTextCursor.KeepAnchor)
                    selection.cursor = cursor
                    selection.format = selection_format
                    selections.append(selection)
                    start = index + len(query)
            block = block.next()
        self._edit.setExtraSelections(selections)

    # ------------------------------------------------------------------ #
    # Scroll behaviour / fonts
    # ------------------------------------------------------------------ #

    def _at_bottom(self) -> bool:
        scrollbar = self._edit.verticalScrollBar()
        return scrollbar.value() >= scrollbar.maximum() - 4

    def _scroll_bottom(self) -> None:
        scrollbar = self._edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _toggle_wrap(self, checked: bool) -> None:
        self._edit.setLineWrapMode(QPlainTextEdit.WidgetWidth if checked
                                   else QPlainTextEdit.NoWrap)

    def _change_font(self, delta: int) -> None:
        self._mono_pt = max(6, min(16, self._mono_pt + delta))
        self._apply_fonts()

    def _apply_fonts(self) -> None:
        self._edit.setFont(Theme.instance().mono_font(self._mono_pt))

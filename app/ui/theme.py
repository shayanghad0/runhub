"""RunHub theme system.

Translates the design language from ``prompt/ui-master.md`` (VS Code /
Linear / Raycast inspired, dark + light mode, accent glow, rounded cards,
shadcn-style badges) into PyQt5 design tokens and a generated stylesheet.

Usage::

    theme = Theme.instance()
    theme.configure("dark", "Indigo")
    app.setStyleSheet(theme.stylesheet())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from string import Template

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QFont, QFontDatabase

from app.models.settings import ACCENTS

log = logging.getLogger(__name__)


def rgba(hex_color: str, alpha: float) -> str:
    """``#rrggbb`` + alpha float → ``rgba(r,g,b,a)`` string for QSS."""
    color = hex_color.lstrip("#")
    if len(color) != 6:
        return hex_color
    r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{round(alpha, 3)})"


def mix(a: str, b: str, ratio: float) -> str:
    """Blend two hex colors (``ratio`` = amount of ``b``)."""
    ca = a.lstrip("#")
    cb = b.lstrip("#")
    ra, ga, ba = (int(ca[i:i + 2], 16) for i in (0, 2, 4))
    rb, gb, bb = (int(cb[i:i + 2], 16) for i in (0, 2, 4))
    r = int(ra + (rb - ra) * ratio)
    g = int(ga + (gb - ga) * ratio)
    bl = int(ba + (bb - ba) * ratio)
    return f"#{r:02x}{g:02x}{bl:02x}"


@dataclass(frozen=True)
class Palette:
    """One complete set of design tokens."""

    name: str
    # Surfaces
    bg: str
    bg_panel: str
    surface: str
    surface2: str
    surface3: str
    border: str
    border_strong: str
    # Text
    text: str
    text_muted: str
    text_faint: str
    # Accent
    accent: str
    accent_hover: str
    accent_soft: str
    on_accent: str
    # Status
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    info: str
    # Misc
    scroll: str
    shadow: str
    glow: str


DARK = Palette(
    name="dark",
    bg="#0a0c10",
    bg_panel="#0d1017",
    surface="#11141b",
    surface2="#171b24",
    surface3="#1f2530",
    border="#1c222e",
    border_strong="#2a3140",
    text="#e8ebf2",
    text_muted="#98a2b8",
    text_faint="#5b6478",
    accent="#6366f1",
    accent_hover="#7c7ff5",
    accent_soft="rgba(99,102,241,0.16)",
    on_accent="#ffffff",
    success="#34d399",
    success_soft="rgba(52,211,153,0.14)",
    warning="#fbbf24",
    warning_soft="rgba(251,191,36,0.15)",
    danger="#f87171",
    danger_soft="rgba(248,113,113,0.15)",
    info="#38bdf8",
    scroll="#2a3140",
    shadow="rgba(0,0,0,0.45)",
    glow="#6366f1",
)

LIGHT = Palette(
    name="light",
    bg="#f4f6f9",
    bg_panel="#ffffff",
    surface="#ffffff",
    surface2="#eef1f6",
    surface3="#e3e7ef",
    border="#e2e6ee",
    border_strong="#ccd3e0",
    text="#101623",
    text_muted="#5b6577",
    text_faint="#98a1b3",
    accent="#6366f1",
    accent_hover="#5457e8",
    accent_soft="rgba(99,102,241,0.10)",
    on_accent="#ffffff",
    success="#16a34a",
    success_soft="rgba(22,163,74,0.10)",
    warning="#d97706",
    warning_soft="rgba(217,119,6,0.10)",
    danger="#dc2626",
    danger_soft="rgba(220,38,38,0.10)",
    info="#0284c7",
    scroll="#d4d9e3",
    shadow="rgba(15,23,42,0.12)",
    glow="#6366f1",
)

PALETTES = {"dark": DARK, "light": LIGHT}

_QSS_TEMPLATE = Template("""
* { outline: none; }
QWidget {
    background: transparent;
    color: $text;
    font-size: ${font_pt}pt;
}
QMainWindow, #Root { background: $bg; }
QWidget:disabled { color: $text_faint; }

/* ---------- Labels ---------- */
QLabel#Title    { font-size: 19px; font-weight: 600; }
QLabel#Subtitle { font-size: 13px; color: $text_muted; }
QLabel#Muted    { color: $text_muted; }
QLabel#Faint    { color: $text_faint; font-size: 11px; }
QLabel#Mono     { font-family: "$mono"; }
QLabel#Heading  { font-size: 14px; font-weight: 600; }
QLabel#Tiny     { font-size: 10px; color: $text_faint; }

/* ---------- Cards ---------- */
QFrame#Card {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#CardSection {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#HLine { border: none; border-top: 1px solid $border; max-height: 1px; }

/* ---------- Buttons ---------- */
QPushButton {
    background: $surface2;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px 12px;
    color: $text;
}
QPushButton:hover  { background: $surface3; border-color: $border_strong; }
QPushButton:pressed { background: $surface2; }
QPushButton:focus { border-color: $accent; }
QPushButton:disabled { color: $text_faint; background: $surface2; }
QPushButton#Primary {
    background: $accent; color: $on_accent; border: none; font-weight: 600;
}
QPushButton#Primary:hover { background: $accent_hover; }
QPushButton#Danger {
    background: $danger_soft; color: $danger; border: 1px solid $danger_soft;
}
QPushButton#Danger:hover { background: $danger; color: #ffffff; border-color: $danger; }
QPushButton#Ghost { background: transparent; border: none; }
QPushButton#Ghost:hover { background: $surface2; }
QToolButton { background: transparent; border: none; border-radius: 8px; padding: 4px; color: $text_muted; }
QToolButton:hover { background: $surface2; color: $text; }
QToolButton:checked { background: $accent_soft; color: $accent; }
QToolButton#Flat { border: none; }

/* ---------- Inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {
    background: $surface2;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus {
    border-color: $accent;
}
QLineEdit#Search {
    border-radius: 10px;
    padding: 7px 12px;
}
QComboBox {
    background: $surface2;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px 10px;
}
QComboBox:hover { border-color: $border_strong; }
QComboBox:focus { border-color: $accent; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: 8px;
    selection-background-color: $accent_soft;
    selection-color: $text;
    outline: none;
    padding: 4px;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid $border_strong; background: $surface2;
}
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }

/* ---------- Scrollbars ---------- */
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 4px 3px 4px 0;
}
QScrollBar::handle:vertical {
    background: $scroll; border-radius: 5px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: $border_strong; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 0 4px 3px 4px;
}
QScrollBar::handle:horizontal {
    background: $scroll; border-radius: 5px; min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: $border_strong; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollArea { border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }

/* ---------- Lists / tables ---------- */
QListWidget, QTableWidget, QTreeView {
    background: transparent;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 4px;
    outline: none;
}
QListWidget::item, QTreeView::item {
    border-radius: 8px; padding: 6px 8px; margin: 1px 2px;
}
QListWidget::item:selected, QTreeView::item:selected {
    background: $accent_soft; color: $text;
}
QListWidget::item:hover, QTreeView::item:hover { background: $surface2; }
QHeaderView::section {
    background: $surface2;
    color: $text_muted;
    border: none;
    border-bottom: 1px solid $border;
    padding: 6px 8px;
    font-size: 11px;
}
QTableWidget { gridline-color: $border; }

/* ---------- Menus / tooltips ---------- */
QMenu {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item { padding: 7px 26px 7px 12px; border-radius: 7px; }
QMenu::item:selected { background: $accent_soft; color: $text; }
QMenu::item:disabled { color: $text_faint; }
QMenu::separator { height: 1px; background: $border; margin: 5px 8px; }
QToolTip {
    background: $surface3;
    color: $text;
    border: 1px solid $border_strong;
    padding: 5px 9px;
    border-radius: 7px;
    font-size: 11px;
}

/* ---------- Log console ---------- */
QPlainTextEdit#LogConsole {
    background: $bg_panel;
    border: none;
    border-radius: 10px;
    padding: 8px;
    font-family: "$mono";
    font-size: ${mono_pt}pt;
}

/* ---------- Dock rail ---------- */
QWidget#DockRail { background: $bg_panel; border-right: 1px solid $border; }
QWidget#DockTab { background: transparent; border-radius: 10px; }
QWidget#DockTab:hover { background: $surface2; }

/* ---------- Status bar ---------- */
QWidget#StatusBar {
    background: $bg_panel;
    border-top: 1px solid $border;
}

/* ---------- Palette overlay ---------- */
QWidget#PaletteOverlay {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: 14px;
}

/* ---------- Progress / sliders ---------- */
QProgressBar {
    background: $surface2; border: none; border-radius: 4px;
    height: 8px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QSlider::groove:horizontal { background: $surface3; height: 6px; border-radius: 3px; }
QSlider::handle:horizontal {
    background: $accent; width: 16px; height: 16px; margin: -5px 0;
    border-radius: 8px;
}

/* ---------- Dialogs ---------- */
QDialog { background: $bg; }
QDialog QLabel#Heading { font-size: 15px; font-weight: 600; }

/* ---------- Splitter ---------- */
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 2px; }
""")


class Theme(QObject):
    """Global theme state + stylesheet factory (singleton)."""

    changed = pyqtSignal()

    _instance: Optional["Theme"] = None

    def __init__(self) -> None:
        super().__init__()
        self._mode = "dark"
        self._accent_name = "Indigo"
        self._font_pt = 10
        self._mono_pt = 9
        self._ui_family = "Segoe UI"
        self._mono_family = "Consolas"
        self._resolve_fonts()

    # ------------------------------------------------------------------ #

    @classmethod
    def instance(cls) -> "Theme":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def configure(self, mode: str, accent_name: str, font_pt: int = 10) -> None:
        """Apply mode/accent and notify listeners."""
        changed = (mode != self._mode or accent_name != self._accent_name
                   or font_pt != self._font_pt)
        self._mode = mode if mode in PALETTES else "dark"
        self._accent_name = accent_name if accent_name in ACCENTS else "Indigo"
        self._font_pt = max(8, min(14, font_pt))
        self._mono_pt = max(7, self._font_pt - 1)
        if changed:
            self.changed.emit()

    # ------------------------------------------------------------------ #
    # Tokens
    # ------------------------------------------------------------------ #

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_dark(self) -> bool:
        return self._mode == "dark"

    def palette(self) -> Palette:
        """Current palette with the accent color substituted in."""
        base = PALETTES[self._mode]
        accent = ACCENTS.get(self._accent_name, "#6366f1")
        hover = mix(accent, "#ffffff", 0.14 if self.is_dark else -0.12)
        if not self.is_dark:
            hover = mix(accent, "#000000", 0.12)
        soft = rgba(accent, 0.16 if self.is_dark else 0.10)
        return replace(
            base,
            accent=accent,
            accent_hover=hover,
            accent_soft=soft,
            glow=accent,
        )

    def token(self, name: str) -> str:
        """One token by attribute name."""
        return getattr(self.palette(), name)

    def color(self, name: str, alpha: float = 1.0) -> str:
        """Token as a QColor-friendly string (optionally with alpha)."""
        value = self.token(name)
        if alpha >= 1.0:
            return value
        return rgba(value, alpha)

    # ------------------------------------------------------------------ #
    # Stylesheet
    # ------------------------------------------------------------------ #

    def stylesheet(self) -> str:
        palette = self.palette()
        substitutions = dict(
            font_pt=self._font_pt,
            mono_pt=self._mono_pt,
            mono=self._mono_family,
            **{field: getattr(palette, field)
               for field in palette.__dataclass_fields__},
        )
        return _QSS_TEMPLATE.substitute(substitutions)

    # ------------------------------------------------------------------ #
    # Fonts
    # ------------------------------------------------------------------ #

    def _resolve_fonts(self) -> None:
        families = set(QFontDatabase().families()) if hasattr(QFontDatabase, "families") else set()
        try:
            families = set(QFontDatabase.families())
        except TypeError:
            families = set(QFontDatabase().families())
        for candidate in ("Segoe UI Variable Display", "Segoe UI", "SF Pro Text",
                          "Inter", "Ubuntu", "Noto Sans", "Helvetica Neue"):
            if candidate in families:
                self._ui_family = candidate
                break
        for candidate in ("Cascadia Code", "JetBrains Mono", "Fira Code",
                          "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"):
            if candidate in families:
                self._mono_family = candidate
                break
        log.debug("Fonts resolved: ui=%s mono=%s", self._ui_family, self._mono_family)

    def ui_font(self) -> QFont:
        font = QFont(self._ui_family, self._font_pt)
        font.setStyleHint(QFont.SansSerif)
        return font

    def mono_font(self, pt: int = 0) -> QFont:
        font = QFont(self._mono_family, pt or self._mono_pt)
        font.setStyleHint(QFont.Monospace)
        return font

    # ------------------------------------------------------------------ #
    # Convenience colors for painters
    # ------------------------------------------------------------------ #

    def status_color(self, status_value: str) -> str:
        """Color for a ProjectStatus value."""
        mapping = {
            "stopped": self.token("text_faint"),
            "starting": self.token("warning"),
            "running": self.token("success"),
            "stopping": self.token("warning"),
            "crashed": self.token("danger"),
            "error": self.token("danger"),
        }
        return mapping.get(status_value, self.token("text_muted"))

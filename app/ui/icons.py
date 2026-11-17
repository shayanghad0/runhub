"""SVG icon factory.

All icons are inline SVG strings (lucide-style, 24x24, stroke-based) that
get recolored by replacing ``currentColor`` and rendered through
``QSvgRenderer``. Results are cached per (name, color, size).

Every icon used anywhere in the UI must come from this module — the
design system mandates SVG icons only.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

from PyQt5.QtCore import QByteArray, QRectF, Qt, QUrl
from PyQt5.QtGui import QIcon, QGuiApplication, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QApplication

log = logging.getLogger(__name__)

_SVG_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'width="{size}" height="{size}">'
)

# --------------------------------------------------------------------------
# Icon definitions (inner SVG markup; `currentColor` is substituted).
# --------------------------------------------------------------------------

ICONS: Dict[str, str] = {
    # Brand
    "logo": (
        '<rect x="2.5" y="2.5" width="19" height="19" rx="5.5" fill="currentColor"/>'
        '<path d="M10 8.1v7.8l6.4-3.9z" fill="#ffffff"/>'
    ),
    # Playback
    "play": '<path d="M8 5.3v13.4l11-6.7z" fill="currentColor"/>',
    "stop": '<rect x="6.4" y="6.4" width="11.2" height="11.2" rx="1.6" fill="currentColor"/>',
    "restart": (
        '<path d="M20.5 12a8.5 8.5 0 1 1-2.5-6" stroke="currentColor" stroke-width="2"'
        ' fill="none" stroke-linecap="round"/>'
        '<path d="M18.5 2.5v4h-4" stroke="currentColor" stroke-width="2" fill="none"'
        ' stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "power": (
        '<path d="M12 3v8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'
        '<path d="M6.6 6.2a7.6 7.6 0 1 0 10.8 0" stroke="currentColor" stroke-width="2"'
        ' fill="none" stroke-linecap="round"/>'
    ),
    # Navigation / pages
    "grid": (
        '<rect x="3.5" y="3.5" width="7" height="7" rx="2" stroke="currentColor"'
        ' stroke-width="1.8" fill="none"/>'
        '<rect x="13.5" y="3.5" width="7" height="7" rx="2" stroke="currentColor"'
        ' stroke-width="1.8" fill="none"/>'
        '<rect x="3.5" y="13.5" width="7" height="7" rx="2" stroke="currentColor"'
        ' stroke-width="1.8" fill="none"/>'
        '<rect x="13.5" y="13.5" width="7" height="7" rx="2" stroke="currentColor"'
        ' stroke-width="1.8" fill="none"/>'
    ),
    "layers": (
        '<path d="M12 3.4 21 8l-9 4.6L3 8z" stroke="currentColor" stroke-width="1.8"'
        ' fill="none" stroke-linejoin="round"/>'
        '<path d="M3 12.4 12 17l9-4.6" stroke="currentColor" stroke-width="1.8"'
        ' fill="none" stroke-linejoin="round"/>'
        '<path d="M3 16.8 12 21.4l9-4.6" stroke="currentColor" stroke-width="1.8"'
        ' fill="none" stroke-linejoin="round"/>'
    ),
    "activity": (
        '<path d="M3.5 12h4l3-7.4 4 14.8 3-7.4h3" stroke="currentColor" stroke-width="1.9"'
        ' fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "sliders": (
        '<path d="M4 7h9M18.5 7H20M4 17h3M11.5 17H20" stroke="currentColor"'
        ' stroke-width="1.9" stroke-linecap="round"/>'
        '<circle cx="15.5" cy="7" r="2.4" stroke="currentColor" stroke-width="1.8" fill="none"/>'
        '<circle cx="9" cy="17" r="2.4" stroke="currentColor" stroke-width="1.8" fill="none"/>'
    ),
    # Files / folders
    "folder": (
        '<path d="M3.5 6.6a2 2 0 0 1 2-2h4l2.1 2.4h6.9a2 2 0 0 1 2 2v8.4a2 2 0 0 1-2 2h-13'
        'a2 2 0 0 1-2-2z" stroke="currentColor" stroke-width="1.8" fill="none"'
        ' stroke-linejoin="round"/>'
    ),
    "folder_open": (
        '<path d="M3.5 6.6a2 2 0 0 1 2-2h4l2.1 2.4h6.9a2 2 0 0 1 2 2v1.4H3.5z"'
        ' stroke="currentColor" stroke-width="1.8" fill="none" stroke-linejoin="round"/>'
        '<path d="M3.5 10.4h16.2l-1.7 8.2H5.2a1.7 1.7 0 0 1-1.7-1.7z"'
        ' stroke="currentColor" stroke-width="1.8" fill="none" stroke-linejoin="round"/>'
    ),
    "file_text": (
        '<path d="M6 3.2h7.5L18 7.7v13.1H6z" stroke="currentColor" stroke-width="1.8"'
        ' fill="none" stroke-linejoin="round"/>'
        '<path d="M13.5 3.4v4.4H18" stroke="currentColor" stroke-width="1.8" fill="none"/>'
        '<path d="M9 12.5h6M9 16h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
    ),
    # Actions
    "plus": '<path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "search": (
        '<circle cx="11" cy="11" r="6.4" stroke="currentColor" stroke-width="1.9" fill="none"/>'
        '<path d="m15.7 15.7 4.3 4.3" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>'
    ),
    "x": '<path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "x_circle": (
        '<circle cx="12" cy="12" r="8.4" stroke="currentColor" stroke-width="1.8" fill="none"/>'
        '<path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6" stroke="currentColor"'
        ' stroke-width="1.8" stroke-linecap="round"/>'
    ),
    "check": '<path d="M5 12.6 9.8 17.4 19 7.6" stroke="currentColor" stroke-width="2.1"'
             ' fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    "pencil": (
        '<path d="M4 20l1.2-4.4L16.6 4.2a2.2 2.2 0 0 1 3.2 3.2L8.4 18.8z"'
        ' stroke="currentColor" stroke-width="1.8" fill="none" stroke-linejoin="round"/>'
    ),
    "trash": (
        '<path d="M4.5 7h15M9.5 7V4.8h5V7M6.5 7l.9 12.4h9.2L17.5 7"'
        ' stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round"'
        ' stroke-linejoin="round"/>'
        '<path d="M10 11v5.5M14 11v5.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
    ),
    "copy": (
        '<rect x="9" y="9" width="11" height="11" rx="2.2" stroke="currentColor"'
        ' stroke-width="1.8" fill="none"/>'
        '<path d="M5.5 14.8V5.6a2 2 0 0 1 2-2h8" stroke="currentColor" stroke-width="1.8"'
        ' fill="none" stroke-linecap="round"/>'
    ),
    "external": (
        '<path d="M14 4h6v6M20 4l-8.6 8.6" stroke="currentColor" stroke-width="1.9"'
        ' fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M18.5 13.8v4.7a1.6 1.6 0 0 1-1.6 1.6H5.6a1.6 1.6 0 0 1-1.6-1.6V7.2'
        'a1.6 1.6 0 0 1 1.6-1.6h4.8" stroke="currentColor" stroke-width="1.9" fill="none"'
        ' stroke-linecap="round"/>'
    ),
    "arrow_right": (
        '<path d="M5 12h13M13 6.5 18.5 12 13 17.5" stroke="currentColor" stroke-width="1.9"'
        ' fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "chevron_right": '<path d="M9.2 5.6 15.6 12l-6.4 6.4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    "chevron_left": '<path d="M14.8 5.6 8.4 12l6.4 6.4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    "chevron_down": '<path d="M5.6 9.2 12 15.6l6.4-6.4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    # Workspace
    "globe": (
        '<circle cx="12" cy="12" r="8.4" stroke="currentColor" stroke-width="1.8" fill="none"/>'
        '<path d="M3.6 12h16.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
        '<path d="M12 3.6c2.7 2.7 2.7 13.9 0 16.8-2.7-2.9-2.7-14.1 0-16.8z"'
        ' stroke="currentColor" stroke-width="1.8" fill="none"/>'
    ),
    "terminal": (
        '<rect x="2.8" y="4.2" width="18.4" height="15.6" rx="2.6" stroke="currentColor"'
        ' stroke-width="1.8" fill="none"/>'
        '<path d="m6.6 9.4 2.6 2.6-2.6 2.6" stroke="currentColor" stroke-width="1.8"'
        ' fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M12.4 15h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
    ),
    "editor": (
        '<path d="M16.6 2.6 8.4 9.3 4.9 6.4 3 7.2v9.6l1.9.8 3.5-2.9 8.2 6.7 3.4-1.7V4.3z"'
        ' fill="currentColor"/>'
    ),
    "cpu": (
        '<rect x="6.4" y="6.4" width="11.2" height="11.2" rx="2.2" stroke="currentColor"'
        ' stroke-width="1.8" fill="none"/>'
        '<rect x="9.6" y="9.6" width="4.8" height="4.8" rx="1" fill="currentColor"/>'
        '<path d="M9 2.8v3.6M15 2.8v3.6M9 17.6v3.6M15 17.6v3.6M2.8 9h3.6M2.8 15h3.6M17.6 9h3.6M17.6 15h3.6"'
        ' stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
    ),
    "database": (
        '<ellipse cx="12" cy="5.6" rx="7.6" ry="2.9" stroke="currentColor" stroke-width="1.8" fill="none"/>'
        '<path d="M4.4 5.6v12.8c0 1.6 3.4 2.9 7.6 2.9s7.6-1.3 7.6-2.9V5.6"'
        ' stroke="currentColor" stroke-width="1.8" fill="none"/>'
        '<path d="M4.4 12c0 1.6 3.4 2.9 7.6 2.9s7.6-1.3 7.6-2.9"'
        ' stroke="currentColor" stroke-width="1.8" fill="none"/>'
    ),
    "zap": '<path d="M13.2 2.2 4.6 13.4h5.9L9.4 21.8 19.4 10h-6.2z" fill="currentColor"/>',
    "box": (
        '<path d="m12 2.8 8.2 4.6v9.2L12 21.2l-8.2-4.6V7.4z" stroke="currentColor"'
        ' stroke-width="1.8" fill="none" stroke-linejoin="round"/>'
        '<path d="M3.8 7.4 12 12l8.2-4.6M12 12v9.2" stroke="currentColor"'
        ' stroke-width="1.8" fill="none" stroke-linejoin="round"/>'
    ),
    "atom": (
        '<circle cx="12" cy="12" r="1.9" fill="currentColor"/>'
        '<ellipse cx="12" cy="12" rx="9" ry="3.7" stroke="currentColor" stroke-width="1.4" fill="none"/>'
        '<ellipse cx="12" cy="12" rx="9" ry="3.7" stroke="currentColor" stroke-width="1.4" fill="none"'
        ' transform="rotate(60 12 12)"/>'
        '<ellipse cx="12" cy="12" rx="9" ry="3.7" stroke="currentColor" stroke-width="1.4" fill="none"'
        ' transform="rotate(120 12 12)"/>'
    ),
    "hexagon": (
        '<path d="M12 2.6 20.2 7.3v9.4L12 21.4 3.8 16.7V7.3z" stroke="currentColor"'
        ' stroke-width="1.8" fill="none" stroke-linejoin="round"/>'
        '<circle cx="12" cy="12" r="2.6" fill="currentColor"/>'
    ),
    # UI chrome
    "star": (
        '<path d="m12 3.4 2.6 5.3 5.9.9-4.3 4.1 1 5.9-5.2-2.8-5.2 2.8 1-5.9-4.3-4.1 5.9-.9z"'
        ' fill="currentColor"/>'
    ),
    "star_outline": (
        '<path d="m12 3.4 2.6 5.3 5.9.9-4.3 4.1 1 5.9-5.2-2.8-5.2 2.8 1-5.9-4.3-4.1 5.9-.9z"'
        ' stroke="currentColor" stroke-width="1.7" fill="none" stroke-linejoin="round"/>'
    ),
    "filter": '<path d="M4 5h16l-6.2 7.3V19l-3.6 2v-8.7z" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linejoin="round"/>',
    "save": (
        '<path d="M5 4h11.4L20 7.6V20H5z" stroke="currentColor" stroke-width="1.8"'
        ' fill="none" stroke-linejoin="round"/>'
        '<path d="M8.4 4v4.8h7V4" stroke="currentColor" stroke-width="1.8" fill="none"/>'
        '<rect x="8.4" y="13.6" width="7.2" height="6.4" rx="1" stroke="currentColor"'
        ' stroke-width="1.8" fill="none"/>'
    ),
    "info": (
        '<circle cx="12" cy="12" r="8.4" stroke="currentColor" stroke-width="1.8" fill="none"/>'
        '<path d="M12 10.8v5.4" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>'
        '<circle cx="12" cy="7.8" r="1.1" fill="currentColor"/>'
    ),
    "warn": (
        '<path d="M12 3.4 21.4 20H2.6z" stroke="currentColor" stroke-width="1.8"'
        ' fill="none" stroke-linejoin="round"/>'
        '<path d="M12 9.4v4.8" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>'
        '<circle cx="12" cy="17.1" r="1.1" fill="currentColor"/>'
    ),
    "dot": '<circle cx="12" cy="12" r="4.4" fill="currentColor"/>',
    "clock": (
        '<circle cx="12" cy="12" r="8.4" stroke="currentColor" stroke-width="1.8" fill="none"/>'
        '<path d="M12 7.2V12l3.4 2" stroke="currentColor" stroke-width="1.8"'
        ' fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "list": (
        '<path d="M8.4 6.4H20M8.4 12H20M8.4 17.6H20" stroke="currentColor"'
        ' stroke-width="1.9" stroke-linecap="round"/>'
        '<circle cx="4.4" cy="6.4" r="1.2" fill="currentColor"/>'
        '<circle cx="4.4" cy="12" r="1.2" fill="currentColor"/>'
        '<circle cx="4.4" cy="17.6" r="1.2" fill="currentColor"/>'
    ),
    "keyboard": (
        '<rect x="2.6" y="6" width="18.8" height="12" rx="2.4" stroke="currentColor"'
        ' stroke-width="1.8" fill="none"/>'
        '<path d="M6 9.6h.01M9.4 9.6h.01M12.8 9.6h.01M16.2 9.6h.01M18 9.6h.01"'
        ' stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>'
        '<path d="M6.6 14.4h10.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
    ),
    "shield": (
        '<path d="M12 2.8 19.4 5.4v5.4c0 4.9-3.1 8.5-7.4 10.4-4.3-1.9-7.4-5.5-7.4-10.4V5.4z"'
        ' stroke="currentColor" stroke-width="1.8" fill="none" stroke-linejoin="round"/>'
    ),
    "download": (
        '<path d="M12 3.6v10.8M7 10l5 4.8L17 10" stroke="currentColor" stroke-width="1.9"'
        ' fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M4.4 20.4h15.2" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>'
    ),
    "upload": (
        '<path d="M12 14.4V3.6M7 8.4l5-4.8 5 4.8" stroke="currentColor" stroke-width="1.9"'
        ' fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M4.4 20.4h15.2" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>'
    ),
    "sun": (
        '<circle cx="12" cy="12" r="4.2" stroke="currentColor" stroke-width="1.8" fill="none"/>'
        '<path d="M12 2.6v2.6M12 18.8v2.6M2.6 12h2.6M18.8 12h2.6M5.4 5.4l1.8 1.8M16.8 16.8l1.8 1.8'
        'M18.6 5.4l-1.8 1.8M7.2 16.8l-1.8 1.8" stroke="currentColor" stroke-width="1.8"'
        ' stroke-linecap="round"/>'
    ),
    "moon": '<path d="M20.4 14.2A8.6 8.6 0 0 1 9.8 3.6a8.6 8.6 0 1 0 10.6 10.6z" fill="currentColor"/>',
    "command": (
        '<path d="M8.4 3.6a2.6 2.6 0 1 1-2.6 2.6h2.6V3.6zM15.6 3.6a2.6 2.6 0 1 0 2.6 2.6h-2.6V3.6z'
        'M8.4 20.4a2.6 2.6 0 1 0-2.6-2.6h2.6v2.6zM15.6 20.4a2.6 2.6 0 1 1 2.6-2.6h-2.6v2.6z'
        'M6.6 6.6h10.8v10.8H6.6z" stroke="currentColor" stroke-width="1.7" fill="none"/>'
    ),
    "refresh": (
        '<path d="M20.5 12a8.5 8.5 0 1 1-2.5-6" stroke="currentColor" stroke-width="2"'
        ' fill="none" stroke-linecap="round"/>'
        '<path d="M18.5 2.5v4h-4" stroke="currentColor" stroke-width="2" fill="none"'
        ' stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "pin": (
        '<path d="M12 3.4c3.6 0 6.4 2.6 6.4 6 0 4.6-6.4 11.2-6.4 11.2S5.6 14 5.6 9.4c0-3.4 2.8-6 6.4-6z"'
        ' stroke="currentColor" stroke-width="1.8" fill="none" stroke-linejoin="round"/>'
        '<circle cx="12" cy="9.4" r="2.4" stroke="currentColor" stroke-width="1.7" fill="none"/>'
    ),
    "scan": (
        '<path d="M3.6 8V5.4a1.8 1.8 0 0 1 1.8-1.8H8M16 3.6h2.6a1.8 1.8 0 0 1 1.8 1.8V8'
        'M20.4 16v2.6a1.8 1.8 0 0 1-1.8 1.8H16M8 20.4H5.4a1.8 1.8 0 0 1-1.8-1.8V16"'
        ' stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round"/>'
        '<path d="M6.6 12h10.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
    ),
    "pulse": (
        '<path d="M3.5 12h4l3-7.4 4 14.8 3-7.4h3" stroke="currentColor" stroke-width="1.9"'
        ' fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "rocket": (
        '<path d="M14.2 3.2c3.2 1 5.6 3.4 6.6 6.6l-3.4 1 -1 3.4c-2.6 2.2-5.6 3.4-8.4 3.6'
        'L5.6 20.4 3.6 18.4l2.6-2.4c.2-2.8 1.4-5.8 3.6-8.4l3.4-1z"'
        ' stroke="currentColor" stroke-width="1.7" fill="none" stroke-linejoin="round"/>'
        '<circle cx="14.6" cy="9.4" r="1.7" stroke="currentColor" stroke-width="1.6" fill="none"/>'
    ),
}

_SIZE_CACHE: Dict[Tuple[str, str, int, float], QPixmap] = {}


def _screen_dpr() -> float:
    """Device pixel ratio of the primary screen (quantized for the cache)."""
    try:
        screen = QGuiApplication.primaryScreen()
        ratio = float(screen.devicePixelRatio()) if screen is not None else 1.0
    except Exception:
        ratio = 1.0
    return max(1.0, round(ratio * 4) / 4)


def svg_bytes(name: str, color: str) -> bytes:
    """Compose the final SVG bytes for an icon name + color."""
    inner = ICONS.get(name, ICONS["box"])
    svg = f"{_SVG_HEAD}{inner}</svg>"
    return svg.replace("currentColor", color).encode("utf-8")


def pixmap(name: str, color: str, size: int = 18, dpr: float = 0.0) -> QPixmap:
    """Render an icon to a QPixmap (cached, high-DPI aware).

    ``dpr=0`` auto-detects the screen ratio so icons stay crisp at
    125 % / 150 % Windows display scaling.
    """
    if dpr <= 0.0:
        dpr = _screen_dpr()
    dpr = max(1.0, float(dpr))
    key = (name, color, size, round(dpr, 2))
    cached = _SIZE_CACHE.get(key)
    if cached is not None and not cached.isNull():
        return cached
    renderer = QSvgRenderer(QByteArray(svg_bytes(name, color)))
    target = QPixmap(int(size * dpr), int(size * dpr))
    target.setDevicePixelRatio(dpr)
    target.fill(Qt.transparent)
    painter = QPainter(target)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    if len(_SIZE_CACHE) > 2400:
        _SIZE_CACHE.clear()
    _SIZE_CACHE[key] = target
    return target


def icon(name: str, color: str = "#8b93a7", size: int = 18, dpr: float = 0.0) -> QIcon:
    """Build a QIcon for toolbars, buttons and lists."""
    pix = pixmap(name, color, size, dpr)
    return QIcon(pix)


def app_icon_path() -> Optional[str]:  # pragma: no cover - used for window icon
    return None


def install_app_icon(app) -> None:  # pragma: no cover
    """Set the application icon from the logo SVG."""
    try:
        app.setWindowIcon(icon("logo", "#6366f1", size=64))
    except Exception as exc:
        log.debug("app icon failed: %s", exc)

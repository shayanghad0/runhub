"""Application settings model.

Mirrors ``settings.json``. Unknown keys from older/newer versions are
ignored, missing keys fall back to defaults, so settings survive upgrades.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict

from app.utils.helpers import parse_bool

log = logging.getLogger(__name__)

THEME_DARK = "dark"
THEME_LIGHT = "light"

ACCENTS: Dict[str, str] = {
    "Indigo": "#6366f1",
    "Violet": "#8b5cf6",
    "Rose": "#f43f5e",
    "Emerald": "#10b981",
    "Cyan": "#06b6d4",
    "Amber": "#f59e0b",
}


@dataclass
class AppSettings:
    """User preferences persisted in ``settings.json``."""

    theme_mode: str = THEME_DARK
    accent_name: str = "Indigo"
    font_size: int = 10
    confirm_stop: bool = True
    confirm_quit_running: bool = True
    auto_open_browser: bool = True
    log_buffer_lines: int = 5000
    log_persist_lines: int = 2000
    monitor_interval_ms: int = 1500
    editor_path: str = ""          # discovered VS Code path ("" = auto)
    terminal_path: str = ""        # discovered terminal ("" = auto)
    plugins_enabled: Dict[str, bool] = field(default_factory=dict)
    window_geometry: str = ""      # QByteArray base64 of saved geometry
    first_run_done: bool = False

    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        return {
            "theme_mode": self.theme_mode,
            "accent_name": self.accent_name,
            "font_size": int(self.font_size),
            "confirm_stop": bool(self.confirm_stop),
            "confirm_quit_running": bool(self.confirm_quit_running),
            "auto_open_browser": bool(self.auto_open_browser),
            "log_buffer_lines": int(self.log_buffer_lines),
            "log_persist_lines": int(self.log_persist_lines),
            "monitor_interval_ms": int(self.monitor_interval_ms),
            "editor_path": self.editor_path,
            "terminal_path": self.terminal_path,
            "plugins_enabled": dict(self.plugins_enabled),
            "window_geometry": self.window_geometry,
            "first_run_done": bool(self.first_run_done),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        """Merge stored values over defaults; invalid values are ignored."""
        data = data if isinstance(data, dict) else {}
        settings = cls()

        mode = str(data.get("theme_mode") or THEME_DARK).lower()
        settings.theme_mode = mode if mode in (THEME_DARK, THEME_LIGHT) else THEME_DARK

        accent = str(data.get("accent_name") or "Indigo")
        settings.accent_name = accent if accent in ACCENTS else "Indigo"

        try:
            settings.font_size = max(8, min(14, int(data.get("font_size", 10))))
        except (TypeError, ValueError):
            pass
        for key in ("log_buffer_lines", "log_persist_lines", "monitor_interval_ms"):
            try:
                value = int(data.get(key) or getattr(settings, key))
            except (TypeError, ValueError):
                continue
            if key == "log_buffer_lines":
                settings.log_buffer_lines = max(500, min(50000, value))
            elif key == "log_persist_lines":
                settings.log_persist_lines = max(0, min(10000, value))
            else:
                settings.monitor_interval_ms = max(500, min(10000, value))

        settings.confirm_stop = parse_bool(data.get("confirm_stop"), True)
        settings.confirm_quit_running = parse_bool(data.get("confirm_quit_running"), True)
        settings.auto_open_browser = parse_bool(data.get("auto_open_browser"), True)
        settings.first_run_done = parse_bool(data.get("first_run_done"))

        settings.editor_path = str(data.get("editor_path") or "")
        settings.terminal_path = str(data.get("terminal_path") or "")
        settings.window_geometry = str(data.get("window_geometry") or "")

        plugins = data.get("plugins_enabled")
        if isinstance(plugins, dict):
            settings.plugins_enabled = {str(k): parse_bool(v, True) for k, v in plugins.items()}
        return settings

    # ------------------------------------------------------------------ #

    @property
    def accent(self) -> str:
        """Hex color for the configured accent."""
        return ACCENTS.get(self.accent_name, ACCENTS["Indigo"])

    def plugin_enabled(self, plugin_id: str, default: bool = True) -> bool:
        """Plugin toggle lookup (defaults to enabled)."""
        return parse_bool(self.plugins_enabled.get(plugin_id), default)

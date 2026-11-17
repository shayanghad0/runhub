"""Browser manager: port probing, URL detection and page opening.

* :meth:`is_port_open` — fast TCP probe against a localhost port.
* :meth:`wait_and_open` — background thread that waits for a dev server
  to come online, then (optionally) opens the browser automatically.
* Console output is scanned by :meth:`detect_urls` in the log manager,
  which feeds the per-project URL list shown in the project view.
"""

from __future__ import annotations

import logging
import re
import socket
import webbrowser
from typing import List, Optional

from PyQt5.QtCore import QObject, QThread, QUrl, Qt, pyqtSignal
from PyQt5.QtGui import QDesktopServices

from app.models.project import Project
from app.utils.helpers import is_free_port

log = logging.getLogger(__name__)

# Patterns for auto-detecting a port from project files (e.g. vite.config.ts).
_FILE_PORT_RE = re.compile(
    r"""port\s*[:=]\s*["']?(\d{2,5})["']?""", re.IGNORECASE
)


class PortWatcher(QThread):
    """Polls a port until it answers (or the timeout elapses)."""

    became_ready = pyqtSignal(str, int, bool)   # project_id, port, success

    def __init__(self, project_id: str, port: int, timeout: float = 45.0,
                 interval: float = 0.4, parent=None) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self.port = port
        self.timeout = timeout
        self.interval = interval
        self._stopping = False

    def run(self) -> None:  # noqa: D102
        deadline = __import__("time").time() + self.timeout
        success = False
        while not self._stopping:
            if is_free_port(self.port) is False:  # port answers → not free
                success = True
                break
            if __import__("time").time() > deadline:
                break
            __import__("time").sleep(self.interval)
        self.became_ready.emit(self.project_id, self.port, success)

    def shutdown(self) -> None:
        self._stopping = True


class BrowserManager(QObject):
    """Opens URLs and manages auto-open-on-ready behaviour."""

    port_ready = pyqtSignal(str, int, bool)   # project_id, port, success

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._watchers: List[PortWatcher] = []

    # ------------------------------------------------------------------ #
    # Port utilities
    # ------------------------------------------------------------------ #

    @staticmethod
    def is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
        """True when something accepts TCP connections on ``host:port``."""
        if not (0 < port < 65536):
            return False
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    @staticmethod
    def find_free_port(start: int = 8000, tries: int = 50) -> int:
        """First free port at/after ``start``."""
        port = start
        for _ in range(tries):
            if is_free_port(port):
                return port
            port += 1
        return start

    @staticmethod
    def detect_port_from_files(project_path: str) -> int:
        """Best-effort port sniffing in common config files."""
        from pathlib import Path

        root = Path(project_path)
        for name in ("vite.config.ts", "vite.config.js", "next.config.js",
                     "next.config.mjs", "webpack.config.js", "angular.json",
                     "quasar.config.js", "settings.py"):
            candidate = root / name
            if not candidate.is_file():
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")[:20000]
            except OSError:
                continue
            matches = [int(m) for m in _FILE_PORT_RE.findall(text) if 1 < int(m) < 65536]
            for port in matches:
                if port not in (80, 443, 8443, 5432, 3306, 6379, 27017):
                    return port
        return 0

    # ------------------------------------------------------------------ #
    # Opening
    # ------------------------------------------------------------------ #

    def open_url(self, url: str) -> bool:
        """Open ``url`` in the system browser."""
        if not url:
            return False
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        try:
            opened = QDesktopServices.openUrl(QUrl(url))
            if not opened:
                opened = webbrowser.open(url)
            log.info("Opened URL %s", url)
            return opened
        except Exception as exc:
            log.error("Cannot open browser for %s: %s", url, exc)
            return False

    def open_project(self, project: Project) -> bool:
        """Open the project's primary URL (if any)."""
        if not project.port:
            return False
        return self.open_url(f"http://localhost:{project.port}")

    def copy_url(self, url: str) -> bool:
        """Copy a URL to the clipboard."""
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None or not url:
            return False
        app.clipboard().setText(url)
        return True

    # ------------------------------------------------------------------ #
    # Auto-open on ready
    # ------------------------------------------------------------------ #

    def wait_and_open(self, project_id: str, port: int, timeout: float = 45.0,
                      open_when_ready: bool = True) -> None:
        """Start a background watcher; opens the browser when the port lives."""
        if not port:
            return
        watcher = PortWatcher(project_id, port, timeout=timeout)
        watcher.became_ready.connect(self._on_port_ready)
        watcher.finished.connect(lambda w=watcher: self._cleanup(w))
        self._watchers.append(watcher)
        watcher.start()
        if not open_when_ready:
            watcher._stopping = True  # probe only, no auto-open

    def _on_port_ready(self, project_id: str, port: int, success: bool) -> None:
        self.port_ready.emit(project_id, port, success)
        if success:
            self.open_url(f"http://localhost:{port}")

    def _cleanup(self, watcher: PortWatcher) -> None:
        try:
            self._watchers.remove(watcher)
        except ValueError:
            pass
        watcher.deleteLater()

    def shutdown(self) -> None:
        for watcher in list(self._watchers):
            watcher.shutdown()

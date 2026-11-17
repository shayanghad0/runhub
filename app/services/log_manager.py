"""Log manager: in-memory ring buffers + rolling JSON persistence.

Every project has a :class:`ProjectLog` ring buffer of :class:`LogRecord`
items. The manager:

* classifies lines into levels (INFO / WARN / ERROR / SYS / CMD),
* strips ANSI escape sequences,
* broadcasts records to the UI via Qt signals,
* periodically flushes a capped snapshot to ``logs.json`` and reloads it
  on startup so previous console output survives restarts.
"""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Tuple

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from app.core.database import Database
from app.utils.helpers import clock_stamp, strip_ansi

log = logging.getLogger(__name__)

# Levels
INFO, WARN, ERROR, SYS, CMD, DBG = "INFO", "WARN", "ERROR", "SYS", "CMD", "DBG"

_ERROR_HINTS = re.compile(
    r"\b(error|exception|traceback|failed|fatal|uncaught|segmentation|exit code [^0]\S*)\b",
    re.IGNORECASE,
)
_WARN_HINTS = re.compile(r"\b(warn(ing)?|deprecated|deprecation|slow query|retry)\b", re.IGNORECASE)
_URL_RE = re.compile(r"(?:https?://|localhost:|127\.0\.0\.1:)[^\s\"'<>]+", re.IGNORECASE)


@dataclass
class LogRecord:
    """One console line."""

    ts: float
    level: str
    source: str      # stdout | stderr | system
    text: str
    project_id: str = ""

    @property
    def stamp(self) -> str:
        return clock_stamp(self.ts)

    @property
    def short(self) -> str:
        return f"{self.stamp} {self.level:<5} {self.text}"

    def to_row(self) -> List:
        """Compact row for JSON persistence."""
        return [round(self.ts, 3), self.level, self.source, self.text]

    @classmethod
    def from_row(cls, row: List, project_id: str = "") -> "LogRecord":
        try:
            ts, level, source, text = row
            return cls(float(ts), str(level), str(source), str(text), project_id)
        except Exception:
            return cls(time.time(), INFO, "stdout", str(row), project_id)


def classify(text: str, source: str) -> str:
    """Heuristically assign a level to a console line."""
    if source == "system":
        return SYS
    if _ERROR_HINTS.search(text):
        return ERROR
    if _WARN_HINTS.search(text):
        return WARN
    return INFO


def extract_urls(text: str) -> List[str]:
    """Pull dev-server URLs out of a console line."""
    matches = _URL_RE.findall(text)
    cleaned = []
    for url in matches:
        url = url.rstrip(".,;)]}'\"")
        if url.startswith("localhost:"):
            url = "http://" + url
        if url not in cleaned:
            cleaned.append(url)
    return cleaned


class ProjectLog:
    """Ring buffer of records for one project."""

    def __init__(self, project_id: str, maxlen: int = 5000) -> None:
        self.project_id = project_id
        self.records: Deque[LogRecord] = deque(maxlen=max(200, maxlen))
        self.session_stats: Dict[str, int] = {}
        self.live_urls: List[str] = []

    def append(self, record: LogRecord) -> None:
        record.project_id = self.project_id
        self.records.append(record)
        self.session_stats[record.level] = self.session_stats.get(record.level, 0) + 1

    def search(self, query: str = "", levels: Optional[Iterable[str]] = None) -> List[LogRecord]:
        """Filtered view used by the log console search."""
        level_set = set(levels) if levels else None
        q = (query or "").lower()
        out = []
        for record in self.records:
            if level_set and record.level not in level_set:
                continue
            if q and q not in record.text.lower() and q not in record.stamp:
                continue
            out.append(record)
        return out

    def counts(self) -> Dict[str, int]:
        return dict(self.session_stats)

    def last(self, n: int = 1) -> List[LogRecord]:
        return list(self.records)[-n:]

    def clear(self) -> None:
        self.records.clear()
        self.session_stats.clear()


class LogManager(QObject):
    """Central log hub owned by the application."""

    record_added = pyqtSignal(str, object)     # project_id, LogRecord
    log_cleared = pyqtSignal(str)              # project_id
    urls_detected = pyqtSignal(str, list)      # project_id, [url, ...]

    FLUSH_MS = 8000

    def __init__(self, database: Database, buffer_lines: int = 5000, persist_lines: int = 2000):
        super().__init__()
        self.db = database
        self.buffer_lines = max(500, buffer_lines)
        self.persist_lines = max(0, persist_lines)
        self._logs: Dict[str, ProjectLog] = {}
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(self.FLUSH_MS)
        self._flush_timer.timeout.connect(self.flush)
        self._load_persisted()

    # ------------------------------------------------------------------ #
    # Access
    # ------------------------------------------------------------------ #

    def log_for(self, project_id: str) -> ProjectLog:
        """Get (or lazily create) the buffer for a project."""
        if project_id not in self._logs:
            self._logs[project_id] = ProjectLog(project_id, maxlen=self.buffer_lines)
        return self._logs[project_id]

    def forget(self, project_id: str) -> None:
        """Drop a project's buffer (project deleted)."""
        self._logs.pop(project_id, None)
        self.flush()

    # ------------------------------------------------------------------ #
    # Appending
    # ------------------------------------------------------------------ #

    def append(self, project_id: str, text: str, source: str = "stdout") -> None:
        """Record one or more lines and broadcast them."""
        text = strip_ansi(text.replace("\x00", ""))
        if not text.strip():
            return
        buffer = self.log_for(project_id)
        for line in text.splitlines() or [text]:
            line = line.rstrip()
            if not line:
                continue
            record = LogRecord(time.time(), classify(line, source), source, line, project_id)
            buffer.append(record)
            self.record_added.emit(project_id, record)
            urls = extract_urls(line)
            if urls:
                for url in urls:
                    if url not in buffer.live_urls:
                        buffer.live_urls.insert(0, url)
                buffer.live_urls = buffer.live_urls[:8]
                self.urls_detected.emit(project_id, list(buffer.live_urls))

    def system(self, project_id: str, text: str) -> None:
        """Append a RunHub system event (start/stop/...)."""
        self.append(project_id, text, source="system")

    def command(self, project_id: str, command: str) -> None:
        """Record the command that is about to run."""
        self.append(project_id, f"$ {command}", source="system")

    def clear(self, project_id: str) -> None:
        self.log_for(project_id).clear()
        self.log_cleared.emit(project_id)
        self.flush()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def _load_persisted(self) -> None:
        payload = self.db.logs.data() or {}
        for project_id, rows in payload.items():
            if not isinstance(rows, list):
                continue
            buffer = self.log_for(str(project_id))
            for row in rows[-self.persist_lines:] if self.persist_lines else []:
                buffer.records.append(LogRecord.from_row(row, str(project_id)))

    def flush(self) -> None:
        """Write capped snapshots of every buffer to logs.json."""
        if self.persist_lines <= 0:
            return
        payload = {}
        for project_id, buffer in self._logs.items():
            if buffer.records:
                payload[project_id] = [r.to_row() for r in list(buffer.records)[-self.persist_lines:]]
        self.db.logs.data().clear()
        self.db.logs.data().update(payload)
        self.db.logs.commit()

    def start(self) -> None:
        self._flush_timer.start()

    def stop(self) -> None:
        self._flush_timer.stop()
        self.flush()

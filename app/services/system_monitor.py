"""System monitor: CPU, RAM, disk and network statistics via psutil.

Runs a QTimer-driven sampler and emits a stats dict every tick. The UI
subscribes for the dashboard status bar and the full monitor page. When
psutil is unavailable the monitor degrades to a no-op so the rest of the
application keeps working.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Deque, Dict, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:      # pragma: no cover - psutil is a hard dependency in practice
    psutil = None        # type: ignore[assignment]
    PSUTIL_AVAILABLE = False

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from app.utils.filesystem import human_size

log = logging.getLogger(__name__)

HISTORY_LEN = 120


class SystemMonitor(QObject):
    """Polls system health and broadcasts it to the UI."""

    updated = pyqtSignal(dict)

    def __init__(self, interval_ms: int = 1500, parent=None) -> None:
        super().__init__(parent)
        self.available = PSUTIL_AVAILABLE
        self.interval_ms = max(500, interval_ms)
        self._timer: Optional[QTimer] = None
        self._last_net: Optional[Dict[str, int]] = None
        self._last_sample_ts: float = 0.0
        self.cpu_history: Deque[float] = deque(maxlen=HISTORY_LEN)
        self.mem_history: Deque[float] = deque(maxlen=HISTORY_LEN)
        self.net_history: Deque[float] = deque(maxlen=HISTORY_LEN)
        self._process_prev: Dict[int, float] = {}
        self._boot_time = psutil.boot_time() if self.available else 0

    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start sampling (idempotent)."""
        if not self.available:
            log.warning("psutil unavailable — system monitor disabled.")
            return
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setInterval(self.interval_ms)
            self._timer.timeout.connect(self.sample)
        self._timer.start()
        self.sample()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    def set_interval(self, ms: int) -> None:
        self.interval_ms = max(500, ms)
        if self._timer is not None:
            self._timer.setInterval(self.interval_ms)

    # ------------------------------------------------------------------ #

    def sample(self) -> Optional[Dict]:
        """Collect one sample and emit it. Returns the stats dict."""
        if not self.available:
            return None
        now = time.time()
        elapsed = max(0.05, now - self._last_sample_ts) if self._last_sample_ts else 1.0
        stats: Dict = {"ts": now, "uptime": now - self._boot_time}

        try:
            stats["cpu"] = psutil.cpu_percent(interval=None)
            stats["cpu_cores"] = psutil.cpu_count(logical=True) or 0
            stats["cpu_freq"] = self._cpu_freq()
        except Exception as exc:
            log.debug("cpu sample failed: %s", exc)

        try:
            memory = psutil.virtual_memory()
            stats["mem_used"] = memory.used
            stats["mem_total"] = memory.total
            stats["mem_pct"] = memory.percent
        except Exception as exc:
            log.debug("mem sample failed: %s", exc)

        try:
            disk = psutil.disk_usage(self._disk_root())
            stats["disk_used"] = disk.used
            stats["disk_total"] = disk.total
            stats["disk_pct"] = disk.percent
        except Exception as exc:
            log.debug("disk sample failed: %s", exc)

        try:
            net = psutil.net_io_counters()
            if self._last_net is not None and elapsed > 0:
                sent_rate = max(0, net.bytes_sent - self._last_net["sent"]) / elapsed
                recv_rate = max(0, net.bytes_recv - self._last_net["recv"]) / elapsed
            else:
                sent_rate = recv_rate = 0.0
            self._last_net = {"sent": net.bytes_sent, "recv": net.bytes_recv}
            stats["net_sent"] = sent_rate        # bytes / second
            stats["net_recv"] = recv_rate
            stats["net_total_sent"] = net.bytes_sent
            stats["net_total_recv"] = net.bytes_recv
        except Exception as exc:
            log.debug("net sample failed: %s", exc)

        self.cpu_history.append(stats.get("cpu", 0.0))
        self.mem_history.append(stats.get("mem_pct", 0.0))
        net_kbps = (stats.get("net_sent", 0) + stats.get("net_recv", 0)) / 1024.0
        self.net_history.append(net_kbps)

        self._last_sample_ts = now
        self.updated.emit(stats)
        return stats

    @staticmethod
    def _disk_root() -> str:
        if hasattr(psutil, "WINDOWS"):
            return "C:\\"
        return "/"

    @staticmethod
    def _cpu_freq() -> float:
        try:
            freq = psutil.cpu_freq()
            return freq.current if freq else 0.0
        except Exception:
            return 0.0

    # ------------------------------------------------------------------ #
    # Per-process metrics for RunHub-managed pids
    # ------------------------------------------------------------------ #

    def process_metrics(self, pids) -> Dict[int, Dict]:
        """CPU% / RSS for a set of pids (two-sample cpu_percent)."""
        out: Dict[int, Dict] = {}
        if not self.available:
            return out
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                cpu = proc.cpu_percent(interval=None)
                rss = proc.memory_info().rss
                create = proc.create_time()
                out[pid] = {
                    "cpu": cpu,
                    "rss": rss,
                    "uptime": time.time() - create,
                    "name": proc.name(),
                    "status": proc.status(),
                }
                self._process_prev[pid] = cpu
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                out[pid] = {"gone": True}
                self._process_prev.pop(pid, None)
            except Exception as exc:  # noqa: BLE001
                log.debug("process metric failed for %s: %s", pid, exc)
        return out

    # ------------------------------------------------------------------ #

    @staticmethod
    def format_rate(bytes_per_second: float) -> str:
        """Format a byte rate like ``1.2 MB/s``."""
        if bytes_per_second >= 1024 * 1024:
            return f"{bytes_per_second / 1048576:.1f} MB/s"
        if bytes_per_second >= 1024:
            return f"{bytes_per_second / 1024:.1f} KB/s"
        return f"{bytes_per_second:.0f} B/s"

    @staticmethod
    def format_uptime(seconds: float) -> str:
        days, rem = divmod(int(seconds), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        if days:
            return f"{days}d {hours}h"
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

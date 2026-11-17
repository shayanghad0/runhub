"""System monitor page: gauges, sparklines and managed process table."""

from __future__ import annotations

import logging
from typing import Dict, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.application import RunHubApplication
from app.services.system_monitor import PSUTIL_AVAILABLE
from app.ui.icons import icon
from app.ui.theme import Theme
from app.ui.widgets.sparkline import ArcGauge, Sparkline
from app.ui.widgets.stat_widgets import StatTile
from app.utils.filesystem import human_size
from app.utils.helpers import format_duration

log = logging.getLogger(__name__)


class MonitorPage(QWidget):
    """Live system health + RunHub process inventory."""

    def __init__(self, app: RunHubApplication, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self._last_stats: Dict = {}
        self._build()
        self.app.monitor.updated.connect(self._on_stats)
        self._refresh_processes()
        self.app.processes.state_changed.connect(lambda *_: self._refresh_processes())
        self.app.processes.exited.connect(lambda *_: self._refresh_processes())
        self.app.processes.aux_started.connect(lambda *_: self._refresh_processes())

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 10)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel("System monitor")
        title.setObjectName("Title")
        subtitle = QLabel("Live health of this machine and of every process RunHub manages.")
        subtitle.setObjectName("Muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        if not PSUTIL_AVAILABLE:
            warning = QLabel("psutil is not installed — run:  pip install psutil")
            warning.setObjectName("Faint")
            header.addWidget(warning)
        layout.addLayout(header)

        # Gauges row
        gauges = QHBoxLayout()
        gauges.setSpacing(12)
        self._cpu_gauge = ArcGauge("CPU")
        self._mem_gauge = ArcGauge("Memory")
        self._disk_gauge = ArcGauge("Disk")
        for gauge in (self._cpu_gauge, self._mem_gauge, self._disk_gauge):
            gauge.setFixedSize(150, 150)
            gauges.addWidget(gauge)
        gauges.addSpacing(8)

        self._net_tile = StatTile("activity", "Network I/O")
        self._net_tile.setFixedHeight(150)
        self._net_tile.setMinimumWidth(190)
        gauges.addWidget(self._net_tile)

        self._spark_cpu = Sparkline(color="#6366f1", height=150)
        self._spark_mem = Sparkline(color="#10b981", height=150)
        self._spark_net = Sparkline(color="#38bdf8", height=150, auto_scale=True)
        for spark, label in ((self._spark_cpu, "CPU history"),
                             (self._spark_mem, "Memory history"),
                             (self._spark_net, "Network history (KB/s)")):
            box = QVBoxLayout()
            caption = QLabel(label)
            caption.setObjectName("Faint")
            caption.setAlignment(Qt.AlignCenter)
            box.addWidget(caption)
            box.addWidget(spark, 1)
            gauges.addLayout(box)

        gauges.addStretch(1)
        layout.addLayout(gauges)

        # Process table
        table_header = QHBoxLayout()
        table_title = QLabel("Managed processes")
        table_title.setObjectName("Heading")
        table_header.addWidget(table_title)
        table_header.addStretch(1)
        refresh_button = QPushButton(" Refresh")
        refresh_button.setIcon(icon("restart", Theme.instance().token("text_muted"), 13))
        refresh_button.clicked.connect(self._refresh_processes)
        table_header.addWidget(refresh_button)
        layout.addLayout(table_header)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Project", "PID", "Type", "CPU %", "Memory", "Uptime", ""]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setMinimumHeight(220)
        layout.addWidget(self._table, 1)
        layout.addStretch(0)

        self._footnote = QLabel("")
        self._footnote.setObjectName("Faint")
        layout.addWidget(self._footnote)

    # ------------------------------------------------------------------ #

    def _on_stats(self, stats: Dict) -> None:
        self._last_stats = stats
        self._cpu_gauge.set_value(stats.get("cpu", 0.0),
                                  f"{stats.get('cpu_cores', '?')} cores")
        memory_used = stats.get("mem_used", 0)
        memory_total = stats.get("mem_total", 1) or 1
        self._mem_gauge.set_value(stats.get("mem_pct", 0.0),
                                  f"{human_size(memory_used)} / {human_size(memory_total)}")
        disk_used = stats.get("disk_used", 0)
        disk_total = stats.get("disk_total", 1) or 1
        self._disk_gauge.set_value(stats.get("disk_pct", 0.0),
                                   f"{human_size(disk_used)} / {human_size(disk_total)}")
        sent = stats.get("net_sent", 0)
        recv = stats.get("net_recv", 0)
        self._net_tile.set_value(
            f"↓{human_size(recv)}/s",
            sub=f"↑{human_size(sent)}/s   total ↓{human_size(stats.get('net_total_recv', 0))}"
        )
        self._spark_cpu.push(stats.get("cpu", 0.0))
        self._spark_mem.push(stats.get("mem_pct", 0.0))
        self._spark_net.push((sent + recv) / 1024.0)

    def _refresh_processes(self) -> None:
        """Rebuild the managed process table from live handles."""
        self._table.setRowCount(0)
        theme = Theme.instance()
        handles = self.app.processes.snapshot()
        if not handles:
            self._table.setRowCount(1)
            empty = QTableWidgetItem("No processes running — start a project from the dashboard.")
            empty.setForeground(Qt.gray)
            self._table.setItem(0, 0, empty)
            self._footnote.setText("")
            return

        pids = [h.popen.pid for h in handles]
        metrics = self.app.monitor.process_metrics(pids)
        for handle in handles:
            pid = handle.popen.pid
            metric = metrics.get(pid, {})
            if metric.get("gone"):
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)
            project = self.app.get_project(handle.project_id)
            name = project.name if project else handle.project_id
            kind = project.type if project else "—"
            label_item = QTableWidgetItem(name)
            self._table.setItem(row, 0, label_item)
            self._table.setItem(row, 1, QTableWidgetItem(str(pid)))
            self._table.setItem(row, 2, QTableWidgetItem(kind))
            self._table.setItem(row, 3, QTableWidgetItem(f"{metric.get('cpu', 0):.1f}"))
            self._table.setItem(row, 4, QTableWidgetItem(human_size(metric.get("rss", 0))))
            self._table.setItem(row, 5, QTableWidgetItem(format_duration(metric.get("uptime", 0))))
            stop_button = QPushButton("Stop")
            stop_button.setObjectName("Danger")
            stop_button.setFixedHeight(24)
            if handle.key.startswith("aux:"):
                stop_button.setText("Stop tool")
            stop_button.clicked.connect(
                lambda _, h=handle: self._stop_handle(h)
            )
            self._table.setCellWidget(row, 6, stop_button)
        self._footnote.setText(
            f"{len(pids)} process(es) • psutil {'available' if PSUTIL_AVAILABLE else 'missing'}"
        )

    def _stop_handle(self, handle) -> None:
        project_id = handle.project_id
        if handle.key.startswith("aux:"):
            self.app.processes.stop_aux(project_id, handle.key)
        else:
            project = self.app.get_project(project_id)
            if project:
                self.app.stop_project(project)
        self._refresh_processes()

"""Services package: process, log, browser, workspace, monitor and plugins."""

from app.services.browser_manager import BrowserManager  # noqa: F401
from app.services.log_manager import LogManager, LogRecord  # noqa: F401
from app.services.plugin_loader import PluginLoader  # noqa: F401
from app.services.process_manager import ProcessManager  # noqa: F401
from app.services.project_detector import ProjectDetector  # noqa: F401
from app.services.system_monitor import SystemMonitor  # noqa: F401
from app.services.workspace_manager import WorkspaceManager  # noqa: F401

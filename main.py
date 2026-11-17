"""RunHub — open-source developer workspace manager.

Entry point for the desktop application. Bootstraps the Qt application,
loads configuration, applies the theme system and opens the main window.

Usage:
    python main.py [--data-dir PATH] [--debug] [--version]

RunHub manages local development projects (React, Node, Python, FastAPI,
Django, Laravel, ...) from a single dashboard: start/stop/restart their
processes, watch live logs, jump to the browser and organize everything
into workspace profiles. All data is stored as plain JSON on disk.
"""

from __future__ import annotations

import argparse
import sys
import traceback

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

APP_NAME = "RunHub"
APP_VERSION = "1.0.0"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments for the application."""
    parser = argparse.ArgumentParser(
        prog="runhub",
        description="RunHub — a developer workspace manager for local projects.",
    )
    parser.add_argument(
        "--data-dir",
        metavar="PATH",
        default=None,
        help="Override the directory used for JSON storage (projects/settings/profiles/logs).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose console logging of internal events.",
    )
    parser.add_argument("--version", action="store_true", help="Print the version and exit.")
    return parser.parse_args(argv)


def _install_excepthook(window_holder: dict) -> None:
    """Route unexpected exceptions to a dialog instead of dying silently."""

    def hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        sys.stderr.write(text + "\n")
        window = window_holder.get("window")
        try:
            if window is not None and window.isVisible():
                QMessageBox.critical(
                    window,
                    "RunHub — unexpected error",
                    "An unexpected error occurred:\n\n" + str(exc_value) + "\n\n"
                    "Details were written to the console.",
                )
        except Exception:  # pragma: no cover - dialog must never crash the hook
            pass

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    """Application entry point."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.version:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0

    # High-DPI support must be configured before QApplication is created.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName("")   # don't append " - RunHub" to the window title
    app.setOrganizationName("RunHub")
    app.setApplicationVersion(APP_VERSION)

    # Local imports keep the module importable for tooling/tests without Qt running.
    from app.core.application import RunHubApplication
    from app.core.config_manager import ConfigManager
    from app.ui.icons import icon
    from app.ui.main_window import MainWindow
    from app.ui.theme import Theme

    config = ConfigManager(data_dir=args.data_dir, debug=args.debug)
    application = RunHubApplication(config)
    application.bootstrap()

    # Theme is applied as early as possible so the first paint is already styled.
    theme = Theme.instance()
    theme.configure(application.settings.theme_mode, application.settings.accent)
    app.setStyleSheet(theme.stylesheet())
    app.setFont(theme.ui_font())
    app.setWindowIcon(icon("logo", theme.token("accent"), size=64))

    window_holder: dict = {"window": None}
    _install_excepthook(window_holder)

    window = MainWindow(application)
    window_holder["window"] = window
    window.show()

    if args.debug:
        print(f"[runhub] data dir: {config.data_dir}")
        print(f"[runhub] projects loaded: {len(application.projects)}")

    return app.exec_()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # pragma: no cover
        traceback.print_exc()
        sys.exit(1)

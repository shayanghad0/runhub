"""Configuration and path management.

Resolves the application's data directory (JSON storage root), guarantees
that the required sub-directories exist and centralizes version constants.

Data directory resolution order:
    1. ``--data-dir`` command line argument
    2. ``RUNHUB_DATA_DIR`` environment variable
    3. ``<app root>/data`` when it is writable (portable / dev mode)
    4. ``~/.runhub`` (installed mode)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional, Union

from app.utils.filesystem import atomic_write_text, backup_file, ensure_directory, is_writable_dir

log = logging.getLogger(__name__)

APP_NAME = "RunHub"
APP_VERSION = "1.0.0"
DATA_VERSION = 1

# Collection file names (JSON database).
PROJECTS_FILE = "projects.json"
PROFILES_FILE = "profiles.json"
SETTINGS_FILE = "settings.json"
LOGS_FILE = "logs.json"


class ConfigError(Exception):
    """Raised when the configuration cannot be prepared."""


def app_root() -> Path:
    """Absolute path of the folder containing the ``app`` package."""
    return Path(__file__).resolve().parent.parent.parent


def default_data_dir() -> Path:
    """Best-guess default data directory for this environment."""
    env = os.environ.get("RUNHUB_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    local = app_root() / "data"
    if is_writable_dir(local) or (not local.exists() and _can_mkdir(local.parent)):
        return local
    return Path.home() / ".runhub"


def _can_mkdir(parent: Path) -> bool:
    try:
        parent.mkdir(parents=True, exist_ok=True)
        return os.access(parent, os.W_OK)
    except OSError:
        return False


class ConfigManager:
    """Owns paths, constants and low-level JSON IO for the application."""

    def __init__(self, data_dir: Optional[Union[str, Path]] = None, debug: bool = False) -> None:
        self.debug = debug
        self.app_root = app_root()
        try:
            self.data_dir = ensure_directory(
                Path(data_dir).expanduser() if data_dir else default_data_dir(),
                purpose="data directory",
            )
        except Exception as exc:  # last resort: temp dir
            import tempfile

            fallback = Path(tempfile.gettempdir()) / "runhub-data"
            log.error("Data dir unavailable (%s); falling back to %s", exc, fallback)
            self.data_dir = ensure_directory(fallback, purpose="fallback data directory")

        self.backup_dir = self.data_dir / "backups"
        self.plugin_dir = self.app_root / "plugins"

        # Logging setup — one file handler + console when debugging.
        self.log_file = self.data_dir / "runhub.log"
        self._configure_logging()

        log.info("RunHub %s | data dir: %s", APP_VERSION, self.data_dir)

    # ------------------------------------------------------------------ #
    # Logging
    # ------------------------------------------------------------------ #

    def _configure_logging(self) -> None:
        root = logging.getLogger()
        root.setLevel(logging.DEBUG if self.debug else logging.INFO)
        if not root.handlers:
            formatter = logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"
            )
            console = logging.StreamHandler(sys.stdout)
            console.setFormatter(formatter)
            root.addHandler(console)
            try:
                file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
                file_handler.setFormatter(
                    logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
                )
                root.addHandler(file_handler)
            except OSError:
                pass  # file logging is best-effort

    # ------------------------------------------------------------------ #
    # Paths
    # ------------------------------------------------------------------ #

    def collection_path(self, name: str) -> Path:
        """Absolute path of a JSON collection file (e.g. ``projects.json``)."""
        if name not in (PROJECTS_FILE, PROFILES_FILE, SETTINGS_FILE, LOGS_FILE):
            raise ConfigError(f"Unknown collection: {name}")
        return self.data_dir / name

    # ------------------------------------------------------------------ #
    # JSON IO
    # ------------------------------------------------------------------ #

    def read_json(self, path: Union[str, Path], default: Any = None) -> Any:
        """Read a JSON file; corrupted files are backed up and replaced by ``default``."""
        path = Path(path)
        if not path.is_file():
            return default
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.error("Corrupted JSON in %s (%s) — backing up and resetting.", path, exc)
            try:
                backup_file(path, self.backup_dir, keep=10)
            except Exception:
                pass
            return default
        except OSError as exc:
            log.error("Cannot read %s: %s", path, exc)
            return default

    def write_json(self, path: Union[str, Path], payload: Any) -> None:
        """Atomically serialize ``payload`` as pretty-printed JSON."""
        try:
            atomic_write_text(
                path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            )
        except OSError as exc:
            log.error("Cannot write %s: %s", path, exc)
            raise ConfigError(f"Cannot write {path}: {exc}") from exc

    def backup_collection(self, name: str) -> Optional[Path]:
        """Create a timestamped backup of one collection file."""
        return backup_file(self.collection_path(name), self.backup_dir, keep=5)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConfigManager data_dir={self.data_dir!r}>"

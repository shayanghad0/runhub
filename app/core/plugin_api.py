"""RunHub plugin API.

Plugins extend RunHub with:

* **Detection**      — ``detect(ctx)`` inspects a folder and reports which
  stack it belongs to, which command should run it and its default port.
* **Commands**       — long-running "tools" that appear in the project
  view (e.g. ``php artisan migrate``) and stream into the project logs.
* **UI actions**     — quick one-shot actions (open file, open docs, ...).

Write a plugin by creating ``plugins/<name>_plugin.py`` with a subclass of
:class:`BasePlugin` named ``Plugin``. The loader discovers it automatically.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------- #
# Detection context handed to plugins
# ---------------------------------------------------------------------- #

@dataclass
class DetectContext:
    """Everything a detector needs to inspect a candidate folder."""

    path: Path
    files: List[str] = field(default_factory=list)
    dirs: List[str] = field(default_factory=list)

    # ---------------------------------------------------------------- #

    @classmethod
    def scan(cls, path: Union[str, Path]) -> "DetectContext":
        """Build a context by listing the directory (one level deep)."""
        directory = Path(path)
        files, dirs = [], []
        try:
            for entry in sorted(directory.iterdir()):
                if entry.is_dir():
                    dirs.append(entry.name)
                else:
                    files.append(entry.name)
        except OSError as exc:
            log.debug("DetectContext.scan failed for %s: %s", directory, exc)
        return cls(path=directory, files=files, dirs=dirs)

    def has(self, name: str) -> bool:
        """True when a top-level file or directory exists."""
        return name in self.files or name in self.dirs

    def has_any(self, names: List[str]) -> bool:
        return any(self.has(name) for name in names)

    def has_matching_file(self, pattern: str) -> bool:
        """True when a top-level file matches a glob pattern (e.g. ``vite.config.*``)."""
        return any(fnmatch_simple(file_name, pattern) for file_name in self.files)

    def read_json(self, name: str) -> Optional[dict]:
        """Parse a top-level JSON file; returns None when missing/invalid."""
        target = self.path / name
        try:
            with open(target, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def read_text(self, name: str, limit: int = 6000) -> str:
        """Read the first ``limit`` chars of a top-level text file."""
        target = self.path / name
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as handle:
                return handle.read(limit)
        except OSError:
            return ""


def fnmatch_simple(name: str, pattern: str) -> bool:
    """Tiny glob matcher supporting ``*`` only (avoids fnmatch case issues)."""
    import re

    regex = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
    return re.match(regex, name, re.IGNORECASE) is not None


# ---------------------------------------------------------------------- #
# Specification records returned by plugins
# ---------------------------------------------------------------------- #

@dataclass
class CommandSpec:
    """A long-running tool command for a project (streams into its logs)."""

    id: str
    label: str
    command: str
    confirm: bool = False
    icon: str = "terminal"


@dataclass
class ActionSpec:
    """A quick UI action with a handler callable receiving the Project."""

    id: str
    label: str
    handler: Optional[Callable[[Any], None]] = None
    icon: str = "external"


@dataclass
class Detection:
    """Result of inspecting a folder."""

    kind: str                 # project type id, e.g. "react"
    command: str = ""
    port: int = 0
    name: str = ""            # suggested display name ("" = folder name)
    env: Dict[str, str] = field(default_factory=dict)
    meta: str = ""            # human explanation, shown in the import UI
    confidence: float = 0.5


# ---------------------------------------------------------------------- #
# Plugin base class
# ---------------------------------------------------------------------- #

class BasePlugin:
    """Contract every RunHub plugin implements.

    Class attributes describe the plugin and the project kind it owns.
    """

    id: str = "base"
    kind: str = "generic"
    name: str = "Base Plugin"
    version: str = "1.0.0"
    description: str = ""
    author: str = "RunHub"
    priority: int = 50          # lower = evaluated earlier
    builtin: bool = True

    label: str = "Project"      # display label for the kind
    color: str = "#8b93a7"      # accent used by type badges/icons
    icon: str = "box"
    default_port: int = 0

    # ---------------------------------------------------------------- #

    def detect(self, ctx: DetectContext) -> Optional[dict]:
        """Inspect ``ctx``; return a Detection payload dict or None."""
        return None

    def commands(self, project: Any) -> List[CommandSpec]:
        """Tool commands offered for ``project`` (may be empty)."""
        return []

    def actions(self, project: Any) -> List[ActionSpec]:
        """Quick actions offered for ``project`` (may be empty)."""
        return []

    def on_loaded(self, app: Any) -> None:
        """Called once after the plugin is registered."""

    def on_unloaded(self) -> None:
        """Called before the plugin is discarded (reload/exit)."""

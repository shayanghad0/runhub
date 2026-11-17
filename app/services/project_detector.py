"""Automatic project type detection.

Runs every enabled detector plugin against a folder and picks the highest
confidence result. Also exposes the plugin-contributed type registry used
by the UI (labels, icons, colors) and a recursive scanner used by the
"Scan folder…" bulk import.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.plugin_api import Detection
from app.models.project import TYPE_META, type_meta
from app.services.plugin_loader import PluginLoader
from app.utils.filesystem import iter_dirs

log = logging.getLogger(__name__)


@dataclass
class DetectionResult:
    """Detection outcome for one folder (possibly "no plugin matched")."""

    path: Path
    kind: str = "generic"
    command: str = ""
    port: int = 0
    name: str = ""
    env: Dict[str, str] = field(default_factory=dict)
    meta: str = ""
    confidence: float = 0.0
    plugin_id: str = ""

    @property
    def matched(self) -> bool:
        return self.kind != "generic" or bool(self.command)


class ProjectDetector:
    """Facade over the plugin-based detection engine."""

    def __init__(self, loader: PluginLoader) -> None:
        self.loader = loader
        self._meta_overrides: Dict[str, Dict[str, str]] = {}

    # ------------------------------------------------------------------ #
    # Detection
    # ------------------------------------------------------------------ #

    def detect(self, path: Path) -> DetectionResult:
        """Return the best detection for ``path`` (generic fallback)."""
        path = Path(path)
        if not path.is_dir():
            return DetectionResult(path=path, meta="Folder not found")

        from app.core.plugin_api import DetectContext

        ctx = DetectContext.scan(path)
        best: Optional[Tuple[float, str, dict]] = None
        for wrapper in self.loader.all_plugins():
            plugin = wrapper.plugin
            try:
                payload = plugin.detect(ctx)
            except Exception as exc:
                log.warning("detect() failed in plugin %s: %s", plugin.id, exc)
                continue
            if not payload:
                continue
            confidence = float(payload.get("confidence", 0.4))
            if best is None or confidence > best[0]:
                best = (confidence, plugin.id, payload)

        if best is None:
            return DetectionResult(path=path, kind="generic", meta="No stack detected")

        confidence, plugin_id, payload = best
        plugin = self.loader.get(plugin_id)
        return DetectionResult(
            path=path,
            kind=getattr(plugin, "kind", "generic") if plugin else "generic",
            command=str(payload.get("command") or ""),
            port=int(payload.get("port") or 0),
            name=str(payload.get("name") or ""),
            env=dict(payload.get("env") or {}),
            meta=str(payload.get("meta") or ""),
            confidence=confidence,
            plugin_id=plugin_id,
        )

    def scan_folder(self, root: Path, max_depth: int = 2) -> List[DetectionResult]:
        """Detect projects in ``root`` and its sub-folders (bulk import)."""
        results: List[DetectionResult] = []
        seen_paths = set()
        for directory in iter_dirs(Path(root), max_depth=max_depth):
            resolved = directory.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            result = self.detect(directory)
            if result.matched:
                results.append(result)
        results.sort(key=lambda r: (r.kind, r.path.name.lower()))
        return results

    # ------------------------------------------------------------------ #
    # Type registry (plugin-contributed UI metadata)
    # ------------------------------------------------------------------ #

    def refresh_meta(self) -> None:
        """Cache kind metadata from currently loaded plugins."""
        overrides: Dict[str, Dict[str, str]] = {}
        for wrapper in self.loader.all_plugins():
            plugin = wrapper.plugin
            kind = getattr(plugin, "kind", "")
            if not kind:
                continue
            overrides[kind] = {
                "label": getattr(plugin, "label", None) or type_meta(kind)["label"],
                "icon": getattr(plugin, "icon", None) or type_meta(kind)["icon"],
                "color": getattr(plugin, "color", None) or type_meta(kind)["color"],
            }
        self._meta_overrides = overrides

    def kinds(self) -> List[str]:
        """All registered kinds (plugins first, then builtin, generic last)."""
        kinds = list(self._meta_overrides.keys())
        for kind in TYPE_META:
            if kind not in kinds:
                kinds.append(kind)
        if "generic" in kinds:
            kinds.remove("generic")
            kinds.append("generic")
        return kinds

    def meta_for(self, kind: str) -> Dict[str, str]:
        """Display metadata for a kind (plugin override > builtin)."""
        if kind in self._meta_overrides:
            return self._meta_overrides[kind]
        return type_meta(kind)

    def default_port_for(self, kind: str) -> int:
        """Default dev-server port for a kind, if known."""
        plugin = next(
            (w.plugin for w in self.loader.all_plugins() if w.plugin.kind == kind), None
        )
        if plugin is not None and getattr(plugin, "default_port", 0):
            return int(plugin.default_port)
        return {"react": 5173, "node": 3000, "python": 8000,
                "fastapi": 8000, "django": 8000, "laravel": 8000}.get(kind, 0)

    def commands_for(self, kind: str, project=None):
        """Plugin tool commands for a project (used by the project view)."""
        plugin = next((w.plugin for w in self.loader.all_plugins() if w.plugin.kind == kind), None)
        if plugin is None:
            return []
        try:
            return plugin.commands(project) or []
        except Exception as exc:
            log.warning("commands() failed for plugin %s: %s", plugin.id, exc)
            return []

    def actions_for(self, kind: str, project=None):
        """Plugin quick actions for a project."""
        plugin = next((w.plugin for w in self.loader.all_plugins() if w.plugin.kind == kind), None)
        if plugin is None:
            return []
        try:
            return plugin.actions(project) or []
        except Exception as exc:
            log.warning("actions() failed for plugin %s: %s", plugin.id, exc)
            return []

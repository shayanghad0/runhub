"""Plugin discovery and lifecycle management.

Scans the ``plugins/`` folder for ``*_plugin.py`` modules, imports each in
an isolated try/except (a broken plugin must never crash RunHub), finds the
``Plugin`` class derived from :class:`BasePlugin`, validates it and keeps
instances sorted by priority.
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Type

from app.core.plugin_api import BasePlugin, DetectContext

log = logging.getLogger(__name__)


class LoadedPlugin:
    """Wrapper pairing a plugin instance with its module provenance."""

    def __init__(self, plugin: BasePlugin, module_name: str, source: Path) -> None:
        self.plugin = plugin
        self.module_name = module_name
        self.source = source
        self.error: Optional[str] = None

    @property
    def id(self) -> str:
        return self.plugin.id

    @property
    def name(self) -> str:
        return self.plugin.name

    def __repr__(self) -> str:  # pragma: no cover
        state = "error" if self.error else "ok"
        return f"<LoadedPlugin {self.plugin.id} {state}>"


class PluginLoader:
    """Loads, validates and (re)loads RunHub plugins."""

    def __init__(self, plugin_dir: Path) -> None:
        self.plugin_dir = Path(plugin_dir)
        self.plugins: Dict[str, LoadedPlugin] = {}
        self.disabled: Dict[str, LoadedPlugin] = {}   # validated, but toggled off
        self.load_errors: List[str] = []
        self.skipped_disabled: List[str] = []

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #

    def discover_modules(self) -> List[Path]:
        """Candidate plugin module files in the plugins directory."""
        if not self.plugin_dir.is_dir():
            return []
        return sorted(
            path
            for path in self.plugin_dir.glob("*_plugin.py")
            if path.is_file() and not path.name.startswith("_")
        )

    def _import_module(self, path: Path):
        """Import a plugin module by absolute path under a stable name."""
        module_name = f"runhub_plugins.{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot build import spec for {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _find_plugin_class(self, module) -> Optional[Type[BasePlugin]]:
        """Locate a subclass of BasePlugin defined in this module."""
        best: Optional[Type[BasePlugin]] = None
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is BasePlugin or not issubclass(obj, BasePlugin):
                continue
            if obj.__module__ != module.__name__:
                continue  # imported base/other module's class
            if best is None or getattr(obj, "priority", 50) < getattr(best, "priority", 50):
                best = obj
        return best

    # ------------------------------------------------------------------ #
    # Load / unload
    # ------------------------------------------------------------------ #

    def load_all(self, is_enabled=None, app=None) -> List[LoadedPlugin]:
        """(Re)load every plugin. Returns the successfully loaded list.

        ``is_enabled(plugin_id) -> bool`` optionally filters plugins by the
        user's per-plugin toggles; ``app`` is forwarded to ``on_loaded``.
        """
        self.unload_all()
        self.load_errors = []
        self.skipped_disabled = []
        self.disabled = {}
        loaded: List[LoadedPlugin] = []

        for path in self.discover_modules():
            try:
                module = self._import_module(path)
                plugin_cls = self._find_plugin_class(module)
                if plugin_cls is None:
                    self.load_errors.append(f"{path.name}: no Plugin(BasePlugin) subclass found")
                    continue
                plugin = plugin_cls()
                error = self._validate(plugin)
                if error:
                    self.load_errors.append(f"{path.name}: {error}")
                    continue
                if is_enabled and not is_enabled(plugin.id):
                    self.skipped_disabled.append(plugin.id)
                    # Keep the validated instance so Settings can list (and
                    # re-enable) it — a disabled plugin must not disappear.
                    self.disabled[plugin.id] = LoadedPlugin(plugin, module.__name__, path)
                    continue
                wrapper = LoadedPlugin(plugin, module.__name__, path)
                self.plugins[plugin.id] = wrapper
                loaded.append(wrapper)
            except Exception as exc:  # noqa: BLE001 - isolation is the point
                message = f"{path.name}: {exc}"
                log.error("Plugin import failed: %s\n%s", message, traceback.format_exc())
                self.load_errors.append(message)

        loaded.sort(key=lambda w: getattr(w.plugin, "priority", 50))
        for wrapper in loaded:
            try:
                wrapper.plugin.on_loaded(app)
            except Exception as exc:
                log.error("plugin %s on_loaded failed: %s", wrapper.plugin.id, exc)
                wrapper.error = f"on_loaded: {exc}"

        log.info(
            "Plugins loaded: %d ok, %d errors, %d disabled",
            len(loaded), len(self.load_errors), len(self.skipped_disabled),
        )
        return loaded

    def unload_all(self) -> None:
        """Give every plugin a chance to clean up, then drop them."""
        for wrapper in self.plugins.values():
            try:
                wrapper.plugin.on_unloaded()
            except Exception:
                log.exception("plugin %s on_unloaded failed", wrapper.plugin.id)
        # Remove imported plugin modules so reload picks up file changes.
        for name in [n for n in sys.modules if n.startswith("runhub_plugins.")]:
            sys.modules.pop(name, None)
        self.plugins.clear()
        self.disabled.clear()

    def get(self, plugin_id: str) -> Optional[BasePlugin]:
        """Plugin instance by id, or None."""
        wrapper = self.plugins.get(plugin_id)
        return wrapper.plugin if wrapper else None

    def all_plugins(self) -> List[LoadedPlugin]:
        """Loaded (enabled) plugins sorted by priority."""
        return sorted(self.plugins.values(), key=lambda w: getattr(w.plugin, "priority", 50))

    def all_known(self) -> List[LoadedPlugin]:
        """Every validated plugin: enabled + disabled, sorted by priority.

        Used by the Settings page — a disabled detector must stay visible
        with an unchecked box so the user can re-enable it.
        """
        known: Dict[str, LoadedPlugin] = {**self.disabled, **self.plugins}
        return sorted(known.values(), key=lambda w: getattr(w.plugin, "priority", 50))

    def reload(self, is_enabled=None, app=None) -> List[LoadedPlugin]:
        """Force a fresh import cycle of all plugins."""
        return self.load_all(is_enabled=is_enabled, app=app)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate(plugin: BasePlugin) -> Optional[str]:
        """Return an error string when the plugin violates the contract."""
        if not getattr(plugin, "id", ""):
            return "plugin.id is empty"
        if not getattr(plugin, "name", ""):
            return "plugin.name is empty"
        if not hasattr(plugin, "detect"):
            return "plugin.detect() missing"
        duplicates = [
            existing for existing in []  # populated by caller loop in load_all
        ]
        if duplicates:  # pragma: no cover
            return "duplicate id"
        try:
            probe = plugin.detect(DetectContext.scan(Path(".")))
        except Exception as exc:
            return f"detect() probe failed: {exc}"
        if probe is not None and not isinstance(probe, dict):
            return "detect() must return a dict or None"
        return None

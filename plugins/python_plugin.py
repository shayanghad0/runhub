"""Python detector plugin (generic Python projects, bots, scripts, CLIs)."""

from __future__ import annotations

import re
from typing import Optional

from app.core.plugin_api import BasePlugin, CommandSpec, DetectContext


class Plugin(BasePlugin):
    id = "python"
    kind = "python"
    name = "Python Detector"
    version = "1.0.0"
    description = "Detects Python projects via requirements.txt, pyproject.toml or entry scripts."
    priority = 30

    label = "Python"
    color = "#4b8bbe"
    icon = "code"
    default_port = 8000

    def detect(self, ctx: DetectContext) -> Optional[dict]:
        has_requirements = ctx.has("requirements.txt")
        has_pyproject = ctx.has("pyproject.toml")
        has_venv = any(name in ctx.dirs for name in (".venv", "venv", "env"))
        if not (has_requirements or has_pyproject or has_venv):
            # Fall through to entry-script sniffing below.
            pass

        entry = self._find_entry(ctx)
        port = self._sniff_port(ctx)

        if has_requirements or has_pyproject or has_venv or entry:
            env = {"PYTHONUNBUFFERED": "1"}
            return {
                "command": f"python {entry}" if entry else "",
                "port": port,
                "env": env,
                "meta": "Python project" + (" (entry: %s)" % entry if entry else ""),
                "confidence": 0.75 if entry else 0.5,
            }
        return None

    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_entry(ctx: DetectContext) -> str:
        """Most likely entry script in a Python project."""
        for candidate in ("main.py", "app.py", "run.py", "server.py", "bot.py",
                          "manage.py", "cli.py", "start.py"):
            if ctx.has(candidate):
                return candidate
        # Any top-level python file as a weak signal.
        py_files = [f for f in ctx.files if f.endswith(".py")]
        return py_files[0] if py_files else ""

    @staticmethod
    def _sniff_port(ctx: DetectContext) -> int:
        """Look for a literal port in the entry file or config."""
        for name in ("main.py", "app.py", "server.py", "bot.py", "config.py"):
            text = ctx.read_text(name, limit=8000)
            if not text:
                continue
            matches = re.findall(r"""port\s*=\s*["']?(\d{2,5})["']?""", text)
            for match in matches:
                port = int(match)
                if 1 < port < 65536 and port not in (80, 443, 5432, 3306):
                    return port
        return 0

    def commands(self, project) -> list:
        tools = []
        if project is not None:
            import os

            if os.path.isfile(os.path.join(project.path, "requirements.txt")):
                tools.append(CommandSpec(
                    id="pip-install", label="Install requirements",
                    command="pip install -r requirements.txt", confirm=True, icon="download",
                ))
        tools.append(CommandSpec(id="venv-create", label="Create venv",
                                 command="python -m venv .venv", confirm=True, icon="box"))
        return tools

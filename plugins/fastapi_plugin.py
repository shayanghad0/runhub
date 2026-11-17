"""FastAPI detector plugin — proposes ``uvicorn ... --reload``."""

from __future__ import annotations

import re
from typing import Optional

from app.core.plugin_api import BasePlugin, CommandSpec, DetectContext


class Plugin(BasePlugin):
    id = "fastapi"
    kind = "fastapi"
    name = "FastAPI Detector"
    version = "1.0.0"
    description = "Detects FastAPI projects and proposes the uvicorn dev command."
    priority = 15  # before the generic python detector

    label = "FastAPI"
    color = "#00a39a"
    icon = "zap"
    default_port = 8000

    def detect(self, ctx: DetectContext) -> Optional[dict]:
        requirements = ctx.read_text("requirements.txt", limit=20000)
        pyproject = ctx.read_text("pyproject.toml", limit=20000)
        haystack = (requirements or "") + (pyproject or "")
        declared = bool(re.search(r"(?m)^\s*(fastapi|uvicorn)\b", haystack, re.IGNORECASE))

        module = self._find_module(ctx)
        if not declared and not module:
            return None

        command = f"uvicorn {module} --reload" if module else ""
        return {
            "command": command,
            "port": 8000,
            "env": {},
            "meta": "FastAPI project (uvicorn)" + (f" — module {module}" if module else ""),
            "confidence": 0.9 if module else 0.6,
        }

    @staticmethod
    def _find_module(ctx: DetectContext) -> str:
        """Locate the ASGI app module: ``app.main:app``, ``main:app``, ..."""
        if ctx.has("app") and any(f == "main.py" for f in ctx.files) is False:
            pass
        # app/main.py layout
        if "app" in ctx.dirs:
            app_dir = ctx.path / "app"
            try:
                if (app_dir / "main.py").is_file():
                    return "app.main:app"
            except OSError:
                pass
        for candidate in ("main.py", "app.py", "server.py", "asgi.py"):
            text = ctx.read_text(candidate, limit=6000)
            if text and re.search(r"\bFastAPI\s*\(", text):
                stem = candidate[:-3]
                attr = "app"
                match = re.search(r"(\w+)\s*=\s*FastAPI\s*\(", text)
                if match:
                    attr = match.group(1)
                return f"{stem}:{attr}"
        return ""

    def commands(self, project) -> list:
        return [
            CommandSpec(id="install", label="Install requirements",
                        command="pip install -r requirements.txt", confirm=True, icon="download"),
        ]

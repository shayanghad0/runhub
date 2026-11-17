"""Django detector plugin."""

from __future__ import annotations

import re
from typing import Optional

from app.core.plugin_api import BasePlugin, CommandSpec, DetectContext


class Plugin(BasePlugin):
    id = "django"
    kind = "django"
    name = "Django Detector"
    version = "1.0.0"
    description = "Detects Django projects via manage.py and proposes runserver."
    priority = 12

    label = "Django"
    color = "#44b78b"
    icon = "database"
    default_port = 8000

    def detect(self, ctx: DetectContext) -> Optional[dict]:
        if not ctx.has("manage.py"):
            return None
        text = ctx.read_text("manage.py", limit=3000)
        is_django = "django" in (text or "").lower()
        port = 8000
        settings_py = self._find_settings(ctx)
        if settings_py:
            match = re.search(r"""port\s*=\s*["']?(\d{2,5})["']?""", settings_py)
            if match:
                port = int(match.group(1))
        return {
            "command": "python manage.py runserver",
            "port": port,
            "env": {},
            "meta": "Django project (manage.py)" + ("" if is_django else " — manage.py without django reference?"),
            "confidence": 0.95 if is_django else 0.6,
        }

    @staticmethod
    def _find_settings(ctx: DetectContext) -> str:
        for folder in ("", "config", "core", "src"):
            base = ctx.path / folder if folder else ctx.path
            candidate = base / "settings.py"
            try:
                if candidate.is_file():
                    return candidate.read_text(encoding="utf-8", errors="replace")[:12000]
            except OSError:
                continue
        return ""

    def commands(self, project) -> list:
        return [
            CommandSpec(id="migrate", label="Apply migrations",
                        command="python manage.py migrate", confirm=False, icon="database"),
            CommandSpec(id="makemigrations", label="Make migrations",
                        command="python manage.py makemigrations", icon="pencil"),
            CommandSpec(id="superuser", label="Create superuser",
                        command="python manage.py createsuperuser", confirm=True, icon="star"),
            CommandSpec(id="shell", label="Django shell",
                        command="python manage.py shell", icon="terminal"),
        ]

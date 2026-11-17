"""Laravel detector plugin."""

from __future__ import annotations

import json
import re
from typing import Optional

from app.core.plugin_api import BasePlugin, CommandSpec, DetectContext


class Plugin(BasePlugin):
    id = "laravel"
    kind = "laravel"
    name = "Laravel Detector"
    version = "1.0.0"
    description = "Detects Laravel projects via composer.json + artisan and proposes artisan serve."
    priority = 12

    label = "Laravel"
    color = "#f05340"
    icon = "layers"
    default_port = 8000

    def detect(self, ctx: DetectContext) -> Optional[dict]:
        if not ctx.has("composer.json"):
            return None
        composer = ctx.read_json("composer.json") or {}
        requires = {**(composer.get("require") or {}), **(composer.get("require-dev") or {})}
        is_laravel = "laravel/framework" in requires or ctx.has("artisan")
        if not is_laravel:
            return None

        env_text = ctx.read_text(".env", limit=4000)
        match = re.search(r"""^APP_PORT\s*=\s*(\d{2,5})\s*$""", env_text, re.MULTILINE)
        port = int(match.group(1)) if match else 8000
        php_version = (composer.get("require") or {}).get("php", "")
        name = composer.get("description") or ""
        return {
            "command": "php artisan serve",
            "port": port,
            "name": name if isinstance(name, str) and 0 < len(name) <= 40 else "",
            "env": {},
            "meta": "Laravel project (composer.json + artisan)"
                    + (f" — requires PHP {php_version}" if php_version else ""),
            "confidence": 0.95,
        }

    def commands(self, project) -> list:
        return [
            CommandSpec(id="composer-install", label="composer install",
                        command="composer install", confirm=True, icon="download"),
            CommandSpec(id="migrate", label="php artisan migrate",
                        command="php artisan migrate", confirm=True, icon="database"),
            CommandSpec(id="key-generate", label="php artisan key:generate",
                        command="php artisan key:generate", confirm=True, icon="zap"),
            CommandSpec(id="npm-install", label="npm install (assets)",
                        command="npm install", confirm=True, icon="box"),
            CommandSpec(id="npm-dev", label="npm run dev (vite)",
                        command="npm run dev", icon="atom"),
        ]

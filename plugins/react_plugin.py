"""React detector plugin.

Recognizes React applications: Vite, Next.js, Create React App, Remix and
plain ``package.json`` React projects. Proposes the canonical dev command
and the expected dev-server port.
"""

from __future__ import annotations

from typing import Optional

from app.core.plugin_api import BasePlugin, CommandSpec, DetectContext


class Plugin(BasePlugin):
    id = "react"
    kind = "react"
    name = "React Detector"
    version = "1.0.0"
    description = "Detects Vite, Next.js, CRA and Remix React apps."
    priority = 10

    label = "React"
    color = "#61dafb"
    icon = "atom"
    default_port = 5173

    def detect(self, ctx: DetectContext) -> Optional[dict]:
        package = ctx.read_json("package.json")
        if package is None:
            return None
        deps = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})}
        scripts = package.get("scripts") or {}
        dev_script = "dev" if "dev" in scripts else ("start" if "start" in scripts else "")

        # --- Vite ------------------------------------------------------ #
        if ctx.has_matching_file("vite.config.*") or "vite" in deps:
            return {
                "command": f"npm run {dev_script or 'dev'}",
                "port": 5173,
                "env": {"BROWSER": "none"},
                "meta": "Vite project (vite.config + package.json)",
                "confidence": 0.95,
            }

        # --- Next.js ---------------------------------------------------- #
        if ctx.has_matching_file("next.config.*") or "next" in deps:
            return {
                "command": f"npm run {dev_script or 'dev'}",
                "port": 3000,
                "env": {},
                "meta": "Next.js project",
                "confidence": 0.95,
            }

        # --- Remix ------------------------------------------------------ #
        if "remix" in deps or "@remix-run/react" in deps:
            return {
                "command": f"npm run {dev_script or 'dev'}",
                "port": 3000,
                "env": {},
                "meta": "Remix project",
                "confidence": 0.9,
            }

        # --- Create React App ------------------------------------------- #
        if "react-scripts" in deps:
            return {
                "command": "npm start",
                "port": 3000,
                "env": {"BROWSER": "none"},
                "meta": "Create React App project",
                "confidence": 0.9,
            }

        # --- Any React dependency ---------------------------------------- #
        if "react" in deps or "react-dom" in deps:
            return {
                "command": f"npm run {dev_script or 'dev'}",
                "port": 3000,
                "env": {},
                "meta": "React project (package.json)",
                "confidence": 0.7,
            }
        return None

    def commands(self, project) -> list:
        """Long-running tools for React projects."""
        return [
            CommandSpec(id="install", label="Install dependencies",
                        command="npm install", confirm=True, icon="download"),
            CommandSpec(id="build", label="Production build",
                        command="npm run build", confirm=False, icon="box"),
            CommandSpec(id="lint", label="Lint", command="npm run lint", icon="check"),
        ]

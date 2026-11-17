"""Node.js detector plugin (non-React JS backends, Express, Nest, ...)."""

from __future__ import annotations

from typing import Optional

from app.core.plugin_api import BasePlugin, CommandSpec, DetectContext


class Plugin(BasePlugin):
    id = "node"
    kind = "node"
    name = "Node.js Detector"
    version = "1.0.0"
    description = "Detects generic Node.js projects and proposes npm scripts."
    priority = 20

    label = "Node.js"
    color = "#8cc84b"
    icon = "hexagon"
    default_port = 3000

    def detect(self, ctx: DetectContext) -> Optional[dict]:
        package = ctx.read_json("package.json")
        if package is None:
            return None
        scripts = package.get("scripts") or {}
        deps = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})}
        name = str(package.get("name") or "")

        dev_script = ""
        for candidate in ("dev", "develop", "serve", "start"):
            if candidate in scripts:
                dev_script = candidate
                break

        # Framework hints for a nicer default port.
        port = 3000
        if "fastify" in deps:
            port = 3000
        elif "hapi" in deps or "@hapi/hapi" in deps:
            port = 3000
        elif "express" in deps or "koa" in deps:
            port = 3000
        elif "strapi" in deps:
            port = 1337

        if not dev_script:
            # No npm script — maybe a plain index/server file.
            for entry in ("index.js", "server.js", "app.js", "main.js"):
                if ctx.has(entry):
                    return {
                        "command": f"node {entry}",
                        "port": port,
                        "meta": f"Node.js project (entry {entry})",
                        "confidence": 0.6,
                    }
            return {
                "command": "",
                "port": port,
                "meta": "package.json found but no dev/start script — set a command",
                "confidence": 0.3,
            }

        return {
            "command": f"npm run {dev_script}",
            "port": port,
            "name": name.title() if name else "",
            "env": {},
            "meta": "Node.js project (package.json)",
            "confidence": 0.8,
        }

    def commands(self, project) -> list:
        return [
            CommandSpec(id="install", label="Install dependencies",
                        command="npm install", confirm=True, icon="download"),
            CommandSpec(id="test", label="Run tests", command="npm test", icon="check"),
        ]

"""Workspace manager: VS Code / terminal / file explorer integration.

Detects installed editors and terminals on Windows, macOS and Linux and
launches them detached from RunHub so closing RunHub never closes the
developer's tooling.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from app.utils.filesystem import ensure_can_execute, resolve_path

log = logging.getLogger(__name__)

DETACHED = 0x00000008 if os.name == "nt" else 0        # DETACHED_PROCESS
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class WorkspaceError(Exception):
    """User-facing workspace action failure."""


def detect_vscode() -> Optional[str]:
    """Locate the VS Code executable, or None when not installed."""
    which = shutil.which("code")
    if which:
        return which
    candidates: List[Path] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            Path(local) / "Programs" / "Microsoft VS Code" / "Code.exe" if local else None,
            Path("C:/Program Files/Microsoft VS Code/Code.exe"),
            Path("C:/Program Files (x86)/Microsoft VS Code/Code.exe"),
        ]
    elif sys.platform == "darwin":
        candidates = [Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")]
    else:
        candidates = [Path("/usr/bin/code"), Path("/usr/local/bin/code"), Path("/snap/bin/code")]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return str(candidate)
    # Try the popular OSS build before giving up.
    if sys.platform == "win32":
        fallback = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "VSCodium" / "VSCodium.exe"
        if fallback.is_file():
            return str(fallback)
    return None


def detect_terminals() -> List[Tuple[str, str]]:
    """Available terminal emulators as (id, label) pairs, best first."""
    found: List[Tuple[str, str]] = []
    if sys.platform == "win32":
        wt = shutil.which("wt")
        if wt:
            found.append(("wt", "Windows Terminal"))
        found.append(("cmd", "Command Prompt"))
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if pwsh:
            found.append(("pwsh", "PowerShell"))
        gitbash = shutil.which("bash")
        if gitbash and "git" in gitbash.lower():
            found.append(("gitbash", "Git Bash"))
    elif sys.platform == "darwin":
        found.append(("terminal", "Terminal.app"))
        if shutil.which("iTerm"):
            found.append(("iterm", "iTerm"))
    else:
        for name, label in (
            ("gnome-terminal", "GNOME Terminal"),
            ("konsole", "Konsole"),
            ("xfce4-terminal", "XFCE Terminal"),
            ("x-terminal-emulator", "Default terminal"),
            ("alacritty", "Alacritty"),
            ("kitty", "Kitty"),
            ("xterm", "XTerm"),
        ):
            if shutil.which(name):
                found.append((name, label))
    return found


class WorkspaceManager:
    """Open folders, files, editors and terminals for a project."""

    def __init__(self, editor_path: str = "", terminal_path: str = "") -> None:
        self._editor_override = editor_path
        self._terminal_override = terminal_path
        self._vscode_cache: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Editor (VS Code)
    # ------------------------------------------------------------------ #

    def vscode_path(self, refresh: bool = False) -> Optional[str]:
        """Resolved VS Code path (override setting beats auto-detection)."""
        if self._editor_override and Path(self._editor_override).is_file():
            return self._editor_override
        if self._vscode_cache is None or refresh:
            self._vscode_cache = detect_vscode()
        return self._vscode_cache

    def vscode_installed(self) -> bool:
        return self.vscode_path() is not None

    def open_in_vscode(self, path: str) -> bool:
        """Open a folder (or file) in VS Code / VSCodium."""
        target = resolve_path(path, must_exist=True)
        code = self.vscode_path(refresh=False)
        if code is None:
            raise WorkspaceError(
                "VS Code was not found. Install it or set the path in Settings → Integrations."
            )
        argv = [code]
        if sys.platform == "win32" and code.lower().endswith((".cmd", ".bat")):
            argv = ["cmd.exe", "/c", code]
        argv.append(str(target))
        try:
            subprocess.Popen(  # noqa: S603 - trusted local binary
                argv, close_fds=True,
                creationflags=DETACHED | NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            log.info("Opened %s in VS Code", target)
            return True
        except OSError as exc:
            raise WorkspaceError(f"Cannot launch VS Code: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Terminal
    # ------------------------------------------------------------------ #

    def open_terminal(self, path: str, terminal_id: str = "") -> bool:
        """Open a terminal at ``path``."""
        directory = ensure_can_execute(path)
        term = terminal_id or self._terminal_override
        if not term:
            terminals = detect_terminals()
            term = terminals[0][0] if terminals else ""
        try:
            if sys.platform == "win32":
                if term == "wt":
                    argv = ["wt.exe", "-d", str(directory)]
                    subprocess.Popen(argv, creationflags=DETACHED | NO_WINDOW)
                elif term == "gitbash":
                    bash = shutil.which("bash")
                    argv = ["cmd.exe", "/c", "start", "bash", "--login", "-i"]
                    subprocess.Popen(argv, cwd=str(directory), creationflags=NO_WINDOW)
                elif term == "pwsh":
                    pwsh = shutil.which("pwsh") or shutil.which("powershell")
                    argv = ["cmd.exe", "/c", "start", pwsh, "-NoExit", "-Command",
                            f"Set-Location -LiteralPath '{directory}'"]
                    subprocess.Popen(argv, cwd=str(directory), creationflags=NO_WINDOW)
                else:  # classic console
                    subprocess.Popen(
                        ["cmd.exe"], cwd=str(directory),
                        creationflags=subprocess.CREATE_NEW_CONSOLE | NO_WINDOW,
                    )
            elif sys.platform == "darwin":
                if term == "iterm":
                    subprocess.Popen(
                        ["open", "-a", "iTerm", str(directory)],
                        creationflags=0, start_new_session=True,
                    )
                else:
                    subprocess.Popen(
                        ["open", "-a", "Terminal", str(directory)], start_new_session=True
                    )
            else:
                commands = {
                    "gnome-terminal": [["gnome-terminal", f"--working-directory={directory}"]],
                    "konsole": [["konsole", "--workdir", str(directory)]],
                    "xfce4-terminal": [["xfce4-terminal", f"--working-directory={directory}"]],
                    "alacritty": [["alacritty", "--working-directory", str(directory)]],
                    "kitty": [["kitty", "--directory", str(directory)]],
                    "xterm": [["xterm", "-e", f"cd '{directory}' && exec $SHELL"]],
                }
                argv_list = commands.get(term) or [["x-terminal-emulator", f"--working-directory={directory}"]]
                subprocess.Popen(argv_list[0], start_new_session=True)
            log.info("Opened terminal (%s) at %s", term or "default", directory)
            return True
        except OSError as exc:
            raise WorkspaceError(f"Cannot open terminal: {exc}") from exc

    # ------------------------------------------------------------------ #
    # File explorer / default apps
    # ------------------------------------------------------------------ #

    def open_folder(self, path: str) -> bool:
        """Reveal a folder in the OS file manager."""
        directory = ensure_can_execute(path)
        try:
            if sys.platform == "win32":
                os.startfile(str(directory))  # type: ignore[attr-defined]  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(directory)], start_new_session=True)
            else:
                subprocess.Popen(["xdg-open", str(directory)], start_new_session=True)
            log.info("Opened folder %s", directory)
            return True
        except OSError as exc:
            raise WorkspaceError(f"Cannot open folder: {exc}") from exc

    def open_file(self, path: str) -> bool:
        """Open a file with its default application."""
        target = resolve_path(path, must_exist=True)
        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)], start_new_session=True)
            else:
                subprocess.Popen(["xdg-open", str(target)], start_new_session=True)
            return True
        except OSError as exc:
            raise WorkspaceError(f"Cannot open file: {exc}") from exc

    def install_status(self) -> dict:
        """Summary for the settings page."""
        return {
            "vscode": self.vscode_path(refresh=True),
            "terminals": detect_terminals(),
        }

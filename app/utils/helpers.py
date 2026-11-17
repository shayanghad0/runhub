"""General purpose helpers: commands, time, text processing and scoring.

This module contains the security-sensitive command parser used by the
process manager plus small pure helpers shared across the application.
"""

from __future__ import annotations

import logging
import re
import shlex
import shutil
import sys
import time
import uuid
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Identifiers / time
# --------------------------------------------------------------------------

def new_id() -> str:
    """Return a short unique identifier (used for projects and profiles)."""
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    """Current local time as an ISO-8601 string (seconds precision)."""
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def clock_stamp(ts: Optional[float] = None) -> str:
    """Return ``HH:MM:SS`` for a unix timestamp (default: now)."""
    return datetime.fromtimestamp(ts if ts is not None else time.time()).strftime("%H:%M:%S")


def format_duration(seconds: float) -> str:
    """Human friendly duration: ``1h 04m 12s`` / ``3m 05s`` / ``12s``."""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def format_timestamp(iso: str) -> str:
    """Format an ISO timestamp from storage as a short relative label."""
    if not iso:
        return "never"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    delta = datetime.now() - dt
    if delta.total_seconds() < 60:
        return "just now"
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() // 60)}m ago"
    if delta.total_seconds() < 86400:
        return f"{int(delta.total_seconds() // 3600)}h ago"
    return dt.strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------
# Command parsing / validation (security relevant)
# --------------------------------------------------------------------------

class CommandError(ValueError):
    """Raised when a command string fails validation or resolution."""


# Patterns that are always rejected, even in opt-in shell mode.
DANGEROUS_PATTERNS: Tuple[re.Pattern, ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\brm\s+-rf\s+/(?:\s|$)",          # rm -rf /
        r"\bdel\s+/[sq]",                    # del /s /q
        r"\brd\s+/s",                        # rd /s
        r"\bformat\b\s+[a-z]:",              # format c:
        r"\bshutdown\b",                     # shutdown
        r"\breboot\b",                       # reboot
        r"\bmkfs\b",                         # mkfs
        r"\bgit\s+push\s+.*--force\b",       # force push
        r":\(\)\s*\{.*\};:",                 # fork bomb
        r"\bdd\s+if=",                       # dd if=...
    )
)

# Shell metacharacters that indicate the command needs a shell interpreter.
SHELL_META = ("|", "&&", "||", ">", "<", "`", "$(")


def validate_command(text: str, allow_shell: bool = False) -> List[str]:
    """Validate a command string and return its argument tokens.

    Rules
    -----
    * The command must be non-empty and start with an executable name.
    * Shell metacharacters (``|``, ``&&``, ``>``, ``<`` ...) are rejected
      unless the caller explicitly opts into shell mode via ``allow_shell``.
    * A curated blocklist of destructive patterns is always rejected.
    """
    if text is None:
        raise CommandError("Command is empty.")
    text = text.strip()
    if not text:
        raise CommandError("Command is empty.")
    if "\n" in text or "\r" in text:
        raise CommandError("Command must be a single line.")
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(text):
            raise CommandError(f"Command rejected by safety policy: {pattern.pattern!r}")
    if not allow_shell and any(meta in text for meta in SHELL_META):
        raise CommandError(
            "Command contains shell metacharacters (| && > <). "
            "Enable 'Allow shell' on the project to use them."
        )
    try:
        tokens = shlex.split(text, posix=(sys.platform != "win32"))
    except ValueError as exc:
        raise CommandError(f"Cannot parse command: {exc}") from exc
    if not tokens:
        raise CommandError("Command is empty.")
    if tokens[0].startswith(("=", "~")):
        raise CommandError("Command must start with an executable name.")
    if sys.platform == "win32":
        # Non-POSIX mode keeps wrapping quotes as literal characters; the
        # list-argv API must receive unquoted tokens instead.
        tokens = [
            token[1:-1]
            if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'"
            else token
            for token in tokens
        ]
    return tokens


def resolve_command(text: str, allow_shell: bool = False) -> List[str]:
    """Validate ``text`` and resolve the executable against PATH.

    Returns a ready-to-run argv list. On Windows ``.cmd``/``.bat`` targets
    (e.g. ``npm.cmd``) are wrapped with ``cmd /c`` because CreateProcess
    cannot execute them directly — this keeps ``shell=False`` everywhere,
    which is the safe execution mode.
    """
    tokens = validate_command(text, allow_shell=allow_shell)
    head = tokens[0]

    if head in ("python", "python3", "python3.12") and not shutil.which(head):
        # Fall back to the interpreter running RunHub itself.
        resolved = sys.executable
    else:
        resolved = shutil.which(head)
        if resolved is None:
            raise CommandError(
                f"Executable '{head}' was not found on PATH. "
                "Install it or edit the project command."
            )

    if sys.platform == "win32" and resolved.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", resolved, *tokens[1:]]
    return [resolved, *tokens[1:]]


def env_var_name_ok(name: str) -> bool:
    """True when ``name`` is a valid environment variable name."""
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""))


def normalize_env(env: Optional[dict]) -> dict:
    """Validate/copy an environment mapping; invalid entries are dropped."""
    clean: dict = {}
    for key, value in (env or {}).items():
        if not env_var_name_ok(str(key)):
            log.warning("Dropping invalid env var name: %r", key)
            continue
        value = str(value).replace("\n", " ").replace("\r", " ")
        clean[str(key)] = value
    return clean


def env_to_lines(env: Optional[dict]) -> str:
    """Serialize an env dict to ``KEY=VALUE`` lines for editing."""
    return "\n".join(f"{k}={v}" for k, v in sorted((env or {}).items()))


def lines_to_env(text: str) -> Tuple[dict, List[str]]:
    """Parse ``KEY=VALUE`` lines into a dict; returns (env, error lines)."""
    env, errors = {}, []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            errors.append(line)
            continue
        key, _, value = line.partition("=")
        if not env_var_name_ok(key.strip()):
            errors.append(line)
            continue
        env[key.strip()] = value.strip()
    return env, errors


# --------------------------------------------------------------------------
# Text processing
# --------------------------------------------------------------------------

ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-B]|\x1b[=>]"
)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (colors, cursor moves) from ``text``."""
    return ANSI_ESCAPE_RE.sub("", text)


def elide(text: str, width: int) -> str:
    """Truncate ``text`` with an ellipsis so it never exceeds ``width``."""
    text = text or ""
    if len(text) <= width:
        return text
    if width <= 1:
        return "…"
    return text[: width - 1] + "…"


def fuzzy_score(query: str, text: str) -> int:
    """Simple subsequence fuzzy-match score (0 = no match).

    Higher is better. Consecutive matches and word-boundary matches score
    higher, which is enough for the command palette.
    """
    query, text = query.strip().lower(), (text or "").lower()
    if not query:
        return 1
    if query in text:
        return 1000 - text.index(query)  # substring: strongest signal
    score, cursor, streak = 0, 0, 0
    for ch in query:
        found = text.find(ch, cursor)
        if found < 0:
            return 0
        streak = streak + 1 if found == cursor else 1
        score += 2 + streak * 2 + (2 if found == 0 or text[found - 1] in " -_./\\" else 0)
        cursor = found + 1
    return score


def parse_bool(value, default: bool = False) -> bool:
    """Parse booleans arriving from JSON with mixed types."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into the closed interval ``[low, high]``."""
    return max(low, min(high, value))


def dedupe(items: Iterable[str]) -> List[str]:
    """Remove duplicates while preserving order."""
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def natural_key(text: str) -> list:
    """Sort key that orders embedded numbers naturally (v2 < v10)."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def is_free_port(port: int, host: str = "127.0.0.1") -> bool:
    """True when a TCP port is currently free on ``host``."""
    import socket

    if not (0 < port < 65536):
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False

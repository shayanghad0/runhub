"""Filesystem utilities: path validation, permission checks and atomic writes.

All filesystem operations performed by RunHub funnel through this module so
that security-relevant checks (existence, readability, writability, path
traversal) are applied consistently in one place.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Union

log = logging.getLogger(__name__)

PathLike = Union[str, os.PathLike]


class FilesystemError(Exception):
    """Raised when a filesystem operation is rejected by a safety check."""


# --------------------------------------------------------------------------
# Path handling
# --------------------------------------------------------------------------

def resolve_path(path: PathLike, must_exist: bool = True) -> Path:
    """Resolve a user supplied path to an absolute :class:`Path`.

    Raises :class:`FilesystemError` when the path is empty, points outside
    any valid filesystem root, or does not exist and ``must_exist`` is True.
    """
    raw = str(path).strip().strip('"')
    if not raw:
        raise FilesystemError("Path is empty.")
    candidate = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    if must_exist and not candidate.exists():
        raise FilesystemError(f"Path does not exist: {candidate}")
    return candidate


def is_within(child: Path, parent: Path) -> bool:
    """Return True when ``child`` is located inside ``parent`` (or equal)."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def ensure_directory(path: PathLike, purpose: str = "directory") -> Path:
    """Create a directory (recursively) if missing, verifying writability."""
    directory = resolve_path(path, must_exist=False)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FilesystemError(f"Cannot create {purpose} {directory}: {exc}") from exc
    if not os.access(directory, os.R_OK | os.W_OK | os.X_OK):
        raise FilesystemError(f"No read/write/execute permission for {directory}")
    return directory


def is_readable_dir(path: PathLike) -> bool:
    """True when the path exists, is a directory and can be listed."""
    directory = Path(path)
    if not directory.is_dir():
        return False
    try:
        os.access(directory, os.R_OK | os.X_OK)
        next(iter(directory.iterdir()), None)
        return True
    except OSError:
        return False


def is_writable_dir(path: PathLike) -> bool:
    """True when the directory exists and accepts a probe write."""
    directory = Path(path)
    if not directory.is_dir():
        return False
    try:
        probe = tempfile.NamedTemporaryFile(
            dir=str(directory), prefix=".runhub-probe-", delete=False
        )
        probe.close()
        os.unlink(probe.name)
        return True
    except OSError:
        return False


def unique_path(base: PathLike) -> Path:
    """Return ``base`` or ``base (2)``, ``base (3)`` ... if ``base`` exists."""
    candidate = Path(base)
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    parent = candidate.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    return parent / f"{stem} ({os.getpid()}){suffix}"


# --------------------------------------------------------------------------
# Directory scanning (used by the auto-detection bulk import)
# --------------------------------------------------------------------------

def iter_dirs(root: Path, max_depth: int = 2) -> Iterable[Path]:
    """Yield ``root`` and every sub-directory up to ``max_depth`` levels.

    Hidden directories, ``node_modules``, virtual environments and other
    build artefacts are skipped. Never raises on permission errors — the
    offending directory is simply skipped and logged.
    """
    SKIP_NAMES = {
        "node_modules", ".git", ".hg", ".svn", "__pycache__", ".venv", "venv",
        "env", ".idea", ".vscode", "dist", "build", ".tox", ".mypy_cache",
        ".pytest_cache", "vendor", "target", ".next", ".nuxt", "coverage",
    }
    root = Path(root)
    stack: List[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        yield current
        if depth >= max_depth:
            continue
        try:
            for entry in current.iterdir():
                if not entry.is_dir() or entry.name.startswith(".") or entry.name in SKIP_NAMES:
                    continue
                stack.append((entry, depth + 1))
        except OSError as exc:
            log.debug("Skipping directory %s: %s", current, exc)


def human_size(num_bytes: float) -> str:
    """Format a byte count as a human readable string."""
    value = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024.0
    return f"{value:,.1f} PB"


# --------------------------------------------------------------------------
# Atomic file IO
# --------------------------------------------------------------------------

def atomic_write_text(path: PathLike, text: str, encoding: str = "utf-8") -> Path:
    """Write ``text`` to ``path`` atomically (temp file + ``os.replace``).

    Guarantees that a crash mid-write cannot corrupt the previous content.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding=encoding,
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    )
    tmp_name = handle.name
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def backup_file(path: PathLike, backup_dir: PathLike, keep: int = 5) -> Optional[Path]:
    """Copy ``path`` into ``backup_dir`` with a timestamped name.

    Keeps at most ``keep`` newest backups. Returns the backup path or None
    when the source file does not exist.
    """
    import time

    source = Path(path)
    if not source.is_file():
        return None
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination = unique_path(backup_dir / f"{source.stem}-{stamp}{source.suffix}")
    try:
        shutil.copy2(source, destination)
    except OSError as exc:
        log.warning("Backup failed for %s: %s", source, exc)
        return None
    # Prune old backups.
    backups = sorted(backup_dir.glob(f"{source.stem}-*{source.suffix}"))
    for stale in backups[:-keep] if keep > 0 else []:
        try:
            stale.unlink()
        except OSError:
            pass
    return destination


def safe_filename(name: str, fallback: str = "untitled") -> str:
    """Sanitize a string so it can be used as a file name."""
    cleaned = "".join(
        ch if ch.isalnum() or ch in (" ", "-", "_", ".", "(", ")") else "_" for ch in name
    ).strip().strip(".")
    return cleaned or fallback


# --------------------------------------------------------------------------
# Permission helpers
# --------------------------------------------------------------------------

def ensure_can_execute(directory: PathLike) -> Path:
    """Verify a project directory is usable as a subprocess working dir.

    Returns the resolved directory or raises :class:`FilesystemError` with a
    message suitable for display in the UI.
    """
    directory = resolve_path(directory, must_exist=True)
    if not directory.is_dir():
        raise FilesystemError(f"Not a directory: {directory}")
    if not (os.access(directory, os.R_OK) and os.access(directory, os.X_OK)):
        raise FilesystemError(f"No read/execute permission for {directory}")
    return directory

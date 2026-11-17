"""Process manager: start / stop / restart / kill / monitor.

Each project runs as a ``subprocess.Popen`` handle with:

* safe argv construction (no shell unless explicitly allowed),
* dedicated :class:`StreamReader` QThreads for stdout/stderr feeding the
  log manager via queued Qt signals,
* a :class:`ProcessWatcher` thread that polls the exit code,
* graceful termination of the whole process tree through psutil with a
  configurable grace period before SIGKILL / ``terminate()``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import psutil
from PyQt5.QtCore import QObject, QThread, QTimer, pyqtSignal

from app.models.project import Project, ProjectStatus
from app.services.log_manager import LogManager
from app.utils.helpers import CommandError, format_duration, normalize_env, resolve_command
from app.utils.filesystem import ensure_can_execute

log = logging.getLogger(__name__)

_START_GRACE = 5.0     # seconds: exit within this window counts as a crash
_STOP_GRACE = 8.0      # seconds before force-kill
_AUX_PREFIX = "aux:"   # key prefix for plugin tool commands


class StreamReader(QThread):
    """Reads one pipe of a child process and forwards lines as Qt signals."""

    line_received = pyqtSignal(str, str)   # text, source

    def __init__(self, stream, source: str, encoding: str = "utf-8", parent=None) -> None:
        super().__init__(parent)
        self._stream = stream
        self._source = source
        self._encoding = encoding
        self._stopping = False

    def run(self) -> None:  # noqa: D102
        try:
            for raw in iter(self._stream.readline, b""):
                if self._stopping:
                    break
                text = raw.decode(self._encoding, errors="replace").rstrip("\r\n")
                if text:
                    self.line_received.emit(text, self._source)
        except (OSError, ValueError):
            pass  # stream closed while stopping
        finally:
            try:
                self._stream.close()
            except Exception:
                pass

    def shutdown(self) -> None:
        """Ask the loop to finish; closing the pipe unblocks readline."""
        self._stopping = True
        try:
            self._stream.close()
        except Exception:
            pass


class ProcessWatcher(QThread):
    """Polls a Popen handle and emits ``exited`` with its return code."""

    exited = pyqtSignal(int, int)   # pid, return code

    def __init__(self, popen: subprocess.Popen, parent=None) -> None:
        super().__init__(parent)
        self._popen = popen
        self._stopping = False

    def run(self) -> None:  # noqa: D102
        while not self._stopping:
            code = self._popen.poll()
            if code is not None:
                self.exited.emit(self._popen.pid, code)
                return
            time.sleep(0.2)

    def shutdown(self) -> None:
        self._stopping = True


class Stopper(QThread):
    """Terminates a process tree off the UI thread."""

    finished_stop = pyqtSignal(int, bool)   # pid, force-killed

    def __init__(self, popen: subprocess.Popen, grace: float = _STOP_GRACE, parent=None) -> None:
        super().__init__(parent)
        self._popen = popen
        self._grace = grace

    def run(self) -> None:  # noqa: D102
        force = self._terminate_tree(self._popen, self._grace)
        self.finished_stop.emit(self._popen.pid, force)

    @staticmethod
    def _terminate_tree(popen: subprocess.Popen, grace: float) -> bool:
        """Terminate ``popen`` and all descendants. Returns True if force-killed."""
        try:
            root = psutil.Process(popen.pid)
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            try:
                popen.terminate()
            except OSError:
                pass
            return False

        try:
            victims = [root, *root.children(recursive=True)]
        except psutil.NoSuchProcess:
            victims = [root]

        for victim in victims:
            try:
                victim.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        _, alive = psutil.wait_procs(victims, timeout=max(0.5, grace))
        force = bool(alive)
        for victim in alive:
            try:
                victim.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            psutil.wait_procs(alive, timeout=3)
        except Exception:  # pragma: no cover
            pass
        return force


@dataclass
class ProcessHandle:
    """Bookkeeping for one running (or stopping) process."""

    project_id: str
    key: str
    popen: subprocess.Popen
    command: str
    argv: List[str]
    started_at: float = field(default_factory=time.time)
    user_stop: bool = False
    finalized: bool = False
    readers: List[StreamReader] = field(default_factory=list)
    watcher: Optional[ProcessWatcher] = None

    @property
    def pid(self) -> int:
        return self._pid() or -1

    def _pid(self) -> Optional[int]:
        return self.popen.pid

    def uptime(self) -> float:
        return time.time() - self.started_at

    def alive(self) -> bool:
        return self.popen.poll() is None


class ProcessError(Exception):
    """User-facing process failure (shown as toast / log line)."""


class ProcessManager(QObject):
    """Owns every child process started by RunHub."""

    state_changed = pyqtSignal(str, str)        # project_id, status value
    output = pyqtSignal(str, str, str)          # project_id, text, source
    exited = pyqtSignal(str, int, bool)         # project_id, code, user_stop
    failed = pyqtSignal(str, str)               # project_id, error message
    aux_started = pyqtSignal(str, str)          # project_id, aux key
    aux_exited = pyqtSignal(str, str, int)      # project_id, aux key, code

    def __init__(self, log_manager: LogManager, parent=None) -> None:
        super().__init__(parent)
        self.logs = log_manager
        self._handles: Dict[str, ProcessHandle] = {}      # key -> handle
        self._stoppers: Dict[int, Stopper] = {}           # pid -> stopper (kept alive while running)
        self._project_status: Dict[str, ProjectStatus] = {}
        self._pending_restart: Dict[str, bool] = {}
        self._pending_start: Dict[str, Project] = {}      # id -> project queued for delayed start
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(self._start_queued)

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    def status(self, project_id: str) -> ProjectStatus:
        return self._project_status.get(project_id, ProjectStatus.STOPPED)

    def is_running(self, project_id: str) -> bool:
        handle = self._handles.get(project_id)
        return handle is not None and handle.alive()

    def running_ids(self) -> List[str]:
        return [key for key, handle in self._handles.items() if handle.alive()]

    def handle_for(self, project_id: str) -> Optional[ProcessHandle]:
        return self._handles.get(project_id)

    def _set_status(self, project_id: str, status: ProjectStatus) -> None:
        if self._project_status.get(project_id) is status:
            return
        self._project_status[project_id] = status
        self.state_changed.emit(project_id, status.value)

    # ------------------------------------------------------------------ #
    # Start
    # ------------------------------------------------------------------ #

    def start(self, project: Project, delay_ms: int = 0) -> bool:
        """Start a project's main command.

        When ``delay_ms`` > 0 the start is queued (used by profile stagger).
        Returns False (with a toast-worthy signal) when validation fails.
        """
        if delay_ms > 0:
            self._pending_start[project.id] = project
            self._start_timer.start(delay_ms)
            return True
        return self._start_now(project)

    def _start_queued(self) -> None:
        pending = self._pending_start
        self._pending_start = {}
        for project in pending.values():
            self._start_now(project)

    def _start_now(self, project: Project) -> bool:
        key = project.id
        if self.is_running(project.id):
            self.logs.system(project.id, "Already running.")
            return False
        if key in self._handles:  # zombie handle from a stopping process
            self._release_handle(key, join=False)

        try:
            argv = resolve_command(project.command, allow_shell=project.allow_shell)
            cwd = ensure_can_execute(project.path)
        except (CommandError, Exception) as exc:
            message = str(exc)
            self.logs.system(project.id, f"Start failed: {message}")
            self._set_status(project.id, ProjectStatus.ERROR)
            self.failed.emit(project.id, message)
            return False

        env = os.environ.copy()
        env.update(normalize_env(project.env))
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("RUNHUB", "1")
        env.setdefault("TERM", "dumb")
        env["RUNHUB_PROJECT"] = project.name

        creationflags = 0
        start_new_session = False
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
        else:
            start_new_session = True

        display_cmd = " ".join(argv)
        self.logs.command(project.id, display_cmd)
        try:
            popen = subprocess.Popen(  # noqa: S603 - argv validated above
                argv,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
        except OSError as exc:
            message = f"Could not launch process: {exc}"
            self.logs.system(project.id, f"Start failed: {message}")
            self._set_status(project.id, ProjectStatus.ERROR)
            self.failed.emit(project.id, message)
            return False

        handle = ProcessHandle(project_id=project.id, key=key, popen=popen,
                               command=project.command, argv=argv)
        for stream, source in ((popen.stdout, "stdout"), (popen.stderr, "stderr")):
            if stream is None:
                continue
            reader = StreamReader(stream, source)
            reader.line_received.connect(self._on_line)
            handle.readers.append(reader)
            reader.start()

        watcher = ProcessWatcher(popen)
        watcher.exited.connect(self._on_exited)
        handle.watcher = watcher
        watcher.start()

        self._handles[key] = handle
        self._set_status(project.id, ProjectStatus.RUNNING)
        self.logs.system(project.id, f"Started (pid {popen.pid})")
        project.mark_started()
        return True

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #

    def _on_line(self, text: str, source: str) -> None:
        sender = self.sender()
        handle = next((h for h in self._handles.values() if sender in h.readers), None)
        if handle is None:
            return
        self.output.emit(handle.project_id, text, source)
        self.logs.append(handle.project_id, text, source)

    # ------------------------------------------------------------------ #
    # Stop / kill / restart
    # ------------------------------------------------------------------ #

    def stop(self, project_id: str, grace: float = _STOP_GRACE) -> bool:
        """Gracefully stop a project (whole process tree)."""
        handle = self._handles.get(project_id)
        if handle is None or not handle.alive():
            self._release_handle(project_id, join=False)
            self._set_status(project_id, ProjectStatus.STOPPED)
            return False
        handle.user_stop = True
        self._set_status(project_id, ProjectStatus.STOPPING)
        self.logs.system(project_id, "Stopping…")
        stopper = Stopper(handle.popen, grace=grace)
        self._stoppers[handle.popen.pid] = stopper  # keep alive until finished
        stopper.finished_stop.connect(self._on_stopped)
        # Release the reference only when the thread has fully exited —
        # dropping it earlier destroys a still-running QThread (hard crash).
        stopper.finished.connect(lambda pid=handle.popen.pid: self._stoppers.pop(pid, None))
        stopper.finished.connect(stopper.deleteLater)
        stopper.start()
        return True

    def _on_stopped(self, pid: int, force: bool) -> None:
        for handle in list(self._handles.values()):
            if handle.popen.pid == pid:
                if force:
                    self.logs.system(handle.project_id, "Process tree force-killed.")
                self._finalize(handle, code=None, user_stop=True)

    def kill(self, project_id: str) -> None:
        """Hard-kill without grace period."""
        handle = self._handles.get(project_id)
        if handle is None:
            return
        handle.user_stop = True
        try:
            Stopper._terminate_tree(handle.popen, grace=0.2)
        except Exception as exc:
            log.warning("kill failed for %s: %s", project_id, exc)
        self._finalize(handle, code=None, user_stop=True)

    def restart(self, project: Project) -> None:
        """Stop (if running) then start again once the exit is confirmed."""
        if self.is_running(project.id):
            self._pending_restart[project.id] = True
            self.stop(project.id)
            self.logs.system(project.id, "Restarting…")
        else:
            self.start(project)

    def stop_all(self, timeout: float = 10.0) -> None:
        """Stop every managed process (used on application shutdown)."""
        keys = [key for key, handle in self._handles.items() if handle.alive()]
        if not keys:
            return
        log.info("Stopping %d running process(es)…", len(keys))
        for key in keys:
            self.stop(key)
        deadline = time.time() + timeout
        while time.time() < deadline and any(h.alive() for h in self._handles.values()):
            time.sleep(0.1)
        for handle in list(self._handles.values()):
            if handle.alive():
                try:
                    Stopper._terminate_tree(handle.popen, grace=0.5)
                except Exception:
                    pass
        log.info("All processes stopped.")

    def stop_aux(self, project_id: str, aux_key: str) -> None:
        """Stop a plugin tool command previously started with ``run_aux``."""
        handle = self._handles.get(aux_key)
        if handle and handle.alive():
            handle.user_stop = True
            stopper = Stopper(handle.popen, grace=4.0)
            self._stoppers[handle.popen.pid] = stopper
            stopper.finished_stop.connect(
                lambda _pid, _force, pk=aux_key, pj=project_id: self._finalize_aux(pj, pk)
            )
            stopper.finished.connect(lambda pid=handle.popen.pid: self._stoppers.pop(pid, None))
            stopper.finished.connect(stopper.deleteLater)
            stopper.start()

    def run_aux(self, project, spec) -> bool:
        """Run a plugin :class:`CommandSpec` as an auxiliary process.

        Output streams into the project's console; lifecycle is independent
        of the main process state. Returns False when already running.
        """
        aux_key = f"{_AUX_PREFIX}{project.id}:{spec.id}"
        if aux_key in self._handles and self._handles[aux_key].alive():
            self.logs.system(project.id, f"Tool '{spec.label}' is already running.")
            return False
        try:
            argv = resolve_command(spec.command, allow_shell=project.allow_shell)
            cwd = ensure_can_execute(project.path)
        except Exception as exc:
            self.logs.system(project.id, f"Tool '{spec.label}' failed: {exc}")
            self.failed.emit(project.id, f"{spec.label}: {exc}")
            return False

        env = os.environ.copy()
        env.update(normalize_env(project.env))
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        start_new_session = os.name != "nt"
        self.logs.command(project.id, f"[tool] {' '.join(argv)}")
        try:
            popen = subprocess.Popen(  # noqa: S603
                argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                creationflags=creationflags, start_new_session=start_new_session,
            )
        except OSError as exc:
            self.logs.system(project.id, f"Tool '{spec.label}' failed: {exc}")
            return False

        handle = ProcessHandle(project_id=project.id, key=aux_key, popen=popen,
                               command=spec.command, argv=argv)
        for stream, source in ((popen.stdout, "stdout"), (popen.stderr, "stderr")):
            if stream is None:
                continue
            reader = StreamReader(stream, source)
            reader.line_received.connect(self._on_aux_line)
            handle.readers.append(reader)
            reader.start()
        self._handles[aux_key] = handle
        self.aux_started.emit(project.id, aux_key)
        self.logs.system(project.id, f"Tool '{spec.label}' started (pid {popen.pid})")
        return True

    def _on_aux_line(self, text: str, source: str) -> None:
        sender = self.sender()
        handle = next((h for h in self._handles.values() if sender in h.readers), None)
        if handle is None:
            return
        self.logs.append(handle.project_id, text, source)

    def _finalize_aux(self, project_id: str, aux_key: str) -> None:
        handle = self._handles.pop(aux_key, None)
        if handle:
            self._join_readers(handle)
            code = handle.popen.poll()
            self.logs.system(project_id, f"Tool finished with exit code {code if code is not None else '?'}")
            self.aux_exited.emit(project_id, aux_key, code if code is not None else -1)

    def aux_for_project(self, project_id: str) -> Dict[str, ProcessHandle]:
        return {
            key: handle
            for key, handle in self._handles.items()
            if key.startswith(f"{_AUX_PREFIX}{project_id}:")
        }

    # ------------------------------------------------------------------ #
    # Exit handling
    # ------------------------------------------------------------------ #

    def _on_exited(self, pid: int, code: int) -> None:
        handle = next((h for h in self._handles.values() if h.popen.pid == pid), None)
        if handle is None or handle.finalized:
            return
        if handle.key.startswith(_AUX_PREFIX):
            self._finalize_aux(handle.project_id, handle.key)
            return
        user_stop = handle.user_stop
        uptime = handle.uptime()
        self._finalize(handle, code=code, user_stop=user_stop)

        project_id = handle.project_id
        if self._pending_restart.pop(project_id, False):
            QTimer.singleShot(500, lambda: self._restart_after_exit(project_id))
            return
        if user_stop:
            self.logs.system(project_id, "Stopped.")
        elif code == 0:
            self.logs.system(project_id, f"Process exited with code 0 after {format_duration(uptime)}.")
        elif uptime < _START_GRACE:
            self.logs.system(project_id, f"Crashed immediately with exit code {code}.")
            self.failed.emit(project_id, f"Process crashed with exit code {code}.")
        else:
            self.logs.system(project_id, f"Process exited with code {code} after {format_duration(uptime)}.")

    def _restart_after_exit(self, project_id: str) -> None:
        project = self._project_lookup(project_id)
        if project is not None:
            self.start(project)

    _project_lookup = None   # injected by RunHubApplication

    def _finalize(self, handle: ProcessHandle, code: Optional[int], user_stop: bool) -> None:
        if handle.finalized:
            return
        handle.finalized = True
        # Join every background thread BEFORE dropping our references.
        # Destroying a QThread while it is still running aborts the whole
        # process on Windows (exit code 0xC0000409).
        self._join_readers(handle)
        if handle.watcher is not None:
            handle.watcher.shutdown()
            if not handle.watcher.wait(1500):
                handle.watcher.terminate()
        self._handles.pop(handle.key, None)
        exit_code = code if code is not None else (handle.popen.poll() or 0)
        if handle.key.startswith(_AUX_PREFIX):
            return
        project = self._project_lookup(handle.project_id) if self._project_lookup else None
        if project is not None:
            project.mark_exit(exit_code)
        if user_stop or exit_code == 0:
            self._set_status(handle.project_id, ProjectStatus.STOPPED)
        elif code is None:
            self._set_status(handle.project_id, ProjectStatus.STOPPED)
        else:
            self._set_status(handle.project_id, ProjectStatus.CRASHED)
        self.exited.emit(handle.project_id, exit_code, user_stop)

    def _release_handle(self, key: str, join: bool = True) -> None:
        handle = self._handles.pop(key, None)
        if handle is None:
            return
        if join:
            self._join_readers(handle)
        if handle.watcher is not None:
            handle.watcher.shutdown()
            handle.watcher.wait(1500)

    @staticmethod
    def _join_readers(handle: ProcessHandle) -> None:
        for reader in handle.readers:
            reader.shutdown()
        for reader in handle.readers:
            if not reader.wait(1500):
                reader.terminate()

    # ------------------------------------------------------------------ #
    # Introspection for the system monitor
    # ------------------------------------------------------------------ #

    def snapshot(self) -> List[ProcessHandle]:
        """Currently tracked handles (main + aux)."""
        return [h for h in self._handles.values()]

    def uptime_for(self, project_id: str) -> float:
        handle = self._handles.get(project_id)
        return handle.uptime() if handle else 0.0

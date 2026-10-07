"""Background work that never freezes a window.

* a shared **thread pool** for blocking work (files, network, databases),
* an optional **process pool** for CPU-heavy pure functions,
* one shared **asyncio loop** for coroutines,
* **subprocesses** whose output streams line by line,

all returning a :class:`Task` whose ``status``, ``progress`` and ``message`` are
reactive :class:`~zepygui.State` values a page can display.

    def scan(folder, task):                     # a parameter named `task` receives the Task
        for i, entry in enumerate(entries):
            task.check()                        # raises Cancelled once task.cancel() was called
            task.report(i / len(entries), entry.name)
        return total

    job = ui.task(scan, folder, on_done=lambda total: ui.toast(f"{total} bytes"))
    ui.progress(job.progress.value * 100 if job.progress.value is not None else 0)
    ui.button("Cancel", job.cancel)

``on_done`` / ``on_error`` run on the thread of the window that started the task, like an
event handler, so they may update the UI freely.
"""
from __future__ import annotations

import asyncio
import concurrent.futures as cf
import inspect
import os
import subprocess
import sys
import threading
import time
import traceback

from .state import State, _local, _session_var, current_session, invoke

__all__ = ["Task", "Cancelled", "CommandError", "start", "run_command", "run_coroutine", "thread_pool",
           "process_pool", "event_loop", "shutdown"]

_lock = threading.Lock()
_threads = None
_processes = None
_loop = None


class Cancelled(Exception):
    """Raised by :meth:`Task.check` inside a task that has been cancelled."""


class CommandError(Exception):
    """A command started with :func:`run_command` exited with a non-zero status."""

    def __init__(self, returncode, cmd):
        super().__init__(f"command exited with status {returncode}: {cmd}")
        self.returncode = returncode
        self.cmd = cmd


# ----------------------------------------------------------------------------- executors
def thread_pool():
    """The shared pool for blocking work (sized for I/O: ``min(32, cpu + 4)`` threads)."""
    global _threads
    with _lock:
        if _threads is None:
            _threads = cf.ThreadPoolExecutor(max_workers=min(32, (os.cpu_count() or 1) + 4),
                                             thread_name_prefix="zepygui-task")
        return _threads


def process_pool():
    """The shared pool for CPU-bound work (one process per core, started on first use)."""
    global _processes
    with _lock:
        if _processes is None:
            _processes = cf.ProcessPoolExecutor(max_workers=os.cpu_count() or 1)
        return _processes


def event_loop():
    """The app's single asyncio loop, running on its own daemon thread."""
    global _loop
    with _lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="zepygui-asyncio", daemon=True).start()
        return _loop


def shutdown():
    """Stop the pools and the loop (called when the app exits). Running work is abandoned."""
    global _threads, _processes, _loop
    with _lock:
        threads, processes, loop = _threads, _processes, _loop
        _threads = _processes = _loop = None
    if threads is not None:
        threads.shutdown(wait=False, cancel_futures=True)
    if processes is not None:
        processes.shutdown(wait=False, cancel_futures=True)
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(loop.stop)


def _report(session, exc):
    traceback.print_exception(type(exc), exc, exc.__traceback__)
    if session is not None and not session.closed:
        session.send({"type": "toast", "kind": "error", "title": type(exc).__name__,
                      "message": str(exc) or "Error", "duration": 6})


async def _in_session(coro, session):
    _session_var.set(session)  # each asyncio task has its own context copy
    return await coro


def run_coroutine(coro, session=None):
    """Schedule ``coro`` on the shared loop on behalf of ``session``; errors become a toast.

    Returns a ``concurrent.futures.Future``."""
    fut = asyncio.run_coroutine_threadsafe(_in_session(coro, session), event_loop())

    def done(f):
        if not f.cancelled() and f.exception() is not None:
            _report(session, f.exception())

    fut.add_done_callback(done)
    return fut


# ----------------------------------------------------------------------------- Task
class Task:
    """A handle on background work.

    Reactive (read them in a page to display them):
      ``status``   ``"pending"``, ``"running"``, ``"done"``, ``"error"`` or ``"cancelled"``
      ``progress`` ``None`` while unknown, else a float from 0 to 1
      ``message``  the last message passed to :meth:`report`
    Plain: ``result``, ``error``.
    """

    def __init__(self, name="task"):
        self.name = name
        self.status = State("pending")
        self.progress = State(None)
        self.message = State("")
        self.result = None
        self.error = None
        self._cancel = threading.Event()
        self._finished = threading.Event()
        self._future = None
        self._process = None

    # -- inside the task -------------------------------------------------------
    @property
    def cancelled(self):
        """True once :meth:`cancel` has been called."""
        return self._cancel.is_set()

    def check(self):
        """Raise :class:`Cancelled` if the task was cancelled. Call it in your loops."""
        if self._cancel.is_set():
            raise Cancelled()

    def report(self, progress=None, message=None):
        """Publish progress (0..1) and/or a message. Cheap enough to call per item:
        windows coalesce the resulting redraws to at most one per frame."""
        if progress is not None:
            self.progress.set(min(1.0, max(0.0, float(progress))))
        if message is not None:
            self.message.set(str(message))

    # -- outside ---------------------------------------------------------------
    @property
    def running(self):
        return self.status.value in ("pending", "running")

    @property
    def done(self):
        return self._finished.is_set()

    def cancel(self):
        """Ask the task to stop: a pending task never starts, a coroutine is cancelled, a
        command is terminated, and a running function sees it at its next :meth:`check`."""
        self._cancel.set()
        fut = self._future
        if fut is not None:
            fut.cancel()
        proc = self._process
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def wait(self, timeout=None):
        """Block until the task ends; return its result or raise its error.
        (Never call this from a window's own thread: use ``on_done`` instead.)"""
        if not self._finished.wait(timeout):
            raise TimeoutError(f"task {self.name!r} still running")
        if self.error is not None:
            raise self.error
        return self.result

    def __repr__(self):
        return f"<Task {self.name} {self.status._value}>"


def _wants_task(fn):
    try:
        return "task" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def start(fn, *args, on_done=None, on_error=None, process=False, name=None, **kwargs):
    """Run ``fn(*args, **kwargs)`` in the background and return its :class:`Task`.

    * a regular function runs on the shared thread pool,
    * an ``async def`` function runs on the shared event loop,
    * ``process=True`` runs it in a separate process (for CPU-bound work; ``fn`` and its
      arguments must be picklable, and it cannot receive ``task``).

    If ``fn`` has a parameter named ``task``, it receives the :class:`Task` (to report
    progress and check for cancellation). ``on_done(result)`` and ``on_error(exc)`` run on
    the starting window's thread. Without ``on_error``, an error is shown as a toast.
    """
    task = Task(name or getattr(fn, "__name__", "task"))
    session = current_session()
    if not process and _wants_task(fn):
        kwargs["task"] = task
    finished = threading.Lock()

    def finish(status, result=None, error=None):
        with finished:
            if task._finished.is_set():
                return
            task.result, task.error = result, error
            if status == "done" and task.progress._value is not None:
                task.progress.set(1.0)
            task.status.set(status)
            task._finished.set()
        if status == "done" and on_done is not None:
            _deliver(session, on_done, result)
        elif status == "error":
            if on_error is not None:
                _deliver(session, on_error, error)
            else:
                _report(session, error)

    def outcome(exc):
        if isinstance(exc, (Cancelled, asyncio.CancelledError, cf.CancelledError)) or \
                (task.cancelled and isinstance(exc, (CommandError, OSError))):
            finish("cancelled")
        else:
            finish("error", error=exc)

    if process:
        if task.cancelled:
            finish("cancelled")
            return task
        task.status.set("running")
        fut = process_pool().submit(fn, *args, **kwargs)

        def collected(f):
            if f.cancelled():
                finish("cancelled")
            elif f.exception() is not None:
                outcome(f.exception())
            else:
                finish("done", f.result())

        task._future = fut
        fut.add_done_callback(collected)
        return task

    if inspect.iscoroutinefunction(fn):
        async def runner():
            _session_var.set(session)
            task.status.set("running")
            try:
                result = await fn(*args, **kwargs)
            except BaseException as exc:  # noqa: B902 - CancelledError is a BaseException
                outcome(exc)
                if not isinstance(exc, Exception):
                    raise
            else:
                finish("done", result)

        fut = asyncio.run_coroutine_threadsafe(runner(), event_loop())
        fut.add_done_callback(lambda f: f.cancelled() and finish("cancelled"))
        task._future = fut
        return task

    def run():
        if task.cancelled:
            finish("cancelled")
            return
        _local.session = session
        task.status.set("running")
        try:
            result = fn(*args, **kwargs)
            if inspect.iscoroutine(result):  # a sync function that returned a coroutine
                result = asyncio.run_coroutine_threadsafe(_in_session(result, session), event_loop()).result()
        except BaseException as exc:  # noqa: B902
            outcome(exc)
        else:
            finish("done", result)
        finally:
            _local.session = None

    fut = thread_pool().submit(run)
    fut.add_done_callback(lambda f: f.cancelled() and finish("cancelled"))
    task._future = fut
    return task


def _deliver(session, fn, value):
    """Call a completion callback on the window's thread (or right here without a window)."""
    if session is not None and not session.closed:
        session.call_soon(fn, value)
    else:
        try:
            invoke(fn, value)
        except Exception:
            traceback.print_exc()


# ----------------------------------------------------------------------------- commands
def run_command(cmd, *, on_line=None, log=None, on_done=None, on_error=None, cwd=None, env=None,
                shell=False, stderr=True, encoding="utf-8", name=None):
    """Run an external command and stream its output, line by line, without blocking.

    ``log``      a :class:`zepygui.Log` that receives every line (show it with ``ui.log_view``)
    ``on_line``  ``fn(line)`` called for every line, on the reading thread
    ``stderr``   merge standard error into the stream (default ``True``)
    ``on_done(returncode)`` runs when the command exits with status 0, ``on_error(exc)``
    otherwise (a :class:`CommandError` carrying ``returncode``). ``task.cancel()``
    terminates the process. Each command gets its own reader thread, so long-running
    commands never occupy the shared pool.
    """
    task = Task(name or (cmd if isinstance(cmd, str) else " ".join(map(str, cmd)))[:60])
    session = current_session()
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW: no console flash

    def finish(status, result=None, error=None):
        task.result, task.error = result, error
        task.status.set(status)
        task._finished.set()
        if status == "done" and on_done is not None:
            _deliver(session, on_done, result)
        elif status == "error":
            if on_error is not None:
                _deliver(session, on_error, error)
            else:
                _report(session, error)

    def read():
        _local.session = session
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, shell=shell, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT if stderr else None,
                                    text=True, encoding=encoding, errors="replace", bufsize=1,
                                    creationflags=flags)
        except OSError as exc:
            finish("error", error=exc)
            return
        task._process = proc
        task.status.set("running")
        if task.cancelled:
            proc.terminate()
        try:
            for line in proc.stdout:
                line = line.rstrip("\r\n")
                if log is not None:
                    log.append(line)
                if on_line is not None:
                    try:
                        on_line(line)
                    except Exception:
                        traceback.print_exc()
        finally:
            proc.stdout.close()
            code = proc.wait()
            _local.session = None
        if task.cancelled:
            finish("cancelled", code)
        elif code == 0:
            finish("done", code)
        else:
            finish("error", code, CommandError(code, cmd))

    threading.Thread(target=read, name="zepygui-command", daemon=True).start()
    return task

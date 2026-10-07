"""Reactive state and the thread-local runtime context shared by the framework."""
from __future__ import annotations

import contextvars
import inspect
import threading
import types
import weakref

_local = threading.local()
_runtime = {"app": None}
_IMMUTABLE = (int, float, complex, str, bool, bytes, tuple, frozenset, type(None))
# The window an asyncio task belongs to. Threads use _local.session; coroutines all share
# one event-loop thread, so they carry their window in a context variable instead.
_session_var = contextvars.ContextVar("zepygui_session", default=None)


def current_session():
    """The window (session) whose event, render or background task is running, if any."""
    return getattr(_local, "session", None) or _session_var.get()


def _targets():
    """Sessions an imperative call (toast, run_js...) should reach."""
    s = current_session()
    if s is not None:
        return [s]
    app = _runtime["app"]
    return app.connected_sessions() if app else []


class State:
    """A reactive value.

    Reading ``.value`` while a window renders subscribes that window; assigning a
    new value re-renders every subscribed window automatically.

        count = State(0)
        count.value += 1        # or count.set(1), count.update(lambda n: n + 1)
    """

    __slots__ = ("_value", "_subs", "_lock", "__weakref__")

    def __init__(self, value=None):
        self._value = value
        self._subs = weakref.WeakSet()
        self._lock = threading.Lock()

    @property
    def value(self):
        r = getattr(_local, "rendering", None)
        if r is not None:
            with self._lock:
                self._subs.add(r)
        return self._value

    @value.setter
    def value(self, new):
        self.set(new)

    def get(self):
        return self.value

    def set(self, new):
        old, self._value = self._value, new
        if isinstance(new, _IMMUTABLE) and type(old) is type(new) and old == new:
            return
        self.notify()

    def update(self, fn):
        """Set the value to ``fn(current)``; returns the new value."""
        self.set(fn(self._value))
        return self._value

    def notify(self):
        """Force subscribed windows to re-render (after mutating a list/dict in place)."""
        with self._lock:
            subs = list(self._subs)
        for s in subs:
            s.invalidate()

    # convenience helpers -------------------------------------------------
    def toggle(self):
        self.set(not self._value)

    def append(self, item):
        self._value.append(item)
        self.notify()

    def extend(self, items):
        self._value.extend(items)
        self.notify()

    def insert(self, index, item):
        self._value.insert(index, item)
        self.notify()

    def remove(self, item):
        self._value.remove(item)
        self.notify()

    def pop(self, *args):
        result = self._value.pop(*args)
        self.notify()
        return result

    def clear(self):
        self._value.clear()
        self.notify()

    def __getitem__(self, key):
        return self.value[key]

    def __setitem__(self, key, item):
        self._value[key] = item
        self.notify()

    def __delitem__(self, key):
        del self._value[key]
        self.notify()

    def __iadd__(self, other):
        self.set(self._value + other)
        return self

    def __isub__(self, other):
        self.set(self._value - other)
        return self

    def __len__(self):
        return len(self.value)

    def __iter__(self):
        return iter(self.value)

    def __contains__(self, item):
        return item in self.value

    def __bool__(self):
        return bool(self.value)

    def __str__(self):
        return str(self.value)

    def __format__(self, spec):
        return format(self.value, spec)

    def __repr__(self):
        return f"State({self._value!r})"


# ---------------------------------------------------------------- calling user code
_FUNC_TYPES = (types.FunctionType, types.MethodType)


def _arity(fn, available):
    """How many of ``available`` positional arguments ``fn`` accepts.

    Plain functions and methods are answered from their code object (cheap: handlers run on
    every event); anything else goes through ``inspect.signature``."""
    if type(fn) in _FUNC_TYPES:
        func = fn.__func__ if type(fn) is types.MethodType else fn
        code = func.__code__
        if code.co_flags & inspect.CO_VARARGS:
            return available
        n = code.co_argcount - (1 if type(fn) is types.MethodType else 0)
        return min(available, n)
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return available
    if any(p.kind == p.VAR_POSITIONAL for p in params):
        return available
    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return min(available, len(positional))


def invoke(fn, *args):
    """Call ``fn`` with as many of ``args`` as it accepts.

    A coroutine it returns is scheduled on the shared event loop and ``None`` is returned."""
    result = fn(*args[: _arity(fn, len(args))])
    if inspect.iscoroutine(result):
        from .tasks import run_coroutine
        run_coroutine(result, current_session())
        return None
    return result


def spawn(fn, *args):
    """Run ``fn(*args)`` (sync or async) in the background, keeping the current window.

    Kept for compatibility; returns a :class:`zepygui.tasks.Task`."""
    from .tasks import start
    return start(fn, *args)

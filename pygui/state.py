"""Reactive state and the thread-local runtime context shared by the framework."""
from __future__ import annotations

import asyncio
import inspect
import threading
import traceback
import weakref

_local = threading.local()
_runtime = {"app": None}
_IMMUTABLE = (int, float, complex, str, bool, bytes, tuple, frozenset, type(None))


def current_session():
    """The window (session) whose event or render is running on this thread, if any."""
    return getattr(_local, "session", None)


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
def _arity(fn, available):
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return available
    if any(p.kind == p.VAR_POSITIONAL for p in params):
        return available
    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return min(available, len(positional))


def invoke(fn, *args):
    """Call ``fn`` with as many of ``args`` as it accepts. Coroutines run in the background."""
    result = fn(*args[: _arity(fn, len(args))])
    if inspect.iscoroutine(result):
        _run_thread(lambda: asyncio.run(result))
        return None
    return result


def _run_thread(target):
    session = current_session()

    def runner():
        _local.session = session
        try:
            target()
        except Exception:
            traceback.print_exc()
            if session is not None:
                session.report_error()

    threading.Thread(target=runner, daemon=True).start()


def spawn(fn, *args):
    """Run ``fn(*args)`` (sync or async) in a background thread, keeping the current window."""

    def target():
        result = fn(*args[: _arity(fn, len(args))])
        if inspect.iscoroutine(result):
            asyncio.run(result)

    _run_thread(target)

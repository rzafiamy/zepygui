"""A bounded, thread-safe line buffer streamed to the window (``ui.log_view``).

A normal page re-sends its whole tree on every change, which is the wrong shape for a
console that grows by thousands of lines a second. A :class:`Log` instead sends each
window only the lines it has not seen yet, in batches, and the window keeps its own copy
and draws just the visible lines. Appending is O(1); memory is capped by ``max_lines``.

    log = Log(max_lines=200_000)
    ui.task(lambda: [log.append(f"line {i}") for i in range(70_000)])
    ui.log_view(log, height=480)          # in a page
    print("hello", file=log)              # a Log is also a writable text stream
"""
from __future__ import annotations

import collections
import itertools
import threading
import weakref

__all__ = ["Log"]

_ids = itertools.count(1)


class Log:
    """Append-only lines, newest last, oldest dropped beyond ``max_lines``."""

    def __init__(self, max_lines=100_000):
        self.id = f"log{next(_ids)}"
        self.max_lines = max_lines
        self._lines = collections.deque(maxlen=max_lines)
        self._end = 0                               # absolute index after the newest line
        self._gen = 0                               # bumped by clear(): windows start over
        self._partial = ""                          # write() text not yet ended by a newline
        self._lock = threading.Lock()
        self._sent = weakref.WeakKeyDictionary()    # session -> absolute index sent so far (None: resync)
        self._queued = weakref.WeakSet()            # sessions with a flush already scheduled

    # -- writing (any thread) -----------------------------------------------------------
    def append(self, line):
        """Add one line (a string containing newlines adds several)."""
        line = str(line)
        if "\n" in line:
            self.extend(line.split("\n"))
            return
        with self._lock:
            self._lines.append(line)
            self._end += 1
        self._wake()

    def extend(self, lines):
        """Add many lines at once (one lock, one wake-up)."""
        lines = [str(x) for x in lines]
        if not lines:
            return
        with self._lock:
            self._lines.extend(lines)
            self._end += len(lines)
        self._wake()

    def write(self, text):
        """File-like: ``print(..., file=log)``. Text is buffered until a newline."""
        text = self._partial + str(text)
        *complete, self._partial = text.split("\n")
        if complete:
            self.extend(complete)
        return len(text)

    def flush(self):
        """File-like no-op (lines are sent as soon as they are complete)."""

    def clear(self):
        """Remove every line; open views empty themselves."""
        with self._lock:
            self._lines.clear()
            self._partial = ""
            self._gen += 1
            for s in list(self._sent.keys()):
                self._sent[s] = None
        self._wake()

    # -- reading ----------------------------------------------------------------------
    def __len__(self):
        return len(self._lines)

    def lines(self, last=None):
        """A list copy of the retained lines (or of the ``last`` n)."""
        with self._lock:
            if last is None or last >= len(self._lines):
                return list(self._lines)
            return list(itertools.islice(self._lines, len(self._lines) - last, None))

    def text(self):
        return "\n".join(self.lines())

    def save(self, path, encoding="utf-8"):
        """Write the retained lines to a file."""
        with open(path, "w", encoding=encoding) as f:
            for line in self.lines():
                f.write(line)
                f.write("\n")

    # -- streaming to windows ---------------------------------------------------------
    def _attach(self, session):
        """Called while ``session`` renders a view of this log."""
        if session in self._sent:
            return
        with self._lock:
            self._sent[session] = None
        session.logs.add(self)
        self._schedule(session)

    def _resync(self, session):
        """The window lost its copy (reconnected): send everything again."""
        with self._lock:
            if session not in self._sent:
                return
            self._sent[session] = None
        self._schedule(session)

    def _wake(self):
        # Hot path (every append): when every window already has a flush pending, the
        # new lines ride along with it and there is nothing to do.
        if len(self._queued) >= len(self._sent):
            return
        for s in list(self._sent.keys()):
            self._schedule(s)

    def _schedule(self, session):
        with self._lock:
            if session in self._queued:
                return  # the pending flush will pick these lines up too: natural batching
            self._queued.add(session)
        session.call_soon(self._flush, session)

    def _flush(self, session):
        """Runs on the window's thread: send the lines this window has not seen."""
        with self._lock:
            self._queued.discard(session)
            base = self._end - len(self._lines)
            cursor = self._sent.get(session)
            reset = cursor is None or cursor < base
            start = base if reset else cursor
            if start >= self._end and not reset:
                return
            lines = list(itertools.islice(self._lines, start - base, None))
            self._sent[session] = self._end
            gen = self._gen
        session.send({"type": "log", "id": self.id, "gen": gen, "start": start, "reset": reset,
                      "max": self.max_lines, "lines": lines})

    def __repr__(self):
        return f"<Log {self.id} {len(self._lines)} lines>"

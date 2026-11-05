"""Application, window sessions, routing and rendering."""
from __future__ import annotations

import inspect
import json
import multiprocessing
import os
import platform
import queue
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import weakref
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs

from . import ui
from .diff import diff as _diff
from .state import State, _local, _runtime, invoke
from .tasks import run_coroutine, shutdown as _shutdown_tasks
from .ui import ComponentCall, Element

STATIC_DIR = Path(__file__).parent / "static"
_UNITLESS = {"opacity", "z-index", "flex", "flex-grow", "flex-shrink", "font-weight", "line-height", "order",
             "zoom", "grid-row", "grid-column", "scale"}


class Event:
    """What a handler receives for raw DOM events (``on_click``, ``on_keydown``...)."""

    def __init__(self, name, data):
        self.name = name
        self.data = data or {}
        self.value = self.data.get("value")
        self.checked = self.data.get("checked")
        self.key = self.data.get("key")
        self.form = self.data.get("form")

    def __getitem__(self, key):
        return self.data.get(key)

    def __repr__(self):
        return f"Event({self.name!r}, {self.data!r})"


class Route:
    _PARAM = re.compile(r"\{(\w+)(?::(int|float|path))?\}")

    def __init__(self, path, fn, title):
        self.path, self.fn, self.title = path, fn, title
        self.converters = {}
        pattern, last = "", 0
        for m in self._PARAM.finditer(path):
            pattern += re.escape(path[last:m.start()])
            name, kind = m.group(1), m.group(2)
            pattern += {"int": r"(?P<%s>-?\d+)", "float": r"(?P<%s>-?\d+(?:\.\d+)?)",
                        "path": r"(?P<%s>.+)"}.get(kind, r"(?P<%s>[^/]+)") % name
            self.converters[name] = {"int": int, "float": float}.get(kind, str)
            last = m.end()
        pattern += re.escape(path[last:])
        self.regex = re.compile(pattern.rstrip("/") + "/?")

    def match(self, path):
        m = self.regex.fullmatch(path)
        if not m:
            return None
        return {k: self.converters[k](v) for k, v in m.groupdict().items()}


def _split_path(full):
    path, _, qs = (full or "/").partition("?")
    return path or "/", {k: v[0] if len(v) == 1 else v for k, v in parse_qs(qs).items()}


def _accepted_kwargs(fn, kwargs):
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return kwargs
    return {k: v for k, v in kwargs.items() if k in params}


def _style_str(style):
    if isinstance(style, str):
        return style
    parts = []
    for k, v in style.items():
        if isinstance(v, State):
            v = v.value
        if v is None or v is False:
            continue
        if not k.startswith("--"):
            k = k.replace("_", "-")
            if isinstance(v, (int, float)) and not isinstance(v, bool) and k not in _UNITLESS:
                v = f"{v}px"
        parts.append(f"{k}:{v}")
    return ";".join(parts)


def _default_404():
    return ui.empty_state("Page not found", "There is nothing at this address.", icon="globe",
                          action=ui.button("Go home", lambda: ui.navigate("/"), icon="home"))


def _error_view(tb):
    return ui.container(ui.alert(ui.code_block(tb, copyable=True), kind="error", title="This page failed to render"))


# =============================================================================
# Rendering
# =============================================================================
class Renderer:
    def __init__(self, session):
        self.session = session
        self.handlers = {}
        self.claims = {}  # id(parent) -> [(ComponentCall, children count when it was created)]
        self.used_hooks = set()
        self.hook_path, self.hook_idx = "root", 0

    def hook(self, default):
        key = (self.hook_path, self.hook_idx)
        self.hook_idx += 1
        self.used_hooks.add(key)
        state = self.session.hooks.get(key)
        if state is None:
            state = State(default() if callable(default) else default)
            self.session.hooks[key] = state
        return state

    def build(self):
        s = self.session
        app = s.app
        route, params = app._match(s.path)
        if route is None:
            fn, params, title, rkey = app._not_found or _default_404, {}, "Not found", "404"
        else:
            fn, title, rkey = route.fn, route.title, route.path
        _local.rendering, _local.renderer = s, self
        try:
            page = Element("div", ComponentCall(fn, (), _accepted_kwargs(fn, params)), cls="pg-page", key=rkey)
            root = ComponentCall(app._layout, (page,), {}) if app._layout else page
            nodes = self.ser(root, "r")
        finally:
            _local.rendering = _local.renderer = None
        tree = nodes[0] if len(nodes) == 1 and isinstance(nodes[0], dict) else {"t": "div", "c": nodes}
        return tree, title

    def ser(self, node, path):
        out = []
        self._ser_into(node, path, out)
        return out

    def _ser_into(self, node, path, out):
        """Serialise ``node`` and append the result to ``out`` (avoids a list per node)."""
        cls = type(node)
        if cls is str:
            out.append(node)
        elif cls is Element:
            if node.tag == "":
                self._children_into(node, path, out)
            else:
                out.append(self.ser_element(node, path))
        elif node is None or node is True or node is False:
            return
        elif cls is ComponentCall:
            out += self.ser_component(node, path)
        elif isinstance(node, State):
            self._ser_into(node.value, path, out)
        elif isinstance(node, ComponentCall):
            out += self.ser_component(node, path)
        elif isinstance(node, Element):
            if node.tag == "":
                self._children_into(node, path, out)
            else:
                out.append(self.ser_element(node, path))
        elif isinstance(node, (list, tuple)):
            for i, child in enumerate(node):
                self._ser_into(child, f"{path}.{i}", out)
        elif callable(node):
            self._ser_into(node(), path, out)
        else:
            out.append(str(node))

    def ser_component(self, call, path):
        cpath = f"{path}/{getattr(call.fn, '__qualname__', 'c')}"
        saved = self.hook_path, self.hook_idx
        self.hook_path, self.hook_idx = cpath, 0
        frag = Element("")
        frag._detach()
        stack = _local.__dict__.setdefault("stack", [])
        stack.append(frag)
        try:
            result = call.fn(*call.args, **call.kwargs)
        finally:
            stack.pop()
            self.hook_path, self.hook_idx = saved
        if result is not None and not (isinstance(result, Element) and result._parent is frag):
            frag.add(result)
        out = []
        self._children_into(frag, cpath, out)
        return out

    def ser_element(self, node, path):
        if node.tag == "":
            return self.ser_children(node, path)
        v = {"t": node.tag}
        attrs = {}
        for k, val in node.attrs.items():
            if isinstance(val, State):
                val = val.value
            elif callable(val):
                val = val()
            if val is None:
                continue
            if k == "style":
                val = _style_str(val)
                if not val:
                    continue
            elif k == "class" and isinstance(val, (list, tuple)):
                val = " ".join(c for c in val if c)
            attrs[k] = val
        if attrs:
            v["a"] = attrs
        if node.key is not None:
            v["k"] = str(node.key)
        if node.events:
            events = {}
            for name, (handler, opts) in node.events.items():
                hid = f"{path}:{name}"
                self.handlers[hid] = (handler, opts.get("transform"))
                spec = {"h": hid}
                for opt in ("keys", "prevent", "stop", "debounce", "throttle", "self"):
                    if opts.get(opt):
                        spec[opt] = opts[opt]
                events.setdefault(opts.get("dom") or name, []).append(spec)
            v["e"] = events
        if node.html is not None:
            v["h"] = node.html
        elif node.children:
            children = []
            self._children_into(node, path, children)
            if children:
                v["c"] = children
        return v

    def ser_children(self, node, path):
        out = []
        self._children_into(node, path, out)
        return out

    def _claimed(self, node, calls):
        """Ids of ``node``'s children that were passed as arguments to a component created
        inside ``node`` (they render inside that component, never here)."""
        found = set()
        for call, before in calls:
            wanted = {id(c) for c in node.children[:before]
                      if isinstance(c, Element) and c._parent is node and id(c) not in found}
            if wanted:
                ui._find(call.args, wanted, found) or ui._find(call.kwargs, wanted, found)
        return found

    def _children_into(self, node, path, out):
        calls = self.claims.get(id(node))
        skip = self._claimed(node, calls) if calls else ()
        i = 0
        for child in node.children:
            if type(child) is str:
                out.append(child)
            elif isinstance(child, Element):
                if child._parent is not node or (skip and id(child) in skip):
                    continue  # moved elsewhere, or handed to a component
                key = child.key
                self._ser_into(child, f"{path}.{i if key is None else key}", out)
                # Break the child -> parent back-reference once serialised: the tree then has
                # no reference cycles and is freed by reference counting as soon as the
                # render ends, instead of waiting for (and slowing down) the cyclic GC.
                child._parent = None
            else:
                self._ser_into(child, f"{path}.{i}", out)
            i += 1


_SLOW_HANDLER = 0.25  # seconds; longer and the window visibly freezes
_warned_slow = set()


def _warn_if_slow(handler, elapsed):
    """Tell the developer (once per handler) that it blocked its window."""
    if elapsed < _SLOW_HANDLER:
        return
    code = getattr(getattr(handler, "__func__", handler), "__code__", None)
    where = f"{code.co_filename}:{code.co_firstlineno}" if code else repr(handler)
    if where in _warned_slow:
        return
    _warned_slow.add(where)
    print(f"[zepygui] a handler blocked its window for {elapsed * 1000:.0f} ms ({where}). "
          f"Run slow work with ui.task(fn, ...) to keep the window responsive.", file=sys.stderr)


# =============================================================================
# Session: one per window
# =============================================================================
class Session:
    """State of one open window: current page, local hooks, event handlers."""

    def __init__(self, app, sid, path="/", theme=None):
        self.app = app
        self.id = sid
        self.path, self.query = _split_path(path)
        self.theme = State(theme if theme in ("dark", "light") else "dark")
        self.data = {}
        self.hooks = {}
        self.handlers = {}
        self.logs = weakref.WeakSet()  # Log buffers this window shows (resent on reconnect)
        self.queue = queue.Queue()
        self.dirty = False
        self._render_queued = False
        self.ack = self._sent_ack = 0
        self.closed = False
        self.connected = False
        self.disconnected_at = time.time()
        self._out = None
        self._rendering = False
        self._title = None
        self._tree = None  # the tree the window shows: later renders send a patch against it
        self.worker = threading.Thread(target=self._loop, name=f"zepygui-window-{sid}", daemon=True)
        self.worker.start()

    # -- transport -----------------------------------------------------------
    def attach(self, out):
        self._out = out
        self.connected = True
        self._title = None
        self._tree = None  # a new or reloaded window has nothing to patch: send it all
        self.queue.put(("render",))
        for log in list(self.logs):
            log._resync(self)

    def detach(self, out=None):
        if out is None or self._out == out:
            self._out = None
            self.connected = False
            self.disconnected_at = time.time()

    def send(self, message):
        out = self._out
        if out is not None:
            out(json.dumps(message, separators=(",", ":"), default=str))

    # -- scheduling ----------------------------------------------------------
    def _in_worker(self):
        return threading.current_thread() is self.worker

    def invalidate(self):
        if self.closed:
            return
        if self._in_worker():
            if not self._rendering:
                self.dirty = True
        elif not self._render_queued:
            # One pending request is enough: a thread setting a State thousands of times
            # per second must not flood the queue with identical render requests.
            self._render_queued = True
            self.queue.put(("render",))

    def call_soon(self, fn, *args):
        """Run ``fn`` on this window's thread (safe from any thread)."""
        self.queue.put(("fn", fn, args))

    def navigate(self, path, push=True):
        if self._in_worker():
            self._set_path(path, push)
        else:
            self.queue.put(("nav", path, push))

    def set_theme(self, theme):
        if theme in ("dark", "light"):
            self.theme.set(theme)
            self.app._backend_theme(theme)
        self.send({"type": "theme", "theme": theme})

    def close(self):
        self.closed = True
        self.queue.put(None)

    def report_error(self):
        exc = sys.exc_info()[1]
        traceback.print_exc()
        if exc is not None:
            self.send({"type": "toast", "kind": "error", "title": type(exc).__name__, "message": str(exc) or "Error",
                       "duration": 6})

    # -- worker --------------------------------------------------------------
    def _set_path(self, path, push):
        self.path, self.query = _split_path(path)
        if push:
            self.send({"type": "nav", "path": path})
        self.dirty = True

    FRAME = 1 / 60      # at most one render per frame
    MAX_DEFER = 0.1     # under a constant stream of events, still render this often

    def _loop(self):
        _local.session = self
        last_render = time.monotonic()  # lets the connect burst (nav, theme, render) settle first
        while True:
            if self.dirty and self._out is not None:
                now = time.monotonic()
                wait = last_render + self.FRAME - now
                if (wait <= 0 and self.queue.empty()) or now - last_render > self.MAX_DEFER:
                    self._render()
                    last_render = time.monotonic()
                    continue
                try:
                    item = self.queue.get(timeout=wait) if wait > 0 else self.queue.get_nowait()
                except queue.Empty:
                    continue
            else:
                if self.ack != self._sent_ack and self.queue.empty():
                    self._sent_ack = self.ack
                    self.send({"type": "ack", "ack": self.ack})
                item = self.queue.get()
            if item is None:
                return
            try:
                self._process(item)
            except Exception:
                self.report_error()

    def _process(self, item):
        kind = item[0]
        if kind == "render":
            self._render_queued = False
            self.dirty = True
        elif kind == "resync":  # the window could not apply a patch: start over from a full tree
            self._tree = None
            self.dirty = True
        elif kind == "event":
            _, hid, data, seq = item
            if seq:
                self.ack = max(self.ack, seq)
            entry = self.handlers.get(hid)
            if entry is not None:
                handler, transform = entry
                ev = Event(hid.rsplit(":", 1)[-1], data)
                started = time.perf_counter()
                try:
                    invoke(handler, transform(ev) if transform else ev)
                finally:
                    _warn_if_slow(handler, time.perf_counter() - started)
        elif kind == "nav":
            self._set_path(item[1], item[2])
        elif kind == "theme":
            if item[1] in ("dark", "light"):
                self.theme.set(item[1])
                self.app._backend_theme(item[1])
        elif kind == "fn":
            invoke(item[1], *item[2])
        elif kind == "call":
            _, cid, name, args = item
            fn = self.app._exposed.get(name)
            try:
                if fn is None:
                    raise KeyError(f"no exposed function named {name!r}")
                result = fn(*args)
                if inspect.iscoroutine(result):
                    # resolve on the shared loop: the window keeps handling events meanwhile
                    fut = run_coroutine(result, self)
                    fut.add_done_callback(lambda f, cid=cid: self._send_result(cid, f))
                    return
                self.send({"type": "result", "id": cid, "ok": True, "value": result})
            except Exception as exc:
                self.send({"type": "result", "id": cid, "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def _send_result(self, cid, fut):
        if fut.cancelled():
            self.send({"type": "result", "id": cid, "ok": False, "error": "CancelledError"})
        elif fut.exception() is not None:
            exc = fut.exception()
            self.send({"type": "result", "id": cid, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        else:
            self.send({"type": "result", "id": cid, "ok": True, "value": fut.result()})

    def _render(self):
        self.dirty = False
        self._rendering = True
        renderer = Renderer(self)
        try:
            tree, title = renderer.build()
        except Exception:
            traceback.print_exc()
            renderer = Renderer(self)
            _local.rendering, _local.renderer = self, renderer
            try:
                tree = renderer.ser(_error_view(traceback.format_exc()), "err")[0]
            finally:
                _local.rendering = _local.renderer = None
            title = "Error"
        finally:
            self._rendering = False
        for key in [k for k in self.hooks if k not in renderer.used_hooks]:
            del self.hooks[key]
        self.handlers = renderer.handlers
        self._sent_ack = self.ack
        previous, self._tree = self._tree, tree
        if previous is None:
            self.send({"type": "render", "tree": tree, "ack": self.ack})
        else:
            self.send({"type": "render", "tree": _diff(previous, tree), "ack": self.ack, "diff": 1})
        full_title = f"{title} · {self.app.title}" if title else self.app.title
        if full_title != self._title:
            self._title = full_title
            self.send({"type": "title", "title": full_title})
            self.app._backend_title(full_title)


# =============================================================================
# App
# =============================================================================
class App:
    """A desktop application.

        app = App("My App")

        @app.page("/")
        def home():
            return ui.h1("Hello")

        app.run()
    """

    def __init__(self, title="ZePyGUI App", *, theme="auto", accent="#6366f1", width=1100, height=760,
                 min_size=(480, 360), icon=None, css=None, head=None, radius=10, font=None):
        self.title = title
        self.theme = theme
        self.accent = accent
        self.width, self.height = width, height
        self.min_size = min_size
        self.icon = icon
        self.radius = radius
        self.font = font
        self.debug = False
        self.token = None
        self.boot = secrets.token_hex(4)
        self.sessions = {}
        self.window = None  # native window object (macOS), or None
        self._routes = []
        self._layout = None
        self._not_found = None
        self._css = [css] if css else []
        self._head = [head] if head else []
        self._statics = {}
        self._exposed = {}
        self._timers = []
        self._startup, self._shutdown = [], []
        self._lock = threading.Lock()
        self._running = False
        self._ever_connected = False
        self._browser = None
        self._server = None

    # -- declaration ---------------------------------------------------------
    def page(self, path="/", title=None):
        """Register a page. ``path`` may contain parameters: ``/user/{id:int}``."""
        def deco(fn):
            self._routes.append(Route(path, fn, title))
            return fn
        return deco

    def layout(self, fn):
        """Wrap every page: ``fn(content)`` returns the shell that contains ``content``."""
        self._layout = fn
        return fn

    def not_found(self, fn):
        self._not_found = fn
        return fn

    def timer(self, interval, fn=None):
        """Call ``fn`` every ``interval`` seconds in the background (decorator or direct)."""
        def deco(f):
            self._timers.append((interval, f))
            if self._running:
                self._start_timer(interval, f)
            return f
        return deco(fn) if fn is not None else deco

    def expose(self, fn=None, *, name=None):
        """Make a Python function callable from JavaScript: ``await zepygui.call("name", ...)``."""
        def deco(f):
            self._exposed[name or f.__name__] = f
            return f
        return deco(fn) if fn is not None else deco

    def on_startup(self, fn):
        self._startup.append(fn)
        return fn

    def on_shutdown(self, fn):
        self._shutdown.append(fn)
        return fn

    def add_css(self, css):
        self._css.append(css)

    def add_head(self, markup):
        self._head.append(markup)

    def static(self, prefix, directory):
        """Serve files: ``app.static("/assets", "assets")`` then ``ui.image("/assets/logo.png")``."""
        self._statics["/" + prefix.strip("/")] = str(Path(directory).resolve())

    # -- runtime helpers -----------------------------------------------------
    def connected_sessions(self):
        with self._lock:
            return [s for s in self.sessions.values() if s.connected]

    def quit(self):
        """Close the app."""
        if self.window is not None:
            self.window.close()
        elif self._server is not None:
            threading.Thread(target=self._server.shutdown, daemon=True).start()

    def _match(self, path):
        for route in self._routes:
            params = route.match(path)
            if params is not None:
                return route, params
        return None, {}

    def _backend_theme(self, theme):
        if self.window is not None:
            self.window.set_theme(theme)

    def _backend_title(self, title):
        if self.window is not None:
            self.window.set_title(title)

    def _dispatch(self, session, m):
        kind = m.get("type")
        if kind == "event":
            session.queue.put(("event", m.get("h"), m.get("d") or {}, m.get("s") or 0))
        elif kind == "nav":
            session.queue.put(("nav", m.get("path") or "/", False))
        elif kind == "call":
            session.queue.put(("call", m.get("id"), m.get("name"), m.get("args") or []))
        elif kind == "theme":
            session.queue.put(("theme", m.get("theme")))
        elif kind == "resync":
            session.queue.put(("resync",))
        elif kind == "open_url":
            url = str(m.get("url") or "")
            if re.match(r"^(https?|mailto):", url):
                threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    # -- page -------------------------------------------------------------------
    def _index_html(self, inline=False, base="/"):
        cfg = {"title": self.title, "theme": self.theme, "debug": self.debug, "boot": self.boot}
        font = self.font or ("-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI Variable', 'Segoe UI', "
                             "Roboto, 'Helvetica Neue', sans-serif")
        root_vars = f":root{{--accent:{self.accent};--radius:{self.radius}px;--font:{font}}}"
        if inline:
            css = f"<style>{(STATIC_DIR / 'style.css').read_text('utf-8')}</style>"
            js = f"<script>{(STATIC_DIR / 'client.js').read_text('utf-8')}</script>"
        else:
            css = f'<link rel="stylesheet" href="/_pg/style.css?v={self.boot}">'
            js = f'<script src="/_pg/client.js?v={self.boot}"></script>'
        user_css = "".join(f"<style>{c}</style>" for c in self._css)
        return f"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="{base}">
<title>{self.title}</title>
{css}
<style>{root_vars}</style>
{user_css}
{''.join(self._head)}
<script>window.__PG__={json.dumps(cfg)};(function(){{var c=window.__PG__,t=c.theme;try{{t=localStorage.getItem("pg_theme:"+c.title)||t}}catch(e){{}}if(t==="auto")t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";document.documentElement.dataset.theme=t}})();</script>
</head>
<body>
<div id="pg-root"><div class="pg-boot"><span class="pg-spinner pg-spinner-lg"></span></div></div>
<div id="pg-toasts"></div>
<div id="pg-status"><span class="pg-spinner pg-spinner-sm"></span> Reconnecting…</div>
{js}
</body>
</html>"""

    # -- lifecycle --------------------------------------------------------------
    def _start_timer(self, interval, fn):
        def loop():
            while self._running:
                time.sleep(interval)
                if not self._running:
                    return
                try:
                    invoke(fn)
                except Exception:
                    traceback.print_exc()
        threading.Thread(target=loop, daemon=True, name="zepygui-timer").start()

    def _startup_hooks(self):
        _runtime["app"] = self
        self._running = True
        for fn in self._startup:
            invoke(fn)
        for interval, fn in self._timers:
            self._start_timer(interval, fn)

    def _shutdown_hooks(self):
        self._running = False
        for fn in self._shutdown:
            try:
                invoke(fn)
            except Exception:
                traceback.print_exc()
        with self._lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for s in sessions:
            s.close()
        _shutdown_tasks()

    def _initial_theme(self):
        if self.theme in ("dark", "light"):
            return self.theme
        if platform.system() == "Darwin":
            try:
                out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True,
                                     text=True, timeout=2).stdout
                return "dark" if "Dark" in out else "light"
            except (OSError, subprocess.SubprocessError):
                pass
        return "dark"

    def run(self, mode="auto", *, debug=False, reload=False, port=0, host="127.0.0.1"):
        """Start the app and block until its window is closed.

        ``mode``:
          * ``"auto"``   native window on macOS, app window (Edge/Chromium) elsewhere
          * ``"native"`` force the native macOS WKWebView window
          * ``"window"`` chrome-less Edge/Chrome/Chromium app window
          * ``"browser"`` open in the default browser (handy for debugging with dev tools)
          * ``"server"`` open nothing: print the address and serve it (remote use, screenshots, CI)

        The ``ZEPYGUI_MODE`` environment variable overrides ``mode``.
        ``reload=True`` restarts the app whenever a source file changes.
        ``debug=True`` enables the web inspector (right-click > Inspect).
        """
        if multiprocessing.parent_process() is not None:
            # A process-pool worker (ui.task(..., process=True)) re-imports the main script
            # under spawn; it must not open a second window.
            return None
        self.debug = debug
        mode = os.environ.get("ZEPYGUI_MODE") or mode
        port = int(os.environ.get("ZEPYGUI_PORT") or port)
        if reload and not os.environ.get("ZEPYGUI_CHILD"):
            from .reloader import run_with_reloader
            return run_with_reloader()
        if mode == "auto":
            mode = "native" if platform.system() == "Darwin" else "window"
        if mode == "native":
            try:
                from . import macos  # noqa: F401
            except (OSError, AttributeError, ImportError) as exc:
                print(f"[zepygui] native window unavailable ({exc}); using an app window instead")
                mode = "window"
        if mode == "native":
            return self._run_native()
        return self._run_server(mode, host, port)

    # native ----------------------------------------------------------------------
    def _run_native(self):
        from .macos import MacWindow

        workdir = Path(tempfile.mkdtemp(prefix="zepygui-"))
        for prefix, directory in self._statics.items():
            link = workdir / prefix.strip("/")
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(directory, target_is_directory=True)
        html_path = workdir / "index.html"
        html_path.write_text(self._index_html(inline=True, base=workdir.as_uri() + "/"), "utf-8")

        theme = self._initial_theme()
        session = Session(self, "main", "/", theme)
        with self._lock:
            self.sessions[session.id] = session

        def on_message(raw):
            try:
                m = json.loads(raw)
            except ValueError:
                return
            if m.get("type") == "connect":
                session.queue.put(("nav", m.get("path") or "/", False))
                if m.get("theme"):
                    session.queue.put(("theme", m["theme"]))
                session.attach(lambda text: win.eval_js(f"window.__pg_recv({text})"))
                self._ever_connected = True
            else:
                self._dispatch(session, m)

        win = MacWindow(title=self.title, html_path=str(html_path), read_access="/", width=self.width,
                        height=self.height, min_size=self.min_size, theme=theme, debug=self.debug,
                        on_message=on_message, icon=str(Path(self.icon).resolve()) if self.icon else None)
        self.window = win
        signal.signal(signal.SIGINT, signal.SIG_DFL)  # Ctrl+C quits even while Cocoa owns the main thread
        self._startup_hooks()
        try:
            win.run()
        finally:
            self.window = None
            self._shutdown_hooks()
            shutil.rmtree(workdir, ignore_errors=True)

    # server-backed window --------------------------------------------------------
    def _serve_socket(self, ws, sid, path, theme):
        with self._lock:
            session = self.sessions.get(sid)
            if session is None or session.closed:
                session = self.sessions[sid] = Session(self, sid, path, theme)
        out = ws.send
        session.queue.put(("nav", path, False))
        if theme:
            session.queue.put(("theme", theme))
        session.attach(out)  # after nav/theme, so the first render already shows the right page
        self._ever_connected = True
        ws.send(json.dumps({"type": "hello", "boot": self.boot}))
        while True:
            raw = ws.recv()
            if raw is None:
                break
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            self._dispatch(session, m)
        session.detach(out)

    def _reaper(self, mode, launched_at):
        while self._running:
            time.sleep(1)
            now = time.time()
            with self._lock:
                for sid, s in list(self.sessions.items()):
                    if not s.connected and now - s.disconnected_at > 60:
                        s.close()
                        del self.sessions[sid]
                connected = [s for s in self.sessions.values() if s.connected]
                last_seen = max((s.disconnected_at for s in self.sessions.values()), default=0)
            if mode != "window" or connected:
                continue
            window_gone = self._browser is not None and self._browser.poll() is not None
            if (self._ever_connected and now - last_seen > 3) or \
                    (not self._ever_connected and window_gone and now - launched_at > 30):
                self._server.shutdown()
                return

    def _run_server(self, mode, host, port):
        from .server import make_server
        from .window import open_window

        self.token = secrets.token_urlsafe(18)
        if os.environ.get("ZEPYGUI_CHILD"):
            # the reloader stops us with SIGTERM: exit through `finally` so the window closes too
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        self._server = make_server(self, host, port)
        port = self._server.server_address[1]
        url = f"http://127.0.0.1:{port}/?_pgt={self.token}"
        self._startup_hooks()
        launched_at = time.time()
        if mode == "window":
            self._browser = open_window(url, self.title, self.width, self.height)
            if self._browser is None:
                print("[zepygui] no Edge/Chrome/Chromium found; opening your default browser instead")
                webbrowser.open(url)
        elif mode == "server":
            print(f"[zepygui] serving on {url}", flush=True)
        else:
            webbrowser.open(url)
        threading.Thread(target=self._reaper, args=(mode, launched_at), daemon=True).start()
        print(f"[zepygui] {self.title} is running (Ctrl+C to quit)")
        try:
            self._server.serve_forever(poll_interval=0.25)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            for s in self.connected_sessions():
                s.send({"type": "close"})
            self._shutdown_hooks()
            self._server.server_close()
            if self._browser is not None and self._browser.poll() is None:
                self._browser.terminate()

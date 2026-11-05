"""ZePyGUI component library.

Every function returns an :class:`Element`. Build trees by nesting calls::

    ui.card(ui.h3("Hello"), ui.button("Click", on_click=handler))

or with ``with`` blocks::

    with ui.card():
        ui.h3("Hello")
        ui.button("Click", on_click=handler)
"""
from __future__ import annotations

import functools
import html as _html
import inspect
import math
import re
import textwrap

from .forms import Field, Form
from .state import State, _local, _targets, current_session, spawn

__all__ = [
    # core
    "Element", "component", "use_state", "use_form", "use_field", "el", "div", "span", "fragment", "html", "session",
    # layout
    "column", "row", "grid", "container", "spacer", "divider", "card", "scroll_area",
    "shell", "sidebar", "nav_item", "nav_section", "header",
    # typography
    "h1", "h2", "h3", "h4", "text", "code", "code_block", "link", "markdown", "kbd",
    # inputs
    "button", "icon_button", "input", "textarea", "checkbox", "switch", "slider", "select",
    "radio_group", "segmented", "form",
    # display
    "icon", "register_icon", "badge", "avatar", "progress", "spinner", "alert", "stat", "image",
    "table", "tabs", "accordion", "modal", "tooltip", "empty_state", "theme_toggle",
    # charts
    "line_chart", "bar_chart", "donut", "sparkline",
    # large data
    "virtual_list", "log_view",
    # actions
    "toast", "navigate", "run_js", "set_title", "set_theme", "toggle_theme", "copy", "background",
    # background work
    "task", "run_command",
]


# =============================================================================
# Core element model
# =============================================================================
def _attr(name):
    if name in ("cls", "class_"):
        return "class"
    if name.endswith("_"):
        name = name[:-1]
    return name.replace("_", "-")


def _style_dict(style):
    if style is None:
        return {}
    if isinstance(style, dict):
        return dict(style)
    out = {}
    for part in str(style).split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _is_iterable_children(c):
    return isinstance(c, (list, tuple, map, filter)) or inspect.isgenerator(c)


class Element:
    """A node of the UI tree: an HTML tag with attributes, events and children."""

    __slots__ = ("tag", "attrs", "events", "children", "key", "html", "_parent")

    def __init__(self, tag, *children, cls=None, style=None, key=None, **props):
        self._setup(tag, key)
        if cls:
            self.classes(cls)
        if style:
            self.style(style)
        for name, value in props.items():
            if name.startswith("on_") and (value is None or callable(value)):
                if value is not None:
                    self.on(name[3:], value)
            else:
                self.attrs[_attr(name)] = value
        self.add(*children)
        self._auto_attach()

    def _setup(self, tag, key):
        self.tag = tag
        self.attrs = {}
        self.events = {}
        self.children = []
        self.key = key
        self.html = None
        self._parent = None

    def _auto_attach(self):
        stack = getattr(_local, "stack", None)
        if stack:
            stack[-1]._adopt(self)

    def _detach(self):
        # O(1): the old parent keeps a stale entry, which readers skip because its _parent
        # no longer points back (see live_children). Rebuilding the list here made every
        # adoption O(siblings) and building N rows O(N²).
        self._parent = None

    def _adopt(self, child):
        if child._parent is self:  # re-adding an existing child moves it to the end
            self.children.remove(child)
        child._parent = self
        self.children.append(child)

    def live_children(self):
        """Children that still belong to this element (moved elements are skipped)."""
        return [c for c in self.children if not isinstance(c, Element) or c._parent is self]

    # -- building ------------------------------------------------------------
    def add(self, *children):
        """Append children (elements, strings, numbers, States, callables, lists)."""
        for c in children:
            if c is None or c is False or c is True:
                continue
            if isinstance(c, Element):
                self._adopt(c)
            elif isinstance(c, State) or isinstance(c, str):
                self.children.append(c)
            elif _is_iterable_children(c):
                self.add(*c)
            else:
                self.children.append(c)
        return self

    def classes(self, *names):
        """Add CSS classes."""
        extra = " ".join(n for n in names if n)
        current = self.attrs.get("class")
        self.attrs["class"] = f"{current} {extra}".strip() if current else extra
        return self

    def style(self, style=None, **rules):
        """Merge inline styles: ``.style({"color": "red"})`` or ``.style(padding=12)``."""
        merged = _style_dict(self.attrs.get("style"))
        merged.update(_style_dict(style))
        merged.update(rules)
        self.attrs["style"] = merged
        return self

    def props(self, **attrs):
        """Set HTML attributes (``data_id=3`` becomes ``data-id="3"``)."""
        for name, value in attrs.items():
            self.attrs[_attr(name)] = value
        return self

    def on(self, event, handler, *, keys=None, prevent=False, stop=False, debounce=None, throttle=None,
           self_only=False, transform=None):
        """Attach an event handler. ``event`` is a DOM event name (click, input, keydown...).

        Shortcuts: ``"enter"`` and ``"escape"`` listen to keydown for that key only.
        ``debounce`` (milliseconds) waits for the user to pause before sending.
        ``throttle`` (milliseconds) sends at most one event per interval, always including the last.
        """
        dom = event
        if event in ("enter", "escape"):
            dom, keys = "keydown", [event.capitalize()]
        self.events[event] = (handler, {
            "dom": dom, "keys": list(keys) if keys else None, "prevent": prevent, "stop": stop,
            "debounce": debounce, "throttle": throttle, "self": self_only, "transform": transform,
        })
        return self

    def tooltip(self, text):
        """Show ``text`` when hovering this element."""
        self.attrs["data-tip"] = text
        return self

    # -- context manager -----------------------------------------------------
    def __enter__(self):
        if not hasattr(_local, "stack"):
            _local.stack = []
        _local.stack.append(self)
        return self

    def __exit__(self, *exc):
        _local.stack.pop()
        return False

    def __repr__(self):
        return f"<{self.tag} {self.attrs} children={len(self.children)}>"


def _claim(value):
    """Detach elements passed as arguments so they don't also render where they were created."""
    t = type(value)
    if t in _SCALARS:
        return
    if isinstance(value, Element):
        value._detach()
    elif isinstance(value, (list, tuple)):
        for v in value:
            if type(v) not in _SCALARS:
                _claim(v)
    elif isinstance(value, dict):
        for v in value.values():
            if type(v) not in _SCALARS:
                _claim(v)


_SCALARS = frozenset((str, int, float, bool, type(None), bytes))


def _find(value, wanted, found):
    """Move the ids of ``wanted`` elements reachable from ``value`` into ``found``.

    Returns True once nothing is left to look for, so a search over a large data
    argument stops as soon as every candidate has been seen."""
    t = type(value)
    if t in _SCALARS:
        return False
    if isinstance(value, Element):
        if id(value) in wanted:
            wanted.discard(id(value))
            found.add(id(value))
            return not wanted
        return False
    if isinstance(value, dict):
        value = value.values()
    elif not isinstance(value, (list, tuple)):
        return False
    for v in value:
        if type(v) not in _SCALARS and _find(v, wanted, found):
            return True
    return False


class ComponentCall(Element):
    """A lazily-rendered ``@component`` invocation (gets its own ``use_state`` hooks)."""

    __slots__ = ("fn", "args", "kwargs")

    def __init__(self, fn, args, kwargs, key=None):
        self._setup(None, key)
        self.fn, self.args, self.kwargs = fn, args, kwargs
        renderer = getattr(_local, "renderer", None)
        stack = getattr(_local, "stack", None)
        if renderer is not None and stack:
            # Defer: elements passed as arguments are only looked for if they are still in
            # place when their parent is serialised (usually they have been moved into the
            # layout by then). Walking the arguments now would cost O(data) per render for
            # every table or list component.
            top = stack[-1]
            renderer.claims.setdefault(id(top), []).append((self, len(top.children)))
        else:
            _claim(args)
            _claim(kwargs)
        self._auto_attach()


def component(fn):
    """Turn a function into a reusable component with its own local state.

        @ui.component
        def Counter(label):
            n = ui.use_state(0)
            return ui.button(f"{label}: {n.value}", on_click=lambda: n.set(n.value + 1))
    """

    @functools.wraps(fn)
    def make(*args, key=None, **kwargs):
        return ComponentCall(fn, args, kwargs, key)

    return make


def use_state(default=None):
    """Per-window state local to the page or component being rendered.

    ``default`` may be a callable, evaluated only the first time.
    """
    renderer = getattr(_local, "renderer", None)
    if renderer is None:
        raise RuntimeError("use_state() must be called while rendering a page or a @component")
    return renderer.hook(default)


def use_form(fields=None, **kw):
    """A :class:`~zepygui.forms.Form` local to this page or component (kept across renders).

        form = ui.use_form(email=("", [rules.required(), rules.email()]), remember=False)
        ui.input(form.email, label="Email")
    """
    return use_state(lambda: Form(fields, **kw)).value


def use_field(default=None, *rules):
    """A single validated :class:`~zepygui.forms.Field` local to this page or component.

        name = ui.use_field("", rules.required(), rules.max_length(40))
        ui.input(name, label="Name")
    """
    return use_state(lambda: Field(default, rules)).value


def session():
    """The current window's Session (has ``.path``, ``.query``, ``.data`` dict...)."""
    return current_session()


def el(tag, *children, **kw):
    """Any HTML element: ``ui.el("section", ..., cls="x", on_click=f, data_id=1)``."""
    return Element(tag, *children, **kw)


def div(*children, **kw):
    return Element("div", *children, **kw)


def span(*children, **kw):
    return Element("span", *children, **kw)


def fragment(*children):
    """Group children without adding a wrapper element."""
    return Element("", *children)


def html(markup, tag="div", **kw):
    """Raw HTML (not escaped, so only pass content you trust)."""
    e = Element(tag, **kw)
    e.html = str(markup)
    return e


def _discard(*items):
    for item in items:
        _claim(item)
    return fragment()


# =============================================================================
# Helpers
# =============================================================================
_ALIGN = {"start": "flex-start", "end": "flex-end", "center": "center", "stretch": "stretch",
          "baseline": "baseline", "between": "space-between", "around": "space-around",
          "evenly": "space-evenly"}


def _c(*names):
    return " ".join(n for n in names if n) or None


def _sp(value):
    """Spacing scale: numbers are 4px steps (4 -> 16px); strings are used as-is."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value * 4:g}px"
    return value


def _px(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value}px"
    return value


def _merge(base, extra):
    out = {k: v for k, v in base.items() if v is not None}
    out.update(_style_dict(extra))
    return out


def _val(v):
    return v.value if isinstance(v, State) else v


def _bind(value, on_change):
    """Shared two-way binding logic: returns (current_value, handler)."""
    bound = value if isinstance(value, State) else None
    current = bound.value if bound is not None else value
    if bound is None and on_change is None:
        return current, None

    def handle(v):
        if bound is not None:
            bound.set(v)
        if on_change is not None:
            from .state import invoke
            invoke(on_change, v)

    return current, handle


def _options(options):
    if isinstance(options, State):
        options = options.value
    if isinstance(options, dict):
        return [(k, v) for k, v in options.items()]
    out = []
    for o in options:
        if isinstance(o, (list, tuple)):
            out.append((o[0], o[1] if len(o) > 1 else o[0]))
        else:
            out.append((o, o))
    return out


def _coerce(raw, sample):
    """Convert the string the browser sends back to the type of the original option."""
    if isinstance(sample, bool):
        return raw in ("True", "true", "1")
    if isinstance(sample, int):
        try:
            return int(raw)
        except ValueError:
            return raw
    if isinstance(sample, float):
        try:
            return float(raw)
        except ValueError:
            return raw
    return raw


# =============================================================================
# Icons (24x24 stroke icons)
# =============================================================================
def _circ(cx, cy, r):
    return f"M{cx - r} {cy}a{r} {r} 0 1 0 {2 * r} 0a{r} {r} 0 1 0 {-2 * r} 0"


def _gear():
    pts = []
    for i in range(8):
        a = math.radians(i * 45)
        for r, d in ((7.2, -17), (9.6, -9), (9.6, 9), (7.2, 17)):
            t = a + math.radians(d)
            pts.append(f"{12 + r * math.cos(t):.2f} {12 + r * math.sin(t):.2f}")
    return "M" + "L".join(pts) + "Z"


ICONS = {
    "check": ["M20 6 9 17l-5-5"],
    "x": ["M18 6 6 18", "M6 6l12 12"],
    "plus": ["M12 5v14", "M5 12h14"],
    "minus": ["M5 12h14"],
    "chevron-right": ["m9 18 6-6-6-6"],
    "chevron-left": ["m15 18-6-6 6-6"],
    "chevron-down": ["m6 9 6 6 6-6"],
    "chevron-up": ["m18 15-6-6-6 6"],
    "arrow-right": ["M5 12h14", "m12 5 7 7-7 7"],
    "arrow-left": ["M19 12H5", "m12 19-7-7 7-7"],
    "arrow-up": ["M12 19V5", "m5 12 7-7 7 7"],
    "arrow-down": ["M12 5v14", "m19 12-7 7-7-7"],
    "home": ["M3 10.5 12 3l9 7.5", "M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"],
    "search": [_circ(11, 11, 7), "m20 20-4.3-4.3"],
    "user": [_circ(12, 8, 4), "M4 21a8 8 0 0 1 16 0"],
    "users": [_circ(9, 8, 4), "M2 21a7 7 0 0 1 14 0", "M16 3.13a4 4 0 0 1 0 7.75", "M22 21a7 7 0 0 0-5-6.7"],
    "settings": [_gear(), _circ(12, 12, 3)],
    "sliders": ["M4 21v-7", "M4 10V3", "M12 21v-9", "M12 8V3", "M20 21v-5", "M20 12V3",
                "M1 14h6", "M9 8h6", "M17 16h6"],
    "sun": [_circ(12, 12, 4), "M12 2v2", "M12 20v2", "m4.93 4.93 1.41 1.41", "m17.66 17.66 1.41 1.41",
            "M2 12h2", "M20 12h2", "m6.34 17.66-1.41 1.41", "m19.07 4.93-1.41 1.41"],
    "moon": ["M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"],
    "bell": ["M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9", "M10.3 21a1.94 1.94 0 0 0 3.4 0"],
    "heart": ["M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2"
              "A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"],
    "star": ["M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"],
    "trash": ["M3 6h18", "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6", "M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"],
    "edit": ["M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"],
    "menu": ["M4 6h16", "M4 12h16", "M4 18h16"],
    "info": [_circ(12, 12, 10), "M12 16v-4", "M12 8h.01"],
    "alert": ["M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z",
              "M12 9v4", "M12 17h.01"],
    "alert-circle": [_circ(12, 12, 10), "M12 8v4", "M12 16h.01"],
    "check-circle": [_circ(12, 12, 10), "m9 12 2 2 4-4"],
    "x-circle": [_circ(12, 12, 10), "m15 9-6 6", "m9 9 6 6"],
    "mail": ["M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z", "m22 6-10 7L2 6"],
    "calendar": ["M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
                 "M16 2v4", "M8 2v4", "M3 10h18"],
    "chart": ["M3 3v18h18", "M8 17v-6", "M13 17V7", "M18 17v-3"],
    "folder": ["M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4"
               "a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"],
    "file": ["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6"],
    "download": ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "m7 10 5 5 5-5", "M12 15V3"],
    "upload": ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "m17 8-5-5-5 5", "M12 3v12"],
    "refresh": ["M21 12a9 9 0 1 1-2.64-6.36L21 8", "M21 3v5h-5"],
    "log-out": ["M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4", "m16 17 5-5-5-5", "M21 12H9"],
    "play": ["M6 3l14 9-14 9V3z"],
    "pause": ["M6 4h4v16H6z", "M14 4h4v16h-4z"],
    "clock": [_circ(12, 12, 10), "M12 6v6l4 2"],
    "lock": ["M5 11h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z", "M7 11V7a5 5 0 0 1 10 0v4"],
    "eye": ["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z", _circ(12, 12, 3)],
    "grid": ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M14 14h7v7h-7z", "M3 14h7v7H3z"],
    "list": ["M8 6h13", "M8 12h13", "M8 18h13", "M3 6h.01", "M3 12h.01", "M3 18h.01"],
    "copy": ["M10 8h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2z",
             "M4 16a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2"],
    "external": ["M15 3h6v6", "M10 14 21 3", "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"],
    "zap": ["M13 2 3 14h9l-1 8 10-12h-9l1-8z"],
    "sparkles": ["M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z", "M19 3v4", "M17 5h4"],
    "box": ["M21 8l-9-5-9 5 9 5 9-5z", "M3 8v8l9 5 9-5V8", "M12 13v8"],
    "dollar": ["M12 2v20", "M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"],
    "trending-up": ["m22 7-8.5 8.5-5-5L2 17", "M16 7h6v6"],
    "trending-down": ["m22 17-8.5-8.5-5 5L2 7", "M16 17h6v-6"],
    "activity": ["M22 12h-4l-3 9L9 3l-3 9H2"],
    "globe": [_circ(12, 12, 10), "M2 12h20",
              "M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"],
    "message": ["M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"],
    "send": ["m22 2-7 20-4-9-9-4Z", "M22 2 11 13"],
    "filter": ["M22 3H2l8 9.46V19l4 2v-8.54L22 3z"],
    "more": ["M5 12h.01", "M12 12h.01", "M19 12h.01"],
    "image": ["M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z", _circ(9, 9, 2),
              "m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"],
    "code": ["m16 18 6-6-6-6", "m8 6-6 6 6 6"],
    "terminal": ["m4 17 6-6-6-6", "M12 19h8"],
    "shield": ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"],
    "bookmark": ["m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"],
    # files and devices
    "folder-open": ["m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4"
                    "a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"],
    "folder-plus": ["M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4"
                    "a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z", "M12 10v6", "M9 13h6"],
    "file-text": ["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6", "M16 13H8",
                  "M16 17H8", "M10 9H8"],
    "file-code": ["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6", "m10 13-2 2 2 2",
                  "m14 17 2-2-2-2"],
    "hard-drive": ["M22 12H2", "M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4"
                   "H7.24a2 2 0 0 0-1.79 1.11z", "M6 16h.01", "M10 16h.01"],
    "usb": [_circ(10, 7, 1), _circ(4, 20, 1), "M4.7 19.3 19 5", "m21 3-3 1 2 2Z", "M9.26 7.68 5 12l2 5",
            "m10 14 5 2 3.5-3.5", "m18 12 1-1 1 1-1 1Z"],
    "disc": [_circ(12, 12, 10), _circ(12, 12, 2)],
    "server": ["M4 2h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z",
               "M4 14h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2z", "M6 6h.01", "M6 18h.01"],
    "monitor": ["M4 3h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z", "M8 21h8", "M12 17v4"],
    "laptop": ["M20 16V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9m16 0H4m16 0 1.28 2.55a1 1 0 0 1-.9 1.45H3.62"
               "a1 1 0 0 1-.9-1.45L4 16"],
    "music": ["M9 18V5l12-2v13", _circ(6, 18, 3), _circ(18, 16, 3)],
    "video": ["m22 8-6 4 6 4V8Z", "M4 6h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z"],
    "archive": ["M3 3h18a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z",
                "M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8", "M10 12h4"],
    "table": ["M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z", "M3 9h18", "M3 15h18",
              "M9 3v18"],
    "presentation": ["M2 3h20", "M21 3v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V3", "m7 21 5-5 5 5"],
    "database": ["M3 5c0-1.66 4-3 9-3s9 1.34 9 3-4 3-9 3-9-1.34-9-3", "M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5",
                 "M3 12c0 1.66 4 3 9 3s9-1.34 9-3"],
    "type": ["M4 7V4h16v3", "M9 20h6", "M12 4v16"],
    "app": ["M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z", "M2 9h20", "M6 6.5h.01",
            "M9 6.5h.01"],
    "link": ["M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71",
             "M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"],
    "cloud": ["M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"],
    # editing and navigation
    "corner-left-up": ["M14 9 9 4 4 9", "M20 20h-7a4 4 0 0 1-4-4V4"],
    "arrow-up-down": ["m21 16-4 4-4-4", "M17 20V4", "m3 8 4-4 4 4", "M7 4v16"],
    "eye-off": ["M9.88 9.88a3 3 0 1 0 4.24 4.24", "M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 "
                "1-1.67 2.68", "M6.61 6.61A13.53 13.53 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61", "m2 2 20 20"],
    "clipboard": ["M9 2h6a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z",
                  "M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"],
    "scissors": [_circ(6, 6, 3), _circ(6, 18, 3), "M20 4 8.12 15.88", "M14.47 14.48 20 20", "M8.12 8.12 12 12"],
    "pin": ["M12 17v5", "M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76"
            "a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"],
    "panel-right": ["M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z", "M15 3v18"],
    "panel-left": ["M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z", "M9 3v18"],
    "maximize": ["M8 3H5a2 2 0 0 0-2 2v3", "M21 8V5a2 2 0 0 0-2-2h-3", "M3 16v3a2 2 0 0 0 2 2h3",
                 "M16 21h3a2 2 0 0 0 2-2v-3"],
    "rows": ["M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z", "M3 9h18", "M3 15h18"],
}


def register_icon(name, *paths):
    """Add your own icon from SVG path ``d`` strings drawn on a 24x24 grid."""
    ICONS[name] = list(paths)
    _ICON_MARKUP.pop(name, None)


_ICON_MARKUP = {}


def _icon_markup(name, paths):
    """The icon's <path> elements as one trusted markup string, built once per icon.

    Sending this as the svg's inner HTML makes an icon one node on the wire and in the
    DOM patcher, instead of one node per path."""
    markup = _ICON_MARKUP.get(name)
    if markup is None:
        markup = _ICON_MARKUP[name] = "".join(f'<path d="{_html.escape(d)}"/>' for d in paths)
    return markup


def _icon(name, size=18, color=None, stroke=2, cls=None, **kw):
    if isinstance(name, Element):
        return name
    paths = ICONS.get(name)
    if paths is None:
        return span(name, cls=_c("pg-icon-text", cls))
    style = {}
    if color:
        style["color"] = color
    if stroke != 2:  # inline: the .pg-icon CSS rule would beat a presentation attribute
        style["stroke-width"] = stroke
    # fill, stroke colour, caps and joins come from the .pg-icon rule in style.css
    svg = Element("svg", cls=_c("pg-icon", cls), style=style or None, width=size, height=size,
                  viewBox="0 0 24 24", **kw)
    svg.html = _icon_markup(name, paths)
    return svg


def icon(name, size=18, color=None, stroke=2, **kw):
    """A built-in icon by name (see ``ui.ICONS``), e.g. ``ui.icon("home")``."""
    return _icon(name, size=size, color=color, stroke=stroke, **kw)


# =============================================================================
# Layout
# =============================================================================
def column(*children, gap=3, align=None, justify=None, padding=None, cls=None, style=None, **kw):
    """Vertical stack. ``gap``/``padding`` use the 4px scale (4 -> 16px)."""
    st = {"gap": _sp(gap), "align-items": _ALIGN.get(align, align),
          "justify-content": _ALIGN.get(justify, justify), "padding": _sp(padding)}
    return Element("div", *children, cls=_c("pg-col", cls), style=_merge(st, style), **kw)


def row(*children, gap=3, align="center", justify=None, wrap=False, padding=None, cls=None, style=None, **kw):
    """Horizontal stack."""
    st = {"gap": _sp(gap), "align-items": _ALIGN.get(align, align),
          "justify-content": _ALIGN.get(justify, justify), "padding": _sp(padding),
          "flex-wrap": "wrap" if wrap else None}
    return Element("div", *children, cls=_c("pg-row", cls), style=_merge(st, style), **kw)


def grid(*children, cols=3, gap=4, min_width=None, responsive=True, cls=None, style=None, **kw):
    """CSS grid. ``cols`` is a count or template; ``min_width`` makes an auto-filling grid."""
    if min_width is not None:
        template = f"repeat(auto-fill, minmax(min({_px(min_width)}, 100%), 1fr))"
    elif isinstance(cols, int):
        template = f"repeat({cols}, minmax(0, 1fr))"
    else:
        template = cols
    st = {"--cols": template, "gap": _sp(gap)}
    return Element("div", *children, cls=_c("pg-grid", "pg-responsive" if responsive else None, cls),
                   style=_merge(st, style), **kw)


def container(*children, max_width=1100, padding=6, cls=None, style=None, **kw):
    """Centered, width-limited content area."""
    st = {"max-width": _px(max_width), "padding": _sp(padding)}
    return Element("div", *children, cls=_c("pg-container", cls), style=_merge(st, style), **kw)


def spacer():
    """Flexible space that pushes siblings apart in a row/column."""
    return Element("div", cls="pg-spacer")


def divider(label=None, vertical=False):
    if vertical:
        return Element("div", cls="pg-divider-v")
    if label:
        return Element("div", span(label), cls="pg-divider pg-divider-label")
    return Element("div", cls="pg-divider")


def card(*children, title=None, subtitle=None, actions=None, padding=5, hover=False, cls=None, style=None, **kw):
    """Surface with rounded corners. ``actions`` render top-right next to the title."""
    head = None
    if title is not None or actions is not None:
        head = row(
            column(Element("div", title, cls="pg-card-title") if title is not None else None,
                   Element("div", subtitle, cls="pg-card-subtitle") if subtitle else None, gap=0.5),
            spacer(),
            row(actions, gap=2) if actions is not None else None,
            cls="pg-card-head", align="start",
        )
    clickable = "pg-card-click" if kw.get("on_click") else None
    return Element("div", head, *children,
                   cls=_c("pg-card", "pg-card-hover" if hover else None, clickable, cls),
                   style=_merge({"--pad": _sp(padding)}, style), **kw)


def scroll_area(*children, height=300, cls=None, style=None, **kw):
    return Element("div", *children, cls=_c("pg-scroll", cls),
                   style=_merge({"max-height": _px(height)}, style), **kw)


def shell(*content, sidebar=None, header=None, cls=None, style=None, **kw):
    """Classic application layout: sidebar on the left, sticky header, scrolling content."""
    return Element("div",
                   sidebar,
                   Element("div", header, Element("main", *content, cls="pg-content"), cls="pg-main"),
                   cls=_c("pg-shell", cls), style=style, **kw)


def sidebar(*children, title=None, logo="sparkles", footer=None, cls=None, style=None, **kw):
    brand = None
    if title is not None:
        mark = Element("div", _icon(logo, 17, stroke=2.2) if isinstance(logo, str) else logo, cls="pg-brand-mark")
        brand = Element("div", mark, Element("span", title, cls="pg-nav-label"), cls="pg-brand")
    return Element("aside", brand, Element("nav", *children, cls="pg-nav"),
                   Element("div", footer, cls="pg-sidebar-footer") if footer is not None else None,
                   cls=_c("pg-sidebar", cls), style=style, **kw)


def nav_section(label):
    return Element("div", label, cls="pg-nav-section pg-nav-label")


def nav_item(label, to=None, icon=None, on_click=None, active=None, badge=None, cls=None, **kw):
    """Sidebar link. Highlights itself when the current page matches ``to``."""
    if active is None and to is not None:
        s = current_session()
        path = s.path if s is not None else ""
        active = path == to or (to != "/" and path.startswith(to.rstrip("/") + "/"))
    children = [_icon(icon, 18) if icon else None, Element("span", label, cls="pg-nav-label")]
    if badge is not None:
        children.append(Element("span", str(badge), cls="pg-nav-badge pg-nav-label"))
    classes = _c("pg-nav-item", "active" if active else None, cls)
    if to is not None:
        return Element("a", *children, href=to, data_pg_link=True, cls=classes, on_click=on_click,
                       title=label, **kw)
    return Element("button", *children, type="button", cls=classes, on_click=on_click, title=label, **kw)


def header(*children, title=None, cls=None, style=None, **kw):
    """Sticky, translucent top bar."""
    return Element("header",
                   Element("div", title, cls="pg-header-title") if title is not None else None,
                   *children, cls=_c("pg-header", cls), style=style, **kw)


# =============================================================================
# Typography
# =============================================================================
def _heading(tag):
    def make(*children, cls=None, **kw):
        return Element(tag, *children, cls=_c(f"pg-{tag}", cls), **kw)

    make.__name__ = tag
    make.__doc__ = f"<{tag}> heading."
    return make


h1, h2, h3, h4 = (_heading(t) for t in ("h1", "h2", "h3", "h4"))


def text(*children, size=None, weight=None, color=None, muted=False, align=None, mono=False,
         truncate=False, tag="p", cls=None, style=None, **kw):
    """Paragraph text. ``size``: xs/sm/md/lg/xl. ``color``: muted/faint/accent/green/red/yellow or CSS."""
    named = {"muted", "faint", "accent", "green", "red", "yellow", "blue"}
    color_cls = f"pg-c-{color}" if color in named else None
    st = {"font-weight": weight, "text-align": align, "color": None if color in named else color}
    return Element(tag, *children,
                   cls=_c("pg-text", f"pg-text-{size}" if size else None, color_cls,
                          "pg-c-muted" if muted else None, "pg-mono" if mono else None,
                          "pg-truncate" if truncate else None, cls),
                   style=_merge(st, style), **kw)


def code(content, **kw):
    """Inline code."""
    return Element("code", content, cls="pg-code", **kw)


def code_block(content, language=None, copyable=True, **kw):
    """Multi-line code with a copy button."""
    content = textwrap.dedent(str(content)).strip("\n")
    return Element("div",
                   Element("button", _icon("copy", 15), type="button", cls="pg-copy-btn", data_pg_copy=content,
                           title="Copy") if copyable else None,
                   Element("span", language, cls="pg-codeblock-lang") if language else None,
                   Element("pre", Element("code", content)), cls="pg-codeblock", **kw)


def link(content, to=None, href=None, new_tab=False, cls=None, **kw):
    """In-app link (``to="/page"``) or external link (``href="https://..."``)."""
    if to is not None:
        return Element("a", content, href=to, data_pg_link=True, cls=_c("pg-link", cls), **kw)
    extra = {"target": "_blank", "rel": "noopener"} if new_tab else {}
    return Element("a", content, href=href, cls=_c("pg-link", cls), **extra, **kw)


def kbd(content):
    return Element("kbd", content, cls="pg-kbd")


def _safe_url(url):
    return url if not re.match(r"\s*(javascript|vbscript|data):", url, re.I) else "#"


def _md_inline(s):
    codes = []

    def stash(m):
        codes.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    s = _html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", stash, s)
    s = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)",
               lambda m: f'<img alt="{m.group(1)}" src="{_html.escape(_safe_url(m.group(2)))}">', s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
               lambda m: f'<a href="{_html.escape(_safe_url(m.group(2)))}" target="_blank" rel="noopener">'
                         f'{m.group(1)}</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"~~(.+?)~~", r"<del>\1</del>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def _markdown_to_html(src):
    lines = textwrap.dedent(src).strip("\n").split("\n")
    out, para, i = [], [], 0

    def flush():
        if para:
            out.append(f"<p>{_md_inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            lang = stripped[3:].strip()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            cls = f' class="lang-{_html.escape(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{_html.escape(chr(10).join(body))}</code></pre>")
        elif not stripped:
            flush()
        elif re.match(r"^#{1,6}\s", stripped):
            flush()
            level = len(stripped) - len(stripped.lstrip("#"))
            out.append(f"<h{level}>{_md_inline(stripped[level:].strip())}</h{level}>")
        elif re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush()
            out.append("<hr>")
        elif stripped.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(f"<blockquote>{_md_inline(' '.join(quote))}</blockquote>")
            continue
        elif re.match(r"^([-*+]|\d+[.)])\s", stripped):
            flush()
            ordered = bool(re.match(r"^\d", stripped))
            tag = "ol" if ordered else "ul"
            items = []
            while i < len(lines) and re.match(r"^\s*([-*+]|\d+[.)])\s", lines[i]):
                item = re.sub(r"^\s*([-*+]|\d+[.)])\s", "", lines[i])
                task = re.match(r"^\[( |x|X)\]\s", item)
                if task:
                    checked = " checked" if task.group(1) != " " else ""
                    item = f'<input type="checkbox" disabled{checked}> ' + _md_inline(item[4:])
                    items.append(f'<li class="task">{item}</li>')
                else:
                    items.append(f"<li>{_md_inline(item)}</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        else:
            para.append(stripped)
        i += 1
    flush()
    return "\n".join(out)


def markdown(content, cls=None, **kw):
    """Render Markdown (headings, emphasis, lists, task lists, links, images, code, quotes)."""
    return html(_markdown_to_html(str(_val(content))), cls=_c("pg-md", cls), **kw)


# =============================================================================
# Inputs
# =============================================================================
def button(label=None, on_click=None, *, variant="primary", size="md", icon=None, icon_right=None,
           disabled=False, loading=False, full=False, submit=False, cls=None, style=None, **kw):
    """Button. ``variant``: primary, secondary, outline, ghost, soft, danger, success."""
    children = [spinner("sm") if loading else (_icon(icon, 16 if size != "lg" else 18) if icon else None)]
    if label is not None:
        children.append(Element("span", label))
    if icon_right:
        children.append(_icon(icon_right, 16))
    return Element("button", *children,
                   cls=_c("pg-btn", f"pg-btn-{variant}", f"pg-btn-{size}", "pg-btn-full" if full else None,
                          "pg-btn-square" if label is None else None, cls),
                   type="submit" if submit else "button", disabled=bool(disabled or loading),
                   on_click=None if (disabled or loading) else on_click, style=style, **kw)


def icon_button(name, on_click=None, *, variant="ghost", size="md", tooltip=None, **kw):
    b = button(None, on_click, variant=variant, size=size, icon=name, **kw)
    if tooltip:
        b.tooltip(tooltip)
        b.attrs["aria-label"] = tooltip
    return b


def _unfield(value, error, on_change):
    """Unwrap a validation Field passed as ``value``: returns (State, error, on_change, on_blur, required)."""
    if not isinstance(value, Field):
        return value, error, on_change, None, False
    f = value

    def changed(v):
        f._changed()
        if on_change is not None:
            from .state import invoke
            invoke(on_change, v)

    return f.state, (error if error is not None else f.visible_error), changed, f.touch, f.required


def _field(control, label, hint, error, key, cls, style, required=False):
    return Element("label",
                   Element("span", label, cls=_c("pg-label", "pg-required" if required else None)) if label else None,
                   control,
                   Element("span", error, cls="pg-error-text") if error else
                   (Element("span", hint, cls="pg-hint") if hint else None),
                   cls=_c("pg-field", cls), style=style, key=key)


def input(value=None, *, placeholder=None, label=None, type="text", on_change=None, on_enter=None,
          icon=None, hint=None, error=None, disabled=False, debounce=None, autofocus=False,
          clearable=False, key=None, cls=None, style=None, **kw):
    """Text input. Pass a ``State`` as ``value`` for automatic two-way binding.

    ``on_change(value)`` fires as the user types; ``on_enter(value)`` when Enter is pressed.
    """
    numeric = type == "number"
    value, error, on_change, on_blur, required = _unfield(value, error, on_change)

    def parse(ev):
        v = ev.value if ev.value is not None else ""
        if numeric:
            try:
                f = float(v)
                return int(f) if f.is_integer() and "." not in v else f
            except ValueError:
                return None
        return v

    current, handle = _bind(value, on_change)
    attrs = dict(kw)
    if handle is not None or value is not None:
        attrs["value"] = "" if current is None else current
    if error:
        attrs["aria-invalid"] = "true"
    inp = Element("input", cls="pg-input", type=type, placeholder=placeholder, disabled=disabled,
                  autofocus=autofocus, aria_required="true" if required else None, **attrs)
    if handle is not None:
        inp.on("input", handle, transform=parse, debounce=debounce)
    if on_blur is not None:
        inp.on("blur", on_blur)
    if on_enter is not None:
        inp.on("enter", on_enter, transform=parse)
    clear = None
    if clearable and handle is not None and current:
        clear = Element("button", _icon("x", 14), type="button", cls="pg-input-clear",
                        on_click=lambda: handle("" if not numeric else None))
    wrap = Element("div", _icon(icon, 16, cls="pg-input-icon") if icon else None, inp, clear,
                   cls=_c("pg-input-wrap", "pg-invalid" if error else None, "pg-disabled" if disabled else None))
    return _field(wrap, label, hint, error, key, cls, style, required)


def textarea(value=None, *, placeholder=None, label=None, rows=4, on_change=None, hint=None, error=None,
             disabled=False, debounce=None, autofocus=False, key=None, cls=None, style=None, **kw):
    """Multi-line text input (two-way binds a ``State`` or ``Field`` like :func:`input`)."""
    value, error, on_change, on_blur, required = _unfield(value, error, on_change)
    current, handle = _bind(value, on_change)
    attrs = dict(kw)
    if handle is not None or value is not None:
        attrs["value"] = "" if current is None else current
    ta = Element("textarea", cls="pg-input pg-textarea", rows=rows, placeholder=placeholder, disabled=disabled,
                 autofocus=autofocus, **attrs)
    if handle is not None:
        ta.on("input", handle, transform=lambda ev: ev.value or "", debounce=debounce)
    if on_blur is not None:
        ta.on("blur", on_blur)
    wrap = Element("div", ta, cls=_c("pg-input-wrap pg-textarea-wrap", "pg-invalid" if error else None))
    return _field(wrap, label, hint, error, key, cls, style, required)


def _toggle(kind, label, value, on_change, disabled, description, key, cls, style, kw, error=None):
    value, error, on_change, on_blur, _ = _unfield(value, error, on_change)
    if on_blur is not None:
        user_change = on_change

        def on_change(v, _u=user_change):
            on_blur()
            _u(v)
    current, handle = _bind(value, on_change)
    inp = Element("input", type="checkbox", checked=bool(current), disabled=disabled, **kw)
    if handle is not None:
        inp.on("change", handle, transform=lambda ev: bool(ev.checked))
    if kind == "switch":
        visual = Element("span", Element("span", cls="pg-switch-thumb"), cls="pg-switch-track")
    else:
        visual = Element("span", _icon("check", 13, stroke=3), cls="pg-check-box")
    caption = None
    if label is not None or description is not None or error:
        caption = Element("span", Element("span", label, cls="pg-toggle-label") if label is not None else None,
                          Element("span", error, cls="pg-error-text") if error else
                          (Element("span", description, cls="pg-hint") if description else None),
                          cls="pg-toggle-text")
    return Element("label", inp, visual, caption,
                   cls=_c(f"pg-{kind}", "pg-disabled" if disabled else None, cls), style=style, key=key)


def checkbox(label=None, value=False, *, on_change=None, disabled=False, description=None, error=None, key=None,
             cls=None, style=None, **kw):
    """Checkbox. ``value`` may be a ``State`` (bool) or a ``Field`` for two-way binding."""
    return _toggle("check", label, value, on_change, disabled, description, key, cls, style, kw, error)


def switch(label=None, value=False, *, on_change=None, disabled=False, description=None, error=None, key=None,
           cls=None, style=None, **kw):
    """iOS-style toggle switch."""
    return _toggle("switch", label, value, on_change, disabled, description, key, cls, style, kw, error)


def slider(value=0, *, min=0, max=100, step=1, label=None, show_value=True, on_change=None, format=None,
           debounce=None, disabled=False, key=None, cls=None, style=None, **kw):
    """Range slider (two-way binds a ``State``)."""
    current, handle = _bind(value, on_change)
    current = min if current is None else current
    is_int = all(isinstance(x, int) for x in (min, max, step))

    def parse(ev):
        f = float(ev.value)
        return int(round(f)) if is_int else f

    pct = 0 if max == min else (current - min) / (max - min) * 100
    inp = Element("input", type="range", min=min, max=max, step=step, value=current, disabled=disabled,
                  cls="pg-slider", style={"--pct": f"{pct:.2f}%"}, **kw)
    if handle is not None:
        inp.on("input", handle, transform=parse, debounce=debounce)
    shown = format(current) if format else current
    head = None
    if label is not None or show_value:
        head = row(Element("span", label, cls="pg-label") if label is not None else None, spacer(),
                   Element("span", str(shown), cls="pg-slider-value") if show_value else None)
    return Element("div", head, inp, cls=_c("pg-field", cls), style=style, key=key)


def select(options, value=None, *, label=None, placeholder=None, on_change=None, hint=None, error=None,
           disabled=False, key=None, cls=None, style=None, **kw):
    """Dropdown. ``options``: list, list of (value, label) tuples, or {value: label} dict."""
    opts = _options(options)
    value, error, on_change, on_blur, required = _unfield(value, error, on_change)
    current, handle = _bind(value, on_change)
    if on_blur is not None:  # a choice counts as visiting the field
        on_change_bound = handle

        def handle(v, _h=on_change_bound):
            on_blur()
            _h(v)
    lookup = {str(v): v for v, _ in opts}
    children = []
    if placeholder is not None:
        children.append(Element("option", placeholder, value="", disabled=True))
    children += [Element("option", str(lbl), value=str(v)) for v, lbl in opts]
    sel = Element("select", *children, cls="pg-input pg-select", disabled=disabled,
                  value="" if current is None else str(current), **kw)
    if handle is not None:
        sel.on("change", handle, transform=lambda ev: lookup.get(ev.value, ev.value))
    if on_blur is not None:
        sel.on("blur", on_blur)
    wrap = Element("div", sel, _icon("chevron-down", 16, cls="pg-select-chevron"),
                   cls=_c("pg-input-wrap pg-select-wrap", "pg-invalid" if error else None))
    return _field(wrap, label, hint, error, key, cls, style, required)


def radio_group(options, value=None, *, label=None, on_change=None, inline=False, disabled=False,
                key=None, cls=None, style=None):
    """Radio buttons for picking one option."""
    opts = _options(options)
    current, handle = _bind(value, on_change)
    name = f"pg-radio-{abs(hash(tuple(str(v) for v, _ in opts))) % 10 ** 8}"
    items = []
    for v, lbl in opts:
        inp = Element("input", type="radio", name=name, value=str(v), checked=current == v, disabled=disabled)
        if handle is not None:
            inp.on("change", (lambda val: lambda: handle(val))(v))
        items.append(Element("label", inp, Element("span", cls="pg-radio-dot"),
                             Element("span", str(lbl), cls="pg-toggle-label"), cls="pg-radio"))
    group = row(*items, gap=4, wrap=True) if inline else column(*items, gap=2.5)
    return Element("div", Element("span", label, cls="pg-label") if label else None, group,
                   cls=_c("pg-field", cls), style=style, key=key, role="radiogroup")


def segmented(options, value=None, *, on_change=None, size="md", full=False, key=None, cls=None, style=None):
    """Segmented control: a compact group of mutually exclusive buttons."""
    opts = _options(options)
    current, handle = _bind(value, on_change)
    buttons = [Element("button", str(lbl), type="button",
                       cls=_c("pg-seg-item", "active" if current == v else None),
                       on_click=(lambda val: lambda: handle(val))(v) if handle else None)
               for v, lbl in opts]
    return Element("div", *buttons, cls=_c("pg-seg", f"pg-seg-{size}", "pg-seg-full" if full else None, cls),
                   style=style, key=key)


def form(*children, on_submit=None, gap=4, cls=None, style=None, **kw):
    """Form. ``on_submit(data)`` receives a dict of named fields (``ui.input(name="email")``).

    The browser's own validation popups are turned off (``novalidate``) so that errors from
    :mod:`zepygui.rules` are the only ones shown, in the app's style.
    """
    kw.setdefault("novalidate", True)
    f = Element("form", *children, cls=_c("pg-form", cls), style=_merge({"gap": _sp(gap)}, style), **kw)
    if on_submit is not None:
        f.on("submit", on_submit, prevent=True, transform=lambda ev: ev.form or {})
    return f


# =============================================================================
# Display
# =============================================================================
def badge(content, color="accent", dot=False, cls=None, **kw):
    """Small pill label. ``color``: accent, gray, green, red, yellow, blue."""
    return Element("span", Element("span", cls="pg-badge-dot") if dot else None, content,
                   cls=_c("pg-badge", f"pg-badge-{color}", cls), **kw)


_AVATAR_COLORS = ["#6366f1", "#ec4899", "#f59e0b", "#10b981", "#06b6d4", "#8b5cf6", "#ef4444", "#3b82f6"]


def avatar(name=None, src=None, size=36, cls=None, **kw):
    """Round avatar from an image or the initials of ``name``."""
    st = {"width": _px(size), "height": _px(size), "font-size": f"{size * 0.38:.0f}px"}
    if src:
        return Element("img", src=src, alt=name or "", cls=_c("pg-avatar", cls), style=st, **kw)
    parts = (name or "?").split()
    initials = "".join(p[0] for p in parts[:2]).upper()
    st["background"] = _AVATAR_COLORS[sum(map(ord, name or "")) % len(_AVATAR_COLORS)]
    return Element("span", initials, cls=_c("pg-avatar", cls), style=st, title=name, **kw)


def progress(value, max=100, *, label=None, show_value=False, color=None, size="md", cls=None, **kw):
    """Progress bar."""
    v = _val(value) or 0
    pct = _clamp(v / max * 100) if max else 0
    head = None
    if label is not None or show_value:
        head = row(Element("span", label, cls="pg-label") if label is not None else None, spacer(),
                   Element("span", f"{pct:.0f}%", cls="pg-slider-value") if show_value else None)
    fill = Element("div", cls="pg-progress-fill", style={"width": f"{pct:.2f}%", "background": color})
    return Element("div", head, Element("div", fill, cls=_c("pg-progress", f"pg-progress-{size}")),
                   cls=_c("pg-field", cls), role="progressbar", aria_valuenow=v, **kw)


def _clamp(v, lo=0, hi=100):
    return lo if v < lo else hi if v > hi else v


def spinner(size="md", cls=None, **kw):
    return Element("span", cls=_c("pg-spinner", f"pg-spinner-{size}", cls), role="status", **kw)


_ALERT_ICONS = {"info": "info", "success": "check-circle", "warning": "alert", "error": "alert-circle"}


def alert(content=None, *, kind="info", title=None, icon=None, on_close=None, cls=None, **kw):
    """Callout box. ``kind``: info, success, warning, error."""
    body = Element("div", Element("div", title, cls="pg-alert-title") if title else None,
                   Element("div", content, cls="pg-alert-text") if content is not None else None,
                   cls="pg-alert-body")
    close = Element("button", _icon("x", 15), type="button", cls="pg-alert-close", on_click=on_close) \
        if on_close else None
    return Element("div", _icon(icon or _ALERT_ICONS.get(kind, "info"), 18, cls="pg-alert-icon"), body, close,
                   cls=_c("pg-alert", f"pg-alert-{kind}", cls), role="alert", **kw)


def stat(label, value, *, delta=None, icon=None, hint=None, spark=None, cls=None, **kw):
    """KPI tile. ``delta`` like "+12%" is colored green/red automatically."""
    delta_el = None
    if delta is not None:
        d = str(delta)
        up = not d.startswith("-")
        delta_el = Element("span", _icon("trending-up" if up else "trending-down", 14), d,
                           cls=_c("pg-stat-delta", "up" if up else "down"))
    return Element("div",
                   row(Element("span", label, cls="pg-stat-label"), spacer(),
                       Element("span", _icon(icon, 18), cls="pg-stat-icon") if icon else None),
                   row(Element("span", str(_val(value)), cls="pg-stat-value"), delta_el, align="baseline", gap=2.5),
                   Element("span", hint, cls="pg-hint") if hint else None,
                   sparkline(spark, height=34) if spark else None,
                   cls=_c("pg-card pg-stat", cls), **kw)


def image(src, *, alt="", width=None, height=None, rounded=True, fit="cover", cls=None, style=None, **kw):
    st = {"width": _px(width), "height": _px(height), "object-fit": fit}
    return Element("img", src=src, alt=alt, cls=_c("pg-image", "pg-rounded" if rounded else None, cls),
                   style=_merge(st, style), **kw)


def tooltip(child, content, cls=None):
    """Wrap ``child`` so ``content`` shows on hover."""
    return Element("span", child, cls=_c("pg-tip-wrap", cls), data_tip=content)


def empty_state(title, description=None, *, icon="box", action=None, cls=None, **kw):
    return Element("div", Element("div", _icon(icon, 24), cls="pg-empty-icon"),
                   Element("div", title, cls="pg-empty-title"),
                   Element("div", description, cls="pg-empty-text") if description else None,
                   action, cls=_c("pg-empty", cls), **kw)


# -- table --------------------------------------------------------------------
def _columns(columns, rows):
    if columns is None:
        first = rows[0] if rows else {}
        if isinstance(first, dict):
            columns = list(first.keys())
        else:
            columns = [(i, f"Column {i + 1}") for i in range(len(first))]
    out = []
    for c in columns:
        if isinstance(c, dict):
            out.append({"label": str(c.get("key", "")).replace("_", " ").title(), **c})
        elif isinstance(c, (list, tuple)):
            out.append({"key": c[0], "label": c[1]})
        else:
            out.append({"key": c, "label": str(c).replace("_", " ").title()})
    return out


def _cell(row_data, key):
    try:
        return row_data[key]
    except (KeyError, IndexError, TypeError):
        return None


@component
def _Table(rows, columns, sortable, on_row_click, striped, empty, max_height, compact, cls, style,
           virtual=False, row_height=36):
    sort = use_state(None)
    scroll = use_state(0) if virtual else None
    rows = list(_val(rows) or [])
    cols = _columns(columns, rows)
    if sort.value is not None:
        key_name, asc = sort.value

        def sort_key(r):
            v = _cell(r, key_name)
            if isinstance(v, Element) or v is None:
                return (1, "")
            return (0, v) if isinstance(v, (int, float)) else (0, str(v).lower())

        try:
            rows.sort(key=sort_key, reverse=not asc)
        except TypeError:
            pass

    def toggle(key_name):
        cur = sort.value
        sort.set((key_name, True) if not cur or cur[0] != key_name else
                 ((key_name, False) if cur[1] else None))

    head = []
    for c in cols:
        can_sort = sortable and c.get("sortable", True)
        arrow = None
        if can_sort and sort.value and sort.value[0] == c["key"]:
            arrow = _icon("arrow-up" if sort.value[1] else "arrow-down", 13)
        head.append(Element("th", Element("span", c["label"], arrow, cls="pg-th-inner"),
                            cls=_c("pg-sortable" if can_sort else None, f"pg-align-{c['align']}" if c.get("align") else None),
                            style={"width": _px(c.get("width"))},
                            on_click=(lambda k: lambda: toggle(k))(c["key"]) if can_sort else None))
    # resolve per column once, not per cell: inspect.signature is slow
    plan = []
    for c in cols:
        fmt = c.get("format")
        wants_row = fmt is not None and _arity_of(fmt) >= 2
        plan.append((c["key"], fmt, wants_row, f"pg-align-{c['align']}" if c.get("align") else None))
    body = []
    first, last = 0, len(rows)
    if virtual:
        first, last = _window(scroll.value, len(rows), row_height, max_height)
        if first:
            body.append(Element("tr", cls="pg-vspacer", style={"height": first * row_height}, key="__top"))
    for i in range(first, last):
        r = rows[i]
        cells = []
        for key_name, fmt, wants_row, align in plan:
            v = _cell(r, key_name)
            if fmt is not None:
                v = fmt(v, r) if wants_row else fmt(v)
            cells.append(Element("td", "" if v is None else v, cls=align))
        click = (lambda rr: lambda: _call_user(on_row_click, rr))(r) if on_row_click else None
        row_key = r.get("id") if isinstance(r, dict) else None
        body.append(Element("tr", *cells, on_click=click, key=row_key))
    if virtual and last < len(rows):
        body.append(Element("tr", cls="pg-vspacer", style={"height": (len(rows) - last) * row_height}, key="__end"))
    if not rows:
        body.append(Element("tr", Element("td", Element("div", empty, cls="pg-table-empty"), colspan=len(cols) or 1)))
    tbl = Element("table", Element("thead", Element("tr", *head)), Element("tbody", *body),
                  cls=_c("pg-table", "pg-striped" if striped else None, "pg-clickable" if on_row_click else None,
                         "pg-compact" if compact else None, "pg-virtual" if virtual else None),
                  style={"--pg-row-h": f"{row_height}px"} if virtual else None)
    wrap = Element("div", tbl, cls=_c("pg-table-wrap", cls),
                   style=_merge({"max-height": _px(max_height)}, style))
    if virtual:
        wrap.on("scroll", scroll.set, throttle=40, transform=lambda ev: ev["scrollTop"] or 0)
    return wrap


def _arity_of(fn):
    try:
        return len(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return 1


def _call_user(fn, *args):
    from .state import invoke
    return invoke(fn, *args)


def table(rows, columns=None, *, sortable=True, on_row_click=None, striped=False, empty="No data",
          max_height=None, compact=False, virtual=None, row_height=36, key=None, cls=None, style=None):
    """Data table from a list of dicts (or lists).

    ``columns`` may be keys, ``(key, label)`` tuples or dicts with
    ``key``, ``label``, ``align``, ``width``, ``format`` (fn(value) or fn(value, row)), ``sortable``.
    Cells may contain elements (badges, buttons...). Click headers to sort.

    ``virtual=True`` renders only the rows in view (plus a margin), so tables of 100,000 rows
    stay fast; rows then have a fixed ``row_height`` and cells don't wrap. By default it
    switches on by itself above 1,000 rows. The table scrolls inside ``max_height``
    (480px when virtual and not given).
    """
    n = len(_val(rows) or [])
    if virtual is None:
        virtual = n > _VIRTUAL_THRESHOLD
    if virtual and max_height is None:
        max_height = 480
    return _Table(rows, columns, sortable, on_row_click, striped, empty, max_height, compact, cls, style,
                  virtual, row_height, key=key)


_VIRTUAL_THRESHOLD = 1000
_OVERSCAN_SCREENS = 1  # rows rendered above and below the viewport, in viewport heights


def _window(scroll_top, count, item_height, viewport):
    """The [first, last) slice of a fixed-height list to render for a scroll offset."""
    viewport = viewport if isinstance(viewport, (int, float)) else 480
    per_screen = max(1, int(math.ceil(viewport / item_height)))
    first_visible = int(max(0, scroll_top) // item_height)
    first = max(0, first_visible - per_screen * _OVERSCAN_SCREENS)
    last = min(count, first_visible + per_screen * (1 + _OVERSCAN_SCREENS))
    return min(first, count), last


@component
def _VirtualList(items, render, item_height, height, empty, cls, style):
    scroll = use_state(0)
    items = _val(items) or []
    n = len(items)
    if not n:
        return Element("div", empty, cls=_c("pg-vlist pg-vlist-empty", cls),
                       style=_merge({"height": _px(height)}, style)) if empty is not None else None
    first, last = _window(scroll.value, n, item_height, height)
    from .state import _arity
    with_index = _arity(render, 2) >= 2
    rows = []
    for i in range(first, last):
        item = items[i]
        content = render(item, i) if with_index else render(item)
        k = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
        rows.append(Element("div", content, cls="pg-vlist-item", key=i if k is None else k))
    win = Element("div", *rows, cls="pg-vlist-window", style={"transform": f"translateY({first * item_height}px)"})
    outer = Element("div", Element("div", win, cls="pg-vlist-inner", style={"height": n * item_height}),
                    cls=_c("pg-vlist", cls), style=_merge({"height": _px(height), "--pg-item-h": f"{item_height}px"},
                                                          style))
    outer.on("scroll", scroll.set, throttle=40, transform=lambda ev: ev["scrollTop"] or 0)
    return outer


def virtual_list(items, render, *, item_height=40, height=480, empty=None, key=None, cls=None, style=None):
    """A scrolling list that only renders the items in view: fine with 100,000 items.

    ``render(item)`` or ``render(item, index)`` returns the content of one item. Every item
    is ``item_height`` pixels tall. Items that are dicts with an ``"id"`` (or objects with
    ``.id``) keep their DOM node while scrolling.

        ui.virtual_list(files, lambda f: ui.row(ui.icon("file"), ui.text(f["name"])), item_height=36)
    """
    return _VirtualList(items, render, item_height, height, empty, cls, style, key=key)


def log_view(log, *, height=360, follow=True, filter=None, numbers=False, key=None, cls=None, style=None):
    """A console for a :class:`zepygui.Log`: streams new lines, draws only visible ones.

    ``follow``  stick to the newest line while the view is scrolled to the bottom
    ``filter``  a string or ``State``: show only lines containing it (case-insensitive)
    ``numbers`` show line numbers
    Lines containing ERROR / WARN / DEBUG are tinted.
    """
    s = current_session()
    if s is not None:
        log._attach(s)
    props = {"data_pg_log": log.id, "data_filter": _val(filter) or None,
             "data_follow": None if follow else "false"}
    # a key keeps the client's node (and its line buffer view) when siblings come and go
    return Element("div", cls=_c("pg-log", "pg-log-numbers" if numbers else None, cls),
                   style=_merge({"height": _px(height)}, style), key=f"pg-log:{log.id}" if key is None else key,
                   **props)


# -- tabs ---------------------------------------------------------------------
def _tab_items(tabs_def):
    items = tabs_def.items() if isinstance(tabs_def, dict) else tabs_def
    out = []
    for item in items:
        item = tuple(item)
        out.append((item[0], item[1], item[2] if len(item) > 2 else None))
    return out


@component
def _Tabs(items, value, on_change, variant, cls, style):
    local = use_state(lambda: items[0][0] if items else None)
    state = value if isinstance(value, State) else local
    active = state.value if any(lbl == state.value for lbl, _, _ in items) else (items[0][0] if items else None)

    def pick(lbl):
        state.set(lbl)
        if on_change:
            _call_user(on_change, lbl)

    buttons = [Element("button", _icon(ic, 16) if ic else None, Element("span", lbl), type="button",
                       cls=_c("pg-tab", "active" if lbl == active else None),
                       on_click=(lambda l: lambda: pick(l))(lbl)) for lbl, _, ic in items]
    content = next((c for lbl, c, _ in items if lbl == active), None)
    if callable(content) and not isinstance(content, Element):
        content = content()
    return Element("div", Element("div", *buttons, cls="pg-tabs-list", role="tablist"),
                   Element("div", content, cls="pg-tabs-panel", key=f"tab-{active}"),
                   cls=_c("pg-tabs", f"pg-tabs-{variant}", cls), style=style)


def tabs(items, value=None, *, on_change=None, variant="line", key=None, cls=None, style=None):
    """Tabs. ``items``: {label: content} or [(label, content, icon)]. Content may be a function (lazy).

    ``variant``: "line" or "pills". Pass a ``State`` as ``value`` to control the active tab.
    """
    return _Tabs(_tab_items(items), value, on_change, variant, cls, style, key=key)


def accordion(items, *, open_first=False, cls=None, **kw):
    """Collapsible sections: {title: content} or [(title, content)]."""
    entries = items.items() if isinstance(items, dict) else items
    sections = []
    for i, (title, content) in enumerate(entries):
        sections.append(Element("details",
                                Element("summary", Element("span", title), _icon("chevron-down", 16, cls="pg-chev")),
                                Element("div", content, cls="pg-acc-body"),
                                cls="pg-acc-item", open=open_first and i == 0))
    return Element("div", *sections, cls=_c("pg-acc", cls), **kw)


def modal(open, *children, title=None, footer=None, width=480, on_close=None, closable=True, cls=None, **kw):
    """Dialog shown while ``open`` (a ``State``) is True. Closes on backdrop click / Escape."""
    is_open = _val(open)
    if not is_open:
        return _discard(children, footer)

    def close():
        if isinstance(open, State):
            open.set(False)
        if on_close:
            _call_user(on_close)

    head = None
    if title is not None or closable:
        head = Element("div", Element("div", title, cls="pg-modal-title"), spacer(),
                       Element("button", _icon("x", 18), type="button", cls="pg-modal-x", on_click=close)
                       if closable else None, cls="pg-modal-head")
    panel = Element("div", head, Element("div", *children, cls="pg-modal-body"),
                    Element("div", footer, cls="pg-modal-foot") if footer is not None else None,
                    cls=_c("pg-modal", cls), style={"--w": _px(width)}, role="dialog", aria_modal="true", **kw)
    backdrop = Element("div", panel, cls="pg-backdrop")
    if closable:
        backdrop.on("click", close, self_only=True)
        backdrop.attrs["data-pg-esc"] = True
    return backdrop


def theme_toggle(**kw):
    """Button switching between light and dark themes."""
    s = current_session()
    dark = s is not None and s.theme.value == "dark"
    return icon_button("sun" if dark else "moon", toggle_theme, tooltip="Toggle theme", **kw)


# =============================================================================
# Charts (pure SVG/CSS, theme aware)
# =============================================================================
_PALETTE = [f"var(--c{i})" for i in range(1, 7)]


def _series(data):
    data = _val(data)
    if isinstance(data, dict):
        return [(str(k), [_val(x) for x in v]) for k, v in data.items()]
    return [("", list(data))]


def _nice(hi):
    if hi <= 0:
        return 1
    exp = 10 ** math.floor(math.log10(hi))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if hi <= m * exp:
            return m * exp
    return 10 * exp


def _fmt(v, fmt=None):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if fmt:
        return fmt(v)
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.1f}"
    v = int(v)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}M".replace(".0M", "M")
    if abs(v) >= 10_000:
        return f"{v / 1000:.1f}k".replace(".0k", "k")
    return f"{v:,}"


def _legend(names):
    return row(*[Element("span", Element("span", cls="pg-legend-dot", style={"background": _PALETTE[i % 6]}), n,
                         cls="pg-legend-item") for i, n in enumerate(names)], gap=4, wrap=True, cls="pg-legend")


def line_chart(data, labels=None, *, height=240, area=True, dots=True, smooth=True, format=None,
               colors=None, cls=None, style=None):
    """Line chart. ``data``: list of numbers, or {series_name: [numbers]} for several lines."""
    series = _series(data)
    colors = colors or _PALETTE
    n = max((len(v) for _, v in series), default=0)
    values = [x for _, v in series for x in v if x is not None]
    if n == 0 or not values:
        return empty_state("No data", icon="chart")
    lo = min(0, min(values))
    hi = _nice(max(values))
    span_ = (hi - lo) or 1
    labels = list(labels) if labels is not None else [str(i + 1) for i in range(n)]
    W, H = 1000.0, 1000.0

    def pt(i, v):
        x = W * i / (n - 1) if n > 1 else W / 2
        return x, H - (v - lo) / span_ * H

    def path(points):
        if not smooth or len(points) < 3:
            return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in points)
        d = f"M{points[0][0]:.1f} {points[0][1]:.1f}"
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            cx = (x0 + x1) / 2
            d += f"C{cx:.1f} {y0:.1f} {cx:.1f} {y1:.1f} {x1:.1f} {y1:.1f}"
        return d

    shapes = [Element("line", x1=0, x2=W, y1=H * k / 4, y2=H * k / 4, cls="pg-chart-grid") for k in range(5)]
    dot_els = []
    for si, (name, vals) in enumerate(series):
        color = colors[si % len(colors)]
        pts = [pt(i, v) for i, v in enumerate(vals) if v is not None]
        if not pts:
            continue
        line_d = path(pts)
        if area and (si == 0 or len(series) == 1):
            shapes.append(Element("path", d=f"{line_d}L{pts[-1][0]:.1f} {H}L{pts[0][0]:.1f} {H}Z",
                                  cls="pg-chart-area", style={"fill": color}))
        shapes.append(Element("path", d=line_d, cls="pg-chart-line", style={"stroke": color}))
        if dots:
            for i, v in enumerate(vals):
                if v is None:
                    continue
                x, y = pt(i, v)
                tip = f"{name + ' · ' if name else ''}{labels[i] if i < len(labels) else i}: {_fmt(v, format)}"
                dot_els.append(Element("span", cls="pg-chart-dot", data_tip=tip,
                                       style={"left": f"{x / W * 100:.2f}%", "top": f"{y / H * 100:.2f}%",
                                              "border-color": color}))
    svg = Element("svg", *shapes, viewBox=f"0 0 {W:g} {H:g}", preserveAspectRatio="none", cls="pg-chart-svg")
    y_axis = Element("div", *[Element("span", _fmt(hi - span_ * k / 4, format)) for k in range(5)], cls="pg-chart-y")
    step = max(1, math.ceil(n / 8))
    x_axis = Element("div", *[Element("span", str(labels[i]) if i % step == 0 and i < len(labels) else "")
                              for i in range(n)], cls="pg-chart-x")
    chart = Element("div", y_axis, Element("div", svg, *dot_els, cls="pg-chart-plot"), Element("div"), x_axis,
                    cls="pg-chart", style={"height": _px(height)})
    names = [nme for nme, _ in series if nme]
    return Element("div", _legend(names) if len(names) > 1 else None, chart,
                   cls=_c("pg-chart-box", cls), style=style)


def bar_chart(data, *, height=240, format=None, color=None, multicolor=False, cls=None, style=None):
    """Bar chart from {label: value} or [(label, value)]."""
    items = list(_val(data).items()) if isinstance(_val(data), dict) else [tuple(x) for x in _val(data)]
    if not items:
        return empty_state("No data", icon="chart")
    hi = _nice(max((v for _, v in items), default=1))
    cols = []
    for i, (lbl, v) in enumerate(items):
        c = color or (_PALETTE[i % 6] if multicolor else _PALETTE[0])
        bar = Element("div", cls="pg-bar", data_tip=f"{lbl}: {_fmt(v, format)}",
                      style={"height": f"{max(0, v) / hi * 100:.2f}%", "background": c})
        cols.append(Element("div", Element("div", bar, cls="pg-bar-track"),
                            Element("span", str(lbl), cls="pg-bar-label"), cls="pg-bar-col"))
    return Element("div", *cols, cls=_c("pg-bars", cls), style=_merge({"height": _px(height)}, style))


def donut(data, *, size=170, thickness=5, center=None, center_label=None, format=None, legend=True,
          cls=None, style=None):
    """Donut chart from {label: value}. ``center`` text defaults to the total."""
    items = list(_val(data).items())
    total = sum(v for _, v in items) or 1
    rings = [Element("circle", cx=21, cy=21, r=15.915, fill="none", cls="pg-donut-bg", stroke_width=thickness)]
    offset = 25.0
    for i, (lbl, v) in enumerate(items):
        pct = v / total * 100
        seg = Element("circle", cx=21, cy=21, r=15.915, fill="none", stroke_width=thickness,
                      stroke_dasharray=f"{max(pct - 0.6, 0):.3f} {100 - pct + 0.6:.3f}",
                      stroke_dashoffset=f"{offset:.3f}", cls="pg-donut-seg", style={"stroke": _PALETTE[i % 6]})
        seg.add(Element("title", f"{lbl}: {_fmt(v, format)} ({pct:.0f}%)"))
        rings.append(seg)
        offset -= pct
    svg = Element("svg", *rings, viewBox="0 0 42 42", width=size, height=size, cls="pg-donut-svg")
    middle = Element("div", Element("div", center if center is not None else _fmt(sum(v for _, v in items), format),
                                    cls="pg-donut-value"),
                     Element("div", center_label, cls="pg-donut-label") if center_label else None,
                     cls="pg-donut-center")
    leg = None
    if legend:
        leg = column(*[row(Element("span", cls="pg-legend-dot", style={"background": _PALETTE[i % 6]}),
                           Element("span", str(lbl), cls="pg-legend-name"), spacer(),
                           Element("span", f"{v / total * 100:.0f}%", cls="pg-legend-val"), gap=2.5)
                       for i, (lbl, v) in enumerate(items)], gap=2, cls="pg-donut-legend")
    return Element("div", Element("div", svg, middle, cls="pg-donut", style={"width": _px(size), "height": _px(size)}),
                   leg, cls=_c("pg-donut-box", cls), style=style)


def sparkline(values, *, height=36, color=None, area=True, cls=None, style=None):
    """Tiny inline trend line."""
    vals = [v for v in _val(values) if v is not None]
    if len(vals) < 2:
        return Element("div", style={"height": _px(height)})
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    pts = [(i / (len(vals) - 1) * 100, 95 - (v - lo) / rng * 90) for i, v in enumerate(vals)]
    d = "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in pts)
    c = color or _PALETTE[0]
    shapes = []
    if area:
        shapes.append(Element("path", d=f"{d}L100 100L0 100Z", cls="pg-chart-area", style={"fill": c}))
    shapes.append(Element("path", d=d, cls="pg-chart-line", style={"stroke": c}))
    return Element("svg", *shapes, viewBox="0 0 100 100", preserveAspectRatio="none", cls=_c("pg-spark", cls),
                   style=_merge({"height": _px(height)}, style))


# =============================================================================
# Actions (call from event handlers)
# =============================================================================
def toast(message, kind="info", *, title=None, duration=3.0):
    """Pop-up notification. ``kind``: info, success, warning, error."""
    for s in _targets():
        s.send({"type": "toast", "message": str(message), "kind": kind, "title": title, "duration": duration})


def navigate(path):
    """Go to another page of the app."""
    for s in _targets():
        s.navigate(path)


def run_js(code):
    """Execute JavaScript in the window."""
    for s in _targets():
        s.send({"type": "js", "code": code})


def set_title(title):
    for s in _targets():
        s.send({"type": "title", "title": str(title)})


def set_theme(theme):
    """"light", "dark" or "auto"."""
    for s in _targets():
        s.set_theme(theme)


def toggle_theme():
    for s in _targets():
        s.set_theme("light" if s.theme.value == "dark" else "dark")


def copy(content, notify=True):
    """Copy text to the user's clipboard."""
    import json
    run_js(f"navigator.clipboard.writeText({json.dumps(str(content))})")
    if notify:
        toast("Copied to clipboard", "success", duration=1.5)


def background(fn, *args):
    """Run slow work without freezing the window: ``ui.background(download, url)``.

    Shorthand for :func:`task` without callbacks; returns the :class:`~zepygui.tasks.Task`."""
    return spawn(fn, *args)


from .tasks import run_command, start as task  # noqa: E402


# =============================================================================
# Desktop integration
# =============================================================================
from .desktop import choose_folder, notify, open_file, open_path, open_url, save_file  # noqa: E402

__all__ += ["open_file", "save_file", "choose_folder", "notify", "open_url", "open_path"]


# =============================================================================
# File browsing
# =============================================================================
from .browser import breadcrumbs, file_browser, file_dialog, file_icon  # noqa: E402
from .fs import file_url  # noqa: E402

__all__ += ["file_browser", "file_dialog", "file_icon", "breadcrumbs", "file_url"]

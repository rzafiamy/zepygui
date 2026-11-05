"""File browsing components: ``ui.file_browser``, ``ui.file_dialog``, ``ui.file_icon``.

    ui.file_browser(folder)                         # an Explorer/Finder-like pane, two-way bound
    ui.file_dialog(show, mode="open", on_done=f)    # an in-app picker that looks the same everywhere
    ui.file_icon("report.pdf", 32)                  # a coloured icon for any file type

The browser is built for large folders: listings come from :mod:`zepygui.fs` (cached,
revalidated with one ``stat``), rows use one delegated handler for the whole list, folders
above a few hundred entries render only the rows in view, and a folder that takes long to
list (a network share, a slow USB stick) is read in the background behind a spinner.
"""
from __future__ import annotations

import concurrent.futures as cf
import fnmatch
import html as _html
import os
import threading

from . import fs
from .state import State, current_session
from .ui import (Element, _c, _call_user, _icon, _merge, _px, _val, _window, button, component, icon_button,
                 input as _input, modal, spacer, toast, use_state)

__all__ = ["file_browser", "file_dialog", "file_icon", "breadcrumbs"]

# =============================================================================
# File icons
# =============================================================================
_FOLDER_BACK = ("M3 8a3 3 0 0 1 3-3h5.6a2 2 0 0 1 1.5.68L14.6 7.5H26a3 3 0 0 1 3 3V24a3 3 0 0 1-3 3H6"
                "a3 3 0 0 1-3-3z")
_FOLDER_FRONT = "M3 13a3 3 0 0 1 3-3h20a3 3 0 0 1 3 3v11a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3z"
_PAGE = "M9 2.5h10.6L27 9.9V27a2.5 2.5 0 0 1-2.5 2.5h-15.5A2.5 2.5 0 0 1 6.5 27V5A2.5 2.5 0 0 1 9 2.5z"
_FOLD = "M19.5 2.5V7.5a2.5 2.5 0 0 0 2.5 2.5h5"
_DRIVE = ("M4 17.5 7.4 8.4A3 3 0 0 1 10.2 6.5h11.6a3 3 0 0 1 2.8 1.9L28 17.5", "M4 17.5h24v6a3 3 0 0 1-3 3H7"
          "a3 3 0 0 1-3-3z")
_GLYPHS = {  # small marks drawn on a page, per kind (24x24 grid, scaled down)
    "image": ["m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21", "M9 7a2 2 0 1 0 0 4 2 2 0 1 0 0-4"],
    "video": ["m10 8 6 4-6 4z"],
    "audio": ["M9 18V5l12-2v13", "M6 15a3 3 0 1 0 0 6 3 3 0 1 0 0-6", "M18 13a3 3 0 1 0 0 6 3 3 0 1 0 0-6"],
    "code": ["m16 18 6-6-6-6", "m8 6-6 6 6 6"],
    "archive": ["M12 3v2", "M12 7v2", "M12 11v2", "M10 15h4v4h-4z"],
    "exe": ["M4 4h16v16H4z", "M4 9h16"],
    "text": ["M5 7h14", "M5 12h14", "M5 17h9"],
    "doc": ["M5 7h14", "M5 12h14", "M5 17h9"],
    "sheet": ["M4 4h16v16H4z", "M4 10h16", "M4 15h16", "M10 4v16"],
    "slides": ["M3 5h18v11H3z", "m8 21 4-5 4 5"],
    "pdf": ["M5 7h14", "M5 12h10"],
    "font": ["M5 7V4h14v3", "M12 4v16", "M9 20h6"],
    "data": ["M4 6c0-1.4 3.6-2.5 8-2.5s8 1.1 8 2.5-3.6 2.5-8 2.5S4 7.4 4 6", "M4 6v12c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5V6"],
    "link": ["M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71",
             "M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"],
}
_SPECIAL = {"Desktop": "monitor", "Documents": "file-text", "Downloads": "download", "Pictures": "image",
            "Music": "music", "Videos": "video", "Home": "home"}
_icon_cache = {}


def _paths(ds, **attrs):
    extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return "".join(f'<path d="{_html.escape(d)}"{extra}/>' for d in ds)


def _folder_markup(glyph, opened):
    from .ui import ICONS
    front = _FOLDER_FRONT if not opened else "M5.2 13.4A3 3 0 0 1 8 11.5h20.2a2 2 0 0 1 1.9 2.6l-3 10A3 3 0 0 1 24.2 27H6a3 3 0 0 1-3-3z"
    out = f'<path class="pg-fi-back" d="{_FOLDER_BACK}"/><path class="pg-fi-front" d="{front}"/>'
    if glyph and glyph in ICONS:
        out += (f'<g class="pg-fi-glyph" transform="translate(11 13.2) scale(.42)" fill="none" stroke-width="2.4" '
                f'stroke-linecap="round" stroke-linejoin="round">{_paths(ICONS[glyph])}</g>')
    return out


def _file_markup(kind, ext, small):
    out = f'<path class="pg-fi-page" d="{_PAGE}"/><path class="pg-fi-fold" d="{_FOLD}"/>'
    glyph = _GLYPHS.get(kind)
    label = ext[:4].upper()
    if small or not label:
        if glyph:
            out += (f'<g class="pg-fi-mark" transform="translate(10.2 12.4) scale(.55)" fill="none" stroke-width="2.6" '
                    f'stroke-linecap="round" stroke-linejoin="round">{_paths(glyph)}</g>')
        else:
            out += '<rect class="pg-fi-band" x="10.5" y="20" width="12" height="3" rx="1.5"/>'
        return out
    if glyph:
        out += (f'<g class="pg-fi-mark" transform="translate(11.6 8.6) scale(.45)" fill="none" stroke-width="2.6" '
                f'stroke-linecap="round" stroke-linejoin="round">{_paths(glyph)}</g>')
    width = 8 + 4.6 * len(label)
    out += (f'<rect class="pg-fi-band" x="{16.75 - width / 2:.1f}" y="19" width="{width:.1f}" height="8" rx="2"/>'
            f'<text class="pg-fi-text" x="16.75" y="25" text-anchor="middle">{_html.escape(label)}</text>')
    return out


def _drive_markup(kind):
    glyph = {"removable": "usb", "cdrom": "disc", "network": "globe"}.get(kind)
    out = f'<path class="pg-fi-drive-top" d="{_DRIVE[0]}"/><path class="pg-fi-drive" d="{_DRIVE[1]}"/>'
    out += '<circle class="pg-fi-led" cx="23.5" cy="22" r="1.4"/><rect class="pg-fi-slot" x="8" y="21" width="9" height="2" rx="1"/>'
    if glyph:
        from .ui import ICONS
        out += (f'<g class="pg-fi-glyph" transform="translate(11 6.6) scale(.42)" fill="none" stroke-width="2.4" '
                f'stroke-linecap="round" stroke-linejoin="round">{_paths(ICONS[glyph])}</g>')
    return out


def file_icon(item, size=20, *, is_dir=None, special=None, opened=False, drive=None, cls=None, **kw):
    """A coloured, two-tone icon for a file, a folder or a drive.

    ``item`` is a file name, a path or an :class:`~zepygui.fs.Entry`. Folders are drawn as
    folders (with a mark for Desktop, Documents, Downloads… when ``special`` names it),
    files as a page tinted by their kind with the extension on it from 28px up.
    ``drive="fixed" | "removable" | "cdrom" | "network"`` draws a drive.

        ui.file_icon("photo.jpg", 48)
        ui.file_icon(entry, 20)
        ui.file_icon("Documents", 64, is_dir=True, special="Documents")
    """
    if isinstance(item, fs.Entry):
        name, kind, ext = item.name, item.kind, item.ext
        is_dir = item.is_dir if is_dir is None else is_dir
    else:
        name = os.path.basename(str(item).rstrip("\\/")) or str(item)
        is_dir = bool(is_dir)
        kind = fs.kind_of(name, is_dir)
        dot = name.rfind(".")
        ext = name[dot + 1:].lower() if dot > 0 and not is_dir else ""
    small = size < 28
    if drive:
        ckey, kind = ("drive", drive), f"drive-{drive}"
    elif is_dir:
        glyph = _SPECIAL.get(special) if special else None
        ckey, kind = ("folder", glyph, opened), "folder"
    else:
        ckey = ("file", kind, ext if not small else "", small)
    markup = _icon_cache.get(ckey)
    if markup is None:
        if drive:
            markup = _drive_markup(drive)
        elif is_dir:
            markup = _folder_markup(ckey[1], opened)
        else:
            markup = _file_markup(kind, ext, small)
        _icon_cache[ckey] = markup
    svg = Element("svg", cls=_c("pg-fi", f"pg-fi-{kind}", cls), width=size, height=size, viewBox="0 0 32 32",
                  aria_hidden="true", **kw)
    svg.html = markup
    return svg


# =============================================================================
# Breadcrumbs
# =============================================================================
def breadcrumbs(items, *, on_click=None, max_items=6, cls=None, style=None, **kw):
    """A trail like ``Home › Projects › zepygui``.

    ``items`` is a list of labels or ``(label, value)`` pairs; ``on_click(value)`` runs when
    a crumb is clicked (the last one is the current place and is not clickable). Long trails
    keep the first crumb and the last ones, with an ellipsis in between."""
    pairs = [(i, i) if not isinstance(i, (list, tuple)) else (i[0], i[1]) for i in items]
    shown = list(enumerate(pairs))
    if max_items and len(pairs) > max_items:
        shown = shown[:1] + [(None, None)] + shown[-(max_items - 2):]
    out = []
    for n, (idx, pair) in enumerate(shown):
        if n:
            out.append(_icon("chevron-right", 14, cls="pg-crumb-sep"))
        if pair is None:
            hidden_value = pairs[shown[n + 1][0] - 1][1]
            out.append(Element("button", "…", type="button", cls="pg-crumb",
                               on_click=(lambda v: lambda: _call_user(on_click, v))(hidden_value) if on_click else None))
            continue
        label, value = pair
        last = idx == len(pairs) - 1
        out.append(Element("button", label, type="button", cls=_c("pg-crumb", "pg-crumb-current" if last else None),
                           on_click=(lambda v: lambda: _call_user(on_click, v))(value) if on_click and not last else None))
    return Element("nav", *out, cls=_c("pg-crumbs", cls), style=style, aria_label="Breadcrumb", **kw)


# =============================================================================
# File browser
# =============================================================================
_VIRTUAL_AT = 400        # rows above which only the visible ones are rendered
_MAX_TILES = 2000        # icon view: tiles beyond this are left out (with a note)
_ROW_H = 32
_SYNC_WAIT = 0.12        # seconds to wait for a listing before showing a spinner
_THUMB_MAX = 25 * 1024 * 1024
_THUMB_KINDS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "avif", "ico"}
_NAV_KEYS = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Backspace", "Delete", "F2", "F5",
             "Home", "End", "PageUp", "PageDown"] + [chr(c) for c in range(97, 123)] + \
            [str(d) for d in range(10)]
_pending = {}
_pending_lock = threading.Lock()


def _load(path, hidden, sort, reverse, wake):
    """``(entries, error, loading)`` for ``path``: at once when cached or quick, else later.

    A slow listing keeps running on the shared thread pool; ``wake()`` re-renders the
    window when it is ready (the result is then in the cache)."""
    if fs.is_cached(path, hidden):
        try:
            return fs.listdir(path, hidden=hidden, sort=sort, reverse=reverse), None, False
        except OSError as exc:
            return [], exc, False
    key = (path, hidden)
    with _pending_lock:
        fut = _pending.get(key)
        if fut is None:
            from .tasks import thread_pool
            fut = _pending[key] = thread_pool().submit(fs.listdir, path, hidden=hidden, sort=sort, reverse=reverse)
            fut.add_done_callback(lambda f, k=key: _pending.pop(k, None))
    try:
        fut.result(timeout=_SYNC_WAIT)
    except cf.TimeoutError:
        fut.add_done_callback(lambda f: wake())
        return [], None, True
    except OSError as exc:
        return [], exc, False
    try:
        return fs.listdir(path, hidden=hidden, sort=sort, reverse=reverse), None, False
    except OSError as exc:
        return [], exc, False


def _matches(entry, query, types, folders_only):
    if folders_only and not entry.is_dir:
        return False
    if types and not entry.is_dir and entry.ext not in types:
        return False
    if query:
        name = entry.name.casefold()
        if any(ch in query for ch in "*?["):
            return fnmatch.fnmatchcase(name, query)
        return query in name
    return True


def _error_text(exc):
    if isinstance(exc, PermissionError):
        return "You don't have permission to open this folder."
    if isinstance(exc, FileNotFoundError):
        return "This folder no longer exists."
    if isinstance(exc, NotADirectoryError):
        return "This is not a folder."
    return f"{type(exc).__name__}: {exc}"


def _computer_label():
    return fs.COMPUTER_LABEL


def _folder_title(path):
    if path == fs.COMPUTER:
        return _computer_label()
    trail = fs.crumbs(path)
    return trail[-1][0] if trail else path


def _usage_bar(total, free, cls=None):
    if not total:
        return None
    used = 1 - (free or 0) / total
    tone = "pg-fb-usage-full" if used > 0.9 else None
    return Element("div", Element("div", cls="pg-fb-usage-fill", style={"width": f"{used * 100:.1f}%"}),
                   cls=_c("pg-fb-usage", tone, cls))


def _drive_icon(kind):
    return {"removable": "usb", "cdrom": "disc", "network": "server"}.get(kind, "hard-drive")


@component
def _FileBrowser(path, on_open, on_select, on_navigate, select, types, folders_only, show_hidden, view, height,
                 sidebar, manage, places, thumbnails, cls, style):
    local = use_state(lambda: _val(path) if path is not None and not isinstance(path, State) else fs.home())
    where = path if isinstance(path, State) else local
    cwd = where.value
    if cwd is None:
        cwd = fs.home()
    hist = use_state(lambda: {"back": [], "fwd": []}).value
    sel = use_state(list)
    anchor = use_state(None)
    focus = use_state(None)
    mode = use_state(view)
    order = use_state(("name", False))
    query = use_state("")
    hidden = use_state(bool(show_hidden))
    editing = use_state(False)
    scroll = use_state(0)
    pane_w = use_state(0)
    reveal = use_state(None)
    jump = use_state(None)  # (scroll offset, n): scroll the virtual list there (keyboard moves)
    dialog = use_state(None)
    name_input = use_state("")
    tick = use_state(0)
    tick.value  # noqa: B018 -- subscribe: a finished background listing or a refresh re-renders
    seen = use_state(cwd)
    if seen.value != cwd:  # the bound folder was changed from outside
        seen.set(cwd)
        sel.set([])
        query.set("")
        scroll.set(0)
        focus.set(None)
    session = current_session()
    types_set = {t.lower().lstrip(".") for t in types} if types else None
    multiple = select == "multiple"

    def wake():
        tick.set(tick.value + 1)

    by, rev = order.value
    if cwd == fs.COMPUTER:
        entries, error, loading = [], None, False
    else:
        entries, error, loading = _load(cwd, hidden.value, by, rev, wake)
    q = query.value.strip().casefold()
    shown = [e for e in entries if _matches(e, q, types_set, folders_only)] if (q or types_set or folders_only) \
        else entries
    by_path = {e.path: e for e in shown}
    paths = [e.path for e in shown]
    index = {p: i for i, p in enumerate(paths)}
    selected = [p for p in sel.value if p in by_path] if cwd != fs.COMPUTER else []
    selected_set = set(selected)
    place_list = fs.places() if places is None else [dict(p) for p in places]
    special = {os.path.normcase(p["path"]): p["name"] for p in place_list}
    drives = fs.drives()

    # -- actions ------------------------------------------------------------------
    def emit_select(new):
        if on_select is None:
            return
        _call_user(on_select, list(new) if multiple else (new[0] if new else None))

    def set_selection(new, focus_on=None):
        sel.set(list(new))
        if focus_on is not None:
            focus.set(focus_on)
        emit_select(new)

    def go(to, record=True):
        if to is None:
            return
        if to != fs.COMPUTER and not os.path.isdir(to):
            toast(f"{to} is not a folder", "error")
            return
        if record and to != cwd:
            hist["back"].append(cwd)
            hist["fwd"].clear()
        seen.set(to)
        where.set(to)
        sel.set([])
        focus.set(None)
        query.set("")
        scroll.set(0)
        editing.set(False)
        emit_select([])
        if on_navigate is not None:
            _call_user(on_navigate, to)

    def back():
        if hist["back"]:
            hist["fwd"].append(cwd)
            go(hist["back"].pop(), record=False)

    def forward():
        if hist["fwd"]:
            hist["back"].append(cwd)
            go(hist["fwd"].pop(), record=False)

    def up():
        target = fs.parent(cwd) if cwd != fs.COMPUTER else None
        if target is not None:
            go(target)
            focus.set(cwd)

    def refresh():
        fs.invalidate(cwd)
        fs.drives(max_age=0)
        wake()

    def open_entry(p):
        if cwd == fs.COMPUTER or os.path.isdir(p):
            go(p)
        elif on_open is not None:
            _call_user(on_open, p)
        else:
            from .desktop import open_path
            open_path(p)

    def click(ev):
        item = ev.data.get("item")
        if cwd == fs.COMPUTER:
            return go(item) if item else None
        if item is None or item not in by_path:
            if selected:
                set_selection([])
            return
        if select is None:
            focus.set(item)
            return
        if multiple and ev.data.get("shift") and anchor.value in index:
            a, b = sorted((index[anchor.value], index[item]))
            return set_selection(paths[a:b + 1], item)
        if multiple and (ev.data.get("ctrl") or ev.data.get("meta")):
            new = [p for p in selected if p != item] if item in selected_set else selected + [item]
            anchor.set(item)
            return set_selection(new, item)
        anchor.set(item)
        set_selection([item], item)

    def dblclick(ev):
        item = ev.data.get("item")
        if item is not None and item in by_path:
            open_entry(item)

    def move(step, extend=False, absolute=None):
        if not paths:
            return
        cur = index.get(focus.value, -1 if step > 0 else len(paths))
        i = absolute if absolute is not None else cur + step
        i = max(0, min(len(paths) - 1, i))
        target = paths[i]
        if extend and multiple and anchor.value in index:
            a, b = sorted((index[anchor.value], i))
            set_selection(paths[a:b + 1], target)
        else:
            anchor.set(target)
            set_selection([target], target) if select else focus.set(target)
        reveal.set(target)
        if virtual:
            top, view_h = scroll.value, list_height
            to = None
            if i * _ROW_H < top:
                to = i * _ROW_H
            elif (i + 1) * _ROW_H > top + view_h:
                to = (i + 1) * _ROW_H - view_h
            if to is not None:
                scroll.set(to)
                jump.set((to, (jump.value or (0, 0))[1] + 1))

    def key(ev):
        k = ev.key
        ctrl = ev.data.get("ctrl") or ev.data.get("meta")
        shift = ev.data.get("shift")
        alt = ev.data.get("alt")
        cols = max(1, (pane_w.value or 720) // 112) if mode.value == "icons" else 1
        page = max(1, list_height // _ROW_H - 1)
        if k == "ArrowDown":
            move(cols, shift)
        elif k == "ArrowUp" and alt:
            up()
        elif k == "ArrowUp":
            move(-cols, shift)
        elif k == "ArrowLeft" and alt:
            back()
        elif k == "ArrowRight" and alt:
            forward()
        elif k == "ArrowRight" and cols > 1:
            move(1, shift)
        elif k == "ArrowLeft" and cols > 1:
            move(-1, shift)
        elif k == "PageDown":
            move(page, shift)
        elif k == "PageUp":
            move(-page, shift)
        elif k == "Home":
            move(0, shift, absolute=0)
        elif k == "End":
            move(0, shift, absolute=len(paths) - 1)
        elif k == "Enter":
            target = focus.value if focus.value in by_path else (selected[0] if selected else None)
            if target:
                open_entry(target)
        elif k == "Backspace":
            up()
        elif k == "F5":
            refresh()
        elif k == "Escape":
            set_selection([])
        elif k == "Delete" and manage and selected:
            dialog.set(("delete", list(selected)))
        elif k == "F2" and manage and len(selected) == 1:
            start_rename(selected[0])
        elif k == "a" and ctrl and multiple:
            set_selection(paths)
        elif len(k) == 1 and not ctrl:
            # type-ahead: jump to the next entry starting with that letter
            start = index.get(focus.value, -1) + 1
            for i in list(range(start, len(paths))) + list(range(0, start)):
                if by_path[paths[i]].name.casefold().startswith(k):
                    move(0, absolute=i)
                    break

    def start_rename(p):
        name_input.set(os.path.basename(p))
        dialog.set(("rename", p))

    def new_folder():
        name_input.set("New folder")
        dialog.set(("mkdir", cwd))

    def confirm_dialog():
        d = dialog.value
        if not d:
            return
        try:
            if d[0] == "mkdir":
                problem = fs.check_name(name_input.value)
                if problem:
                    return toast(problem, "warning")
                made = fs.make_folder(cwd, name_input.value.strip())
                set_selection([made], made)
                reveal.set(made)
            elif d[0] == "rename":
                new = fs.rename(d[1], name_input.value)
                set_selection([new], new)
                reveal.set(new)
            elif d[0] == "delete":
                fs.trash(*d[1])
                n = len(d[1])
                toast(f"Moved {n} item{'s' if n != 1 else ''} to the {'Recycle Bin' if fs.WINDOWS else 'Trash'}",
                      "success")
                set_selection([])
        except (OSError, ValueError) as exc:
            toast(str(exc), "error", title="Could not complete the operation")
            return
        dialog.set(None)
        wake()

    def copy_path():
        from .ui import copy
        copy("\n".join(selected) if selected else cwd)

    def set_sort(col):
        cur_by, cur_rev = order.value
        order.set((col, not cur_rev) if cur_by == col else (col, col in ("size", "modified")))
        scroll.set(0)

    def on_scroll(ev):
        scroll.set(ev.data.get("scrollTop") or 0)
        if ev.data.get("width"):
            pane_w.set(ev.data["width"])

    # -- toolbar ------------------------------------------------------------------
    can_back, can_fwd = bool(hist["back"]), bool(hist["fwd"])
    nav = Element("div",
                  icon_button("arrow-left", back, disabled=not can_back, tooltip="Back (Alt+←)", size="sm"),
                  icon_button("arrow-right", forward, disabled=not can_fwd, tooltip="Forward (Alt+→)", size="sm"),
                  icon_button("corner-left-up", up, disabled=cwd == fs.COMPUTER, tooltip="Up (Backspace)", size="sm"),
                  icon_button("refresh", refresh, tooltip="Refresh (F5)", size="sm"),
                  cls="pg-fb-navbtns")
    if editing.value:
        def go_typed(text):
            text = os.path.expandvars(os.path.expanduser((text or "").strip().strip('"')))
            if not text:
                return editing.set(False)
            if os.path.isfile(text):
                go(os.path.dirname(text))
                return set_selection([text], text)
            go(text)

        box = Element("input", cls="pg-fb-path-input", value=cwd if cwd != fs.COMPUTER else "", autofocus=True,
                      spellcheck="false", key="pathedit")
        box.on("enter", go_typed, transform=lambda ev: ev.value)
        box.on("escape", lambda: editing.set(False))
        box.on("blur", lambda: editing.set(False))
        address = Element("div", _icon("folder", 16, cls="pg-fb-addr-icon"), box, cls="pg-fb-address pg-fb-editing")
    else:
        trail = [(_computer_label(), fs.COMPUTER)] + ([] if cwd == fs.COMPUTER else fs.crumbs(cwd))
        address = Element("div",
                          Element("button", _icon("monitor", 16), type="button", cls="pg-fb-addr-icon",
                                  on_click=lambda: go(fs.COMPUTER)).tooltip(_computer_label()),
                          breadcrumbs(trail[1:] if cwd != fs.COMPUTER else trail, on_click=go, max_items=5),
                          Element("div", cls="pg-fb-addr-fill", on_click=lambda: editing.set(True)),
                          cls="pg-fb-address", title="Click to type a path")
    search = _input(query, placeholder=f"Search {_folder_title(cwd)}", icon="search", clearable=True, debounce=150,
                    cls="pg-fb-search", key="pg-fb-search")
    top = Element("div", nav, address, search, cls="pg-fb-toolbar")

    sel_one = len(selected) == 1
    commands = []
    if manage and cwd != fs.COMPUTER:
        commands += [button("New folder", new_folder, variant="ghost", size="sm", icon="folder-plus"),
                     Element("span", cls="pg-fb-sep"),
                     icon_button("edit", lambda: start_rename(selected[0]), size="sm", disabled=not sel_one,
                                 tooltip="Rename (F2)"),
                     icon_button("trash", lambda: dialog.set(("delete", list(selected))), size="sm",
                                 disabled=not selected, tooltip="Move to " + ("Recycle Bin" if fs.WINDOWS else "Trash")),
                     icon_button("copy", copy_path, size="sm", tooltip="Copy path")]
    elif cwd != fs.COMPUTER:
        commands.append(icon_button("copy", copy_path, size="sm", tooltip="Copy path"))
    sort_labels = {"name": "Name", "modified": "Date", "size": "Size", "kind": "Type"}
    commands += [
        spacer(),
        button(f"{sort_labels.get(by, 'Name')} {'↓' if rev else '↑'}", lambda: set_sort(by), variant="ghost",
               size="sm", icon="arrow-up-down").tooltip("Reverse the order"),
        icon_button("eye" if hidden.value else "eye-off", lambda: hidden.set(not hidden.value), size="sm",
                    tooltip="Hide hidden items" if hidden.value else "Show hidden items",
                    cls="pg-fb-on" if hidden.value else None),
        Element("div", *[Element("button", _icon(ic, 15), type="button", title=label, aria_label=label,
                                 cls=_c("pg-seg-item", "active" if mode.value == v else None),
                                 on_click=(lambda v: lambda: mode.set(v))(v))
                         for v, ic, label in (("details", "list", "Details"), ("icons", "grid", "Large icons"))],
                cls="pg-seg pg-seg-sm pg-fb-views"),
    ]
    command_bar = Element("div", *commands, cls="pg-fb-commands")

    # -- side bar -----------------------------------------------------------------
    side = None
    if sidebar:
        norm_cwd = os.path.normcase(cwd) if cwd else cwd
        items = [Element("div", "Quick access", cls="pg-fb-side-title")]
        for p in place_list:
            items.append(Element("button", file_icon(p["name"], 18, is_dir=True, special=p["name"]),
                                 Element("span", p["name"], cls="pg-truncate"), type="button",
                                 cls=_c("pg-fb-place", "active" if os.path.normcase(p["path"]) == norm_cwd else None),
                                 on_click=(lambda t: lambda: go(t))(p["path"]), title=p["path"]))
        items.append(Element("div", _computer_label(), cls="pg-fb-side-title"))
        for d in drives:
            items.append(Element("button", file_icon(d["name"], 18, drive=d["kind"]),
                                 Element("span", Element("span", d["name"], cls="pg-truncate"),
                                         _usage_bar(d["total"], d["free"]), cls="pg-fb-place-text"),
                                 type="button",
                                 cls=_c("pg-fb-place", "active" if os.path.normcase(d["path"]) == norm_cwd else None),
                                 on_click=(lambda t: lambda: go(t))(d["path"]), title=d["path"]))
        side = Element("div", *items, cls="pg-fb-side")

    # -- content ------------------------------------------------------------------
    list_height = max(160, (height if isinstance(height, (int, float)) else 520) - 150)
    virtual = mode.value == "details" and len(shown) > _VIRTUAL_AT
    focus_path = focus.value
    reveal_path = reveal.value
    details_head = None

    def row_cls(p):
        return _c("pg-fb-item", "selected" if p in selected_set else None, "focused" if p == focus_path else None)

    if cwd == fs.COMPUTER:
        body = _computer_view(drives, place_list)
    elif error is not None:
        body = Element("div", Element("div", _icon("lock" if isinstance(error, PermissionError) else "alert", 26),
                                      cls="pg-empty-icon"),
                       Element("div", "Can't open this folder", cls="pg-empty-title"),
                       Element("div", _error_text(error), cls="pg-empty-text"),
                       button("Go up", up, variant="outline", size="sm", icon="corner-left-up"), cls="pg-empty")
    elif loading:
        body = Element("div", *[Element("div", Element("span", cls="pg-fb-skel-icon"),
                                        Element("span", cls="pg-fb-skel-line", style={"width": f"{30 + (i * 37) % 45}%"}),
                                        cls="pg-fb-skel") for i in range(8)],
                       cls="pg-fb-loading", aria_busy="true")
    elif not shown:
        body = Element("div", Element("div", _icon("search" if q else "folder-open", 26), cls="pg-empty-icon"),
                       Element("div", f"No items match “{query.value}”" if q else "This folder is empty",
                               cls="pg-empty-title"),
                       Element("div", "Try another name, or * and ? as wildcards." if q else
                               ("Only " + ", ".join(sorted(types_set)) + " files are shown." if types_set else None),
                               cls="pg-empty-text"),
                       cls="pg-empty")
    elif mode.value == "icons":
        tiles = []
        for e in shown[:_MAX_TILES]:
            thumb = None
            if thumbnails and e.ext in _THUMB_KINDS and e.size < _THUMB_MAX:
                thumb = Element("img", src=fs.file_url(e.path), loading="lazy", decoding="async", alt="",
                                draggable="false", cls="pg-fb-thumb-img")
            tiles.append(Element("div",
                                 Element("div", thumb or file_icon(e, 56, special=special.get(os.path.normcase(e.path))),
                                         cls="pg-fb-thumb"),
                                 Element("div", e.name, cls="pg-fb-tile-name"),
                                 cls=_c("pg-fb-tile", row_cls(e.path)), key=e.path, data_pg_item=e.path,
                                 title=f"{e.name}\n{fs.type_label(e)}" + ("" if e.is_dir else f" · {fs.human_size(e.size)}"),
                                 data_pg_reveal="1" if e.path == reveal_path else None))
        more = None
        if len(shown) > _MAX_TILES:
            more = Element("div", f"{len(shown) - _MAX_TILES:,} more items: switch to Details to see them all.",
                           cls="pg-fb-more")
        body = Element("div", *tiles, more, cls="pg-fb-tiles")
    else:
        def head(col, label, align=None):
            arrow = _icon("arrow-down" if rev else "arrow-up", 12) if by == col else None
            return Element("button", Element("span", label), arrow, type="button",
                           cls=_c("pg-fb-th", f"pg-align-{align}" if align else None, "active" if by == col else None),
                           on_click=lambda: set_sort(col))

        details_head = Element("div", head("name", "Name"), head("modified", "Date modified"), head("kind", "Type"),
                               head("size", "Size", "right"), cls="pg-fb-head")
        first, last = 0, len(shown)
        if virtual:
            first, last = _window(scroll.value, len(shown), _ROW_H, list_height)
        rows = []
        for e in shown[first:last]:
            rows.append(Element(
                "div",
                Element("span", file_icon(e, 20, special=special.get(os.path.normcase(e.path))),
                        Element("span", e.name, cls="pg-truncate"),
                        _icon("link", 12, cls="pg-fb-linkmark") if e.link else None, cls="pg-fb-cell pg-fb-name"),
                Element("span", fs.human_time(e.modified), cls="pg-fb-cell pg-fb-dim"),
                Element("span", fs.type_label(e), cls="pg-fb-cell pg-fb-dim"),
                Element("span", "" if e.is_dir else fs.human_size(e.size), cls="pg-fb-cell pg-fb-dim pg-align-right"),
                cls=_c("pg-fb-row", row_cls(e.path), "pg-fb-hidden" if e.hidden else None), key=e.path,
                data_pg_item=e.path, data_pg_reveal="1" if (e.path == reveal_path and not virtual) else None))
        if virtual:
            inner = Element("div", Element("div", *rows, cls="pg-fb-rows",
                                           style={"transform": f"translateY({first * _ROW_H}px)"}),
                            cls="pg-fb-rows-inner", style={"height": len(shown) * _ROW_H})
        else:
            inner = Element("div", *rows, cls="pg-fb-rows")
        body = Element("div", inner, cls="pg-fb-details")

    pane = Element("div", body, cls=_c("pg-fb-pane", "pg-fb-pane-icons" if mode.value == "icons" else None),
                   tabindex="0", key=f"pane:{cwd}",
                   data_pg_scroll=f"{jump.value[0]}:{jump.value[1]}" if virtual and jump.value else None)
    pane.on("click", click)
    pane.on("dblclick", dblclick)
    pane.on("keydown", key, keys=_NAV_KEYS, prevent=True)
    if virtual or mode.value == "icons":
        pane.on("scroll", on_scroll, throttle=40)

    # -- status bar ---------------------------------------------------------------
    if cwd == fs.COMPUTER:
        status_left = f"{len(drives)} drive{'s' if len(drives) != 1 else ''}"
    else:
        status_left = f"{len(shown):,} item{'s' if len(shown) != 1 else ''}"
        if len(shown) != len(entries):
            status_left += f" (of {len(entries):,})"
        if selected:
            size = sum(by_path[p].size for p in selected if not by_path[p].is_dir)
            status_left += f"  ·  {len(selected):,} selected" + (f"  ·  {fs.human_size(size)}" if size else "")
    free_note = None
    if cwd != fs.COMPUTER:
        for d in sorted(drives, key=lambda d: -len(d["path"])):
            if os.path.normcase(cwd).startswith(os.path.normcase(d["path"])) and d["free"] is not None:
                free_note = f"{fs.human_size(d['free'])} free on {d['name']}"
                break
    status = Element("div", Element("span", status_left), spacer(),
                     Element("span", free_note, cls="pg-fb-dim") if free_note else None,
                     cls="pg-fb-status")

    # -- dialogs ------------------------------------------------------------------
    dlg = None
    d = dialog.value
    if d:
        close = lambda: dialog.set(None)  # noqa: E731
        if d[0] == "delete":
            n = len(d[1])
            what = f"“{os.path.basename(d[1][0])}”" if n == 1 else f"these {n} items"
            dlg = modal(True, Element("p", f"Move {what} to the {'Recycle Bin' if fs.WINDOWS else 'Trash'}?",
                                      cls="pg-text"),
                        title="Delete", width=420, on_close=close,
                        footer=[button("Cancel", close, variant="ghost"),
                                button("Move to " + ("Recycle Bin" if fs.WINDOWS else "Trash"), confirm_dialog,
                                       variant="danger", icon="trash")])
        else:
            problem = fs.check_name(name_input.value)
            dlg = modal(True, _input(name_input, label="Name", autofocus=True, on_enter=lambda _v: confirm_dialog(),
                                     error=problem if name_input.value else None, key="pg-fb-name"),
                        title="New folder" if d[0] == "mkdir" else "Rename", width=420, on_close=close,
                        footer=[button("Cancel", close, variant="ghost"),
                                button("Create" if d[0] == "mkdir" else "Rename", confirm_dialog,
                                       disabled=bool(problem))])

    main = Element("div", command_bar, details_head, pane, status, cls="pg-fb-main")
    return Element("div", top, Element("div", side, main, cls="pg-fb-body"), dlg,
                   cls=_c("pg-fb", cls), style=_merge({"height": _px(height)}, style))


def _computer_view(drives, place_list):
    tiles = []
    for p in place_list:
        if p["name"] == "Home":
            continue
        tiles.append(Element("div", file_icon(p["name"], 40, is_dir=True, special=p["name"]),
                             Element("div", Element("div", p["name"], cls="pg-fb-card-title"),
                                     Element("div", p["path"], cls="pg-fb-dim pg-truncate"), cls="pg-fb-card-text"),
                             cls="pg-fb-card pg-fb-item", key=p["path"], data_pg_item=p["path"]))
    cards = []
    for d in drives:
        detail = (f"{fs.human_size(d['free'])} free of {fs.human_size(d['total'])}" if d["total"] else
                  {"network": "Network location", "cdrom": "No disc"}.get(d["kind"], d["path"]))
        cards.append(Element("div", file_icon(d["name"], 44, drive=d["kind"]),
                             Element("div", Element("div", d["name"], cls="pg-fb-card-title"),
                                     _usage_bar(d["total"], d["free"]),
                                     Element("div", detail, cls="pg-fb-dim"), cls="pg-fb-card-text"),
                             cls="pg-fb-card pg-fb-item", key=d["path"], data_pg_item=d["path"]))
    return Element("div",
                   Element("div", "Folders", cls="pg-fb-section") if tiles else None,
                   Element("div", *tiles, cls="pg-fb-cards") if tiles else None,
                   Element("div", "Devices and drives", cls="pg-fb-section"),
                   Element("div", *cards, cls="pg-fb-cards"), cls="pg-fb-computer")


def file_browser(path=None, *, on_open=None, on_select=None, on_navigate=None, select="multiple", types=None,
                 folders_only=False, show_hidden=False, view="details", height=560, sidebar=True, manage=False,
                 places=None, thumbnails=True, key=None, cls=None, style=None):
    """A file browser like Windows Explorer or Finder, for any folder of the computer.

    ``path``          the folder shown: a ``State`` (two-way: it follows navigation) or a
                      string to start in. Default: the home folder. ``fs.COMPUTER`` ("")
                      shows the drives ("This PC").
    ``on_open``       ``fn(path)`` when a file is double-clicked or opened with Enter
                      (default: open it with its application)
    ``on_select``     ``fn(paths)`` (or ``fn(path)`` with ``select="single"``) as the
                      selection changes
    ``on_navigate``   ``fn(folder)`` after moving to another folder
    ``select``        ``"multiple"`` (Ctrl/Shift-click), ``"single"`` or ``None``
    ``types``         only show files with these extensions, e.g. ``["png", "jpg"]``
    ``folders_only``  hide files
    ``view``          ``"details"`` (columns) or ``"icons"`` (tiles, with image thumbnails)
    ``manage``        add New folder, Rename (F2) and Delete (to the Recycle Bin/Trash)
    ``places``        the Quick access list: ``[{"name", "path"}, ...]`` (default: ``fs.places()``)

    Keyboard: arrows, Home/End, PageUp/PageDown, Enter, Backspace (up), Alt+←/→, F5,
    Ctrl+A, and typing a letter jumps to the next name that starts with it.
    """
    return _FileBrowser(path, on_open, on_select, on_navigate, select, types, folders_only, show_hidden, view,
                        height, sidebar, manage, places, thumbnails, cls, style, key=key)


# =============================================================================
# File dialog
# =============================================================================
@component
def _FileDialog(open, mode, on_done, on_cancel, title, types, multiple, start, default_name, width, height):
    folder = use_state(lambda: start or fs.home())
    picked = use_state(list)
    name = use_state(default_name or "")
    confirm = use_state(None)
    if not _val(open):
        return None
    exts = [t.lower().lstrip(".") for t in types] if types else None

    def close():
        if isinstance(open, State):
            open.set(False)
        confirm.set(None)
        picked.set([])

    def cancel():
        close()
        if on_cancel is not None:
            _call_user(on_cancel)

    def finish(result):
        close()
        if on_done is not None:
            _call_user(on_done, result)

    def accept(paths=None):
        paths = paths if paths is not None else picked.value
        if mode == "folder":
            chosen = [p for p in paths if os.path.isdir(p)]
            target = chosen[0] if chosen else folder.value
            if target == fs.COMPUTER:
                return toast("Choose a folder", "warning")
            return finish(target)
        if mode == "save":
            n = (name.value or "").strip()
            problem = fs.check_name(n)
            if problem:
                return toast(problem, "warning")
            if exts and "." not in n:
                n += "." + exts[0]
            target = os.path.join(folder.value, n)
            if os.path.isdir(target):
                folder.set(target)
                return
            if os.path.exists(target) and confirm.value != target:
                return confirm.set(target)
            return finish(target)
        files = [p for p in paths if os.path.isfile(p)]
        if not files:
            return
        finish(files if multiple else files[0])

    def selected(paths):
        paths = paths if isinstance(paths, list) else ([paths] if paths else [])
        picked.set(paths)
        confirm.set(None)
        if mode == "save" and paths and os.path.isfile(paths[0]):
            name.set(os.path.basename(paths[0]))

    def opened(p):
        if mode == "folder":
            return
        if mode == "save":
            name.set(os.path.basename(p))
        accept([p])

    browser = file_browser(folder, on_select=selected, on_open=opened, on_navigate=lambda _f: picked.set([]),
                           select="multiple" if (multiple and mode == "open") else "single",
                           types=exts if mode != "folder" else None, folders_only=mode == "folder",
                           height=height, sidebar=True, key="pg-fd-browser")
    files_picked = [p for p in picked.value if os.path.isfile(p)]
    if mode == "save":
        left = Element("div", _input(name, placeholder="File name", icon="file", on_enter=lambda _v: accept(),
                                     key="pg-fd-name", cls="pg-fd-name"),
                       Element("span", "Save as " + ", ".join(f"*.{e}" for e in exts), cls="pg-fb-dim")
                       if exts else None, cls="pg-fd-left")
        ok = button("Replace" if confirm.value else "Save", lambda: accept(), icon="check",
                    variant="danger" if confirm.value else "primary", disabled=not (name.value or "").strip())
    elif mode == "folder":
        target = picked.value[0] if picked.value else folder.value
        left = Element("div", file_icon("folder", 18, is_dir=True),
                       Element("span", _folder_title(target) if target else "", cls="pg-truncate"), cls="pg-fd-left")
        ok = button("Select folder", lambda: accept(), icon="check", disabled=folder.value == fs.COMPUTER and not picked.value)
    else:
        label = (os.path.basename(files_picked[0]) if len(files_picked) == 1 else
                 f"{len(files_picked)} files" if files_picked else "No file selected")
        left = Element("div", _icon("file", 16), Element("span", label, cls="pg-truncate"),
                       Element("span", " · " + ", ".join(f"*.{e}" for e in exts), cls="pg-fb-dim") if exts else None,
                       cls="pg-fd-left")
        ok = button("Open", lambda: accept(), icon="check", disabled=not files_picked)
    warn = Element("div", _icon("alert", 15), Element("span", f"“{os.path.basename(confirm.value)}” already exists. "
                                                             "Replace it?"), cls="pg-fd-warn") if confirm.value else None
    footer = [left, warn, spacer(), button("Cancel", cancel, variant="ghost"), ok]
    heading = title or {"open": "Open", "save": "Save as", "folder": "Choose a folder"}.get(mode, "Open")
    return modal(True, browser, title=heading, footer=footer, width=width, on_close=cancel, cls="pg-fd")


def file_dialog(open, *, mode="open", on_done=None, on_cancel=None, title=None, types=None, multiple=False,
                start=None, default_name="", width=920, height=480, key=None):
    """An in-app file dialog, shown while ``open`` (a ``State``) is True.

    It is a :func:`file_browser` in a modal, so it looks and behaves the same on Windows,
    macOS and Linux, needs no external program, and never opens behind the window.

    ``mode``          ``"open"``, ``"save"`` or ``"folder"``
    ``on_done``       ``fn(result)``: a path, or a list of paths with ``multiple=True``
    ``on_cancel``     ``fn()`` when the dialog is dismissed
    ``types``         extensions to show (``["csv", "xlsx"]``); in save mode the first is
                      added to a name typed without one
    ``start``         the folder to open in (default: home); the dialog then remembers
                      where the user last was
    ``default_name``  the suggested file name in save mode

        show = State(False)
        ui.button("Import…", lambda: show.set(True))
        ui.file_dialog(show, types=["csv"], on_done=load_csv)
    """
    return _FileDialog(open, mode, on_done, on_cancel, title, types, multiple, start, default_name, width, height,
                       key=key)

"""Native macOS window: NSWindow + WKWebView through the Objective-C runtime, using only ctypes.

Python <-> UI communication is an in-process bridge (WKScriptMessageHandler for JS -> Python,
evaluateJavaScript for Python -> JS). No server, no ports.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import queue
import re
import traceback
from ctypes import CFUNCTYPE, POINTER, Structure, c_bool, c_char_p, c_double, c_long, c_short, c_ulong, c_void_p

_objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
ctypes.cdll.LoadLibrary("/System/Library/Frameworks/WebKit.framework/WebKit")
_libsystem = ctypes.CDLL("/usr/lib/libSystem.B.dylib")

_objc.objc_getClass.restype = c_void_p
_objc.objc_getClass.argtypes = [c_char_p]
_objc.objc_getProtocol.restype = c_void_p
_objc.objc_getProtocol.argtypes = [c_char_p]
_objc.sel_registerName.restype = c_void_p
_objc.sel_registerName.argtypes = [c_char_p]
_objc.objc_allocateClassPair.restype = c_void_p
_objc.objc_allocateClassPair.argtypes = [c_void_p, c_char_p, ctypes.c_size_t]
_objc.objc_registerClassPair.argtypes = [c_void_p]
_objc.class_addMethod.restype = c_bool
_objc.class_addMethod.argtypes = [c_void_p, c_void_p, c_void_p, c_char_p]
_objc.class_addProtocol.restype = c_bool
_objc.class_addProtocol.argtypes = [c_void_p, c_void_p]

_MSG_SEND = ctypes.cast(_objc.objc_msgSend, c_void_p).value
_DISPATCH_FN = CFUNCTYPE(None, c_void_p)
_libsystem.dispatch_async_f.argtypes = [c_void_p, c_void_p, _DISPATCH_FN]
_MAIN_QUEUE = ctypes.addressof(c_void_p.in_dll(_libsystem, "_dispatch_main_q"))


class CGPoint(Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


class CGSize(Structure):
    _fields_ = [("width", c_double), ("height", c_double)]


class CGRect(Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


_sels, _protos = {}, {}


def _sel(name):
    s = _sels.get(name)
    if s is None:
        s = _sels[name] = _objc.sel_registerName(name.encode())
    return s


def _cls(name):
    return _objc.objc_getClass(name.encode())


def msg(obj, selector, *args, restype=c_void_p, argtypes=None):
    """objc_msgSend with an explicit signature (required on Apple Silicon)."""
    if argtypes is None:
        argtypes = [c_void_p] * len(args)
    key = (restype, tuple(argtypes))
    fn = _protos.get(key)
    if fn is None:
        fn = _protos[key] = CFUNCTYPE(restype, c_void_p, c_void_p, *argtypes)(_MSG_SEND)
    return fn(obj, _sel(selector), *args)


def new(class_name):
    return msg(msg(_cls(class_name), "alloc"), "init")


def nsstr(s):
    return msg(_cls("NSString"), "stringWithUTF8String:", str(s).encode("utf-8"), argtypes=[c_char_p])


def pystr(ns):
    if not ns:
        return ""
    raw = msg(ns, "UTF8String", restype=c_char_p)
    return raw.decode("utf-8", "replace") if raw else ""


def nsbool(v):
    return msg(_cls("NSNumber"), "numberWithBool:", bool(v), argtypes=[c_bool])


_keepalive = []


def _make_class(name, methods, protocols=()):
    existing = _cls(name)
    if existing:
        return existing
    new_cls = _objc.objc_allocateClassPair(_cls("NSObject"), name.encode(), 0)
    for selector, (functype, fn, encoding) in methods.items():
        imp = functype(fn)
        _keepalive.append(imp)
        _objc.class_addMethod(new_cls, _sel(selector), ctypes.cast(imp, c_void_p), encoding)
    for proto in protocols:
        p = _objc.objc_getProtocol(proto.encode())
        if p:
            _objc.class_addProtocol(new_cls, p)
    _objc.objc_registerClassPair(new_cls)
    return new_cls


_VOID3 = CFUNCTYPE(None, c_void_p, c_void_p, c_void_p)
_VOID4 = CFUNCTYPE(None, c_void_p, c_void_p, c_void_p, c_void_p)
_BOOL3 = CFUNCTYPE(c_bool, c_void_p, c_void_p, c_void_p)
_ULONG3 = CFUNCTYPE(c_ulong, c_void_p, c_void_p, c_void_p)

# Only one window per process; callbacks route through this.
_active = {"window": None}


def _on_script_message(_self, _cmd, _controller, message):
    win = _active["window"]
    if win is not None:
        try:
            win.on_message(pystr(msg(message, "body")))
        except Exception:
            traceback.print_exc()


def _on_window_close(_self, _cmd, _notification):
    win = _active["window"]
    if win is not None:
        win._stop_loop()


def _should_terminate(_self, _cmd, _app):
    win = _active["window"]
    if win is not None:
        win._stop_loop()
    return 0  # NSTerminateCancel: let NSApp.run() return so Python can clean up


def _last_window_closed(_self, _cmd, _app):
    return True


_THEME_BG = {"dark": (0x0b / 255, 0x0d / 255, 0x12 / 255), "light": (0xf7 / 255, 0xf7 / 255, 0xf8 / 255)}


class MacWindow:
    def __init__(self, *, title, html_path, read_access, width, height, min_size, theme, debug, on_message,
                 icon=None, background=None):
        self.title = title
        self.html_path = html_path
        self.read_access = read_access
        self.width, self.height = width, height
        self.min_size = min_size
        self.theme = theme
        self.debug = debug
        self.on_message = on_message
        self.icon = icon
        self.background = background or _THEME_BG
        self._calls = queue.SimpleQueue()
        self._drain_cb = _DISPATCH_FN(self._drain)
        self.app = self.window = self.webview = None

    # -- threading -----------------------------------------------------------
    def _drain(self, _ctx):
        while True:
            try:
                fn = self._calls.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception:
                traceback.print_exc()

    def on_main(self, fn):
        """Run ``fn`` on the Cocoa main thread (safe to call from any thread)."""
        self._calls.put(fn)
        _libsystem.dispatch_async_f(_MAIN_QUEUE, None, self._drain_cb)

    # -- public API (thread-safe) ---------------------------------------------
    def eval_js(self, code):
        def run():
            if self.webview:
                msg(self.webview, "evaluateJavaScript:completionHandler:", nsstr(code), None)
        self.on_main(run)

    def set_title(self, title):
        self.on_main(lambda: self.window and msg(self.window, "setTitle:", nsstr(title)))

    def set_theme(self, theme):
        self.on_main(lambda: self._apply_theme(theme))

    def close(self):
        self.on_main(lambda: self.window and msg(self.window, "performClose:", None))

    def minimize(self):
        self.on_main(lambda: self.window and msg(self.window, "miniaturize:", None))

    def toggle_fullscreen(self):
        self.on_main(lambda: self.window and msg(self.window, "toggleFullScreen:", None))

    def set_size(self, width, height):
        def run():
            if self.window:
                msg(self.window, "setContentSize:", CGSize(width, height), argtypes=[CGSize])
        self.on_main(run)

    # -- internals -----------------------------------------------------------
    def _apply_theme(self, theme):
        if not self.window or theme not in self.background:
            return
        self.theme = theme
        name = "NSAppearanceNameDarkAqua" if theme == "dark" else "NSAppearanceNameAqua"
        msg(self.window, "setAppearance:", msg(_cls("NSAppearance"), "appearanceNamed:", nsstr(name)))
        r, g, b = self.background[theme]
        color = msg(_cls("NSColor"), "colorWithSRGBRed:green:blue:alpha:", r, g, b, 1.0, argtypes=[c_double] * 4)
        msg(self.window, "setBackgroundColor:", color)

    def _stop_loop(self):
        if not self.app:
            return
        msg(self.app, "stop:", None)
        # stop: only takes effect after an event is processed; post a no-op one.
        event = msg(_cls("NSEvent"),
                    "otherEventWithType:location:modifierFlags:timestamp:windowNumber:context:subtype:data1:data2:",
                    15, CGPoint(0, 0), 0, 0.0, 0, None, 0, 0, 0,
                    argtypes=[c_ulong, CGPoint, c_ulong, c_double, c_long, c_void_p, c_short, c_long, c_long])
        msg(self.app, "postEvent:atStart:", event, True, argtypes=[c_void_p, c_bool])

    def _item(self, menu, title, action, key="", mask=None):
        item = msg(msg(_cls("NSMenuItem"), "alloc"), "initWithTitle:action:keyEquivalent:",
                   nsstr(title), _sel(action) if action else None, nsstr(key))
        if mask is not None:
            msg(item, "setKeyEquivalentModifierMask:", mask, argtypes=[c_ulong])
        msg(menu, "addItem:", item)
        return item

    def _submenu(self, bar, title):
        holder = new("NSMenuItem")
        menu = msg(msg(_cls("NSMenu"), "alloc"), "initWithTitle:", nsstr(title))
        msg(holder, "setSubmenu:", menu)
        msg(bar, "addItem:", holder)
        return menu

    def _build_menu(self):
        bar = new("NSMenu")
        sep = lambda m: msg(m, "addItem:", msg(_cls("NSMenuItem"), "separatorItem"))
        app_menu = self._submenu(bar, self.title)
        self._item(app_menu, f"Hide {self.title}", "hide:", "h")
        self._item(app_menu, "Hide Others", "hideOtherApplications:", "h", (1 << 19) | (1 << 20))
        sep(app_menu)
        self._item(app_menu, f"Quit {self.title}", "terminate:", "q")
        edit = self._submenu(bar, "Edit")
        self._item(edit, "Undo", "undo:", "z")
        self._item(edit, "Redo", "redo:", "Z")
        sep(edit)
        self._item(edit, "Cut", "cut:", "x")
        self._item(edit, "Copy", "copy:", "c")
        self._item(edit, "Paste", "paste:", "v")
        self._item(edit, "Select All", "selectAll:", "a")
        view = self._submenu(bar, "View")
        self._item(view, "Enter Full Screen", "toggleFullScreen:", "f", (1 << 18) | (1 << 20))
        window = self._submenu(bar, "Window")
        self._item(window, "Minimize", "performMiniaturize:", "m")
        self._item(window, "Zoom", "performZoom:", "")
        self._item(window, "Close", "performClose:", "w")
        msg(self.app, "setMainMenu:", bar)
        msg(self.app, "setWindowsMenu:", window)

    def _rename_process(self):
        bundle = msg(_cls("NSBundle"), "mainBundle")
        info = msg(bundle, "infoDictionary") if bundle else None
        if info and msg(info, "respondsToSelector:", _sel("setObject:forKey:"), restype=c_bool):
            msg(info, "setObject:forKey:", nsstr(self.title), nsstr("CFBundleName"))

    def run(self):
        """Create the window and block in the Cocoa event loop until it is closed."""
        _active["window"] = self
        pool = new("NSAutoreleasePool")
        self._rename_process()
        self.app = msg(_cls("NSApplication"), "sharedApplication")
        msg(self.app, "setActivationPolicy:", 0, argtypes=[c_long])
        self._build_menu()
        if self.icon:
            img = msg(msg(_cls("NSImage"), "alloc"), "initWithContentsOfFile:", nsstr(self.icon))
            if img:
                msg(self.app, "setApplicationIconImage:", img)

        delegate_cls = _make_class("ZePyGUIDelegate", {
            "windowWillClose:": (_VOID3, _on_window_close, b"v@:@"),
            "applicationShouldTerminate:": (_ULONG3, _should_terminate, b"Q@:@"),
            "applicationShouldTerminateAfterLastWindowClosed:": (_BOOL3, _last_window_closed, b"c@:@"),
        }, protocols=("NSWindowDelegate", "NSApplicationDelegate"))
        bridge_cls = _make_class("ZePyGUIBridge", {
            "userContentController:didReceiveScriptMessage:": (_VOID4, _on_script_message, b"v@:@@"),
        }, protocols=("WKScriptMessageHandler",))
        delegate = new_instance(delegate_cls)
        msg(self.app, "setDelegate:", delegate)

        rect = CGRect(CGPoint(0, 0), CGSize(self.width, self.height))
        style = 1 | 2 | 4 | 8  # titled | closable | miniaturizable | resizable
        self.window = msg(msg(_cls("NSWindow"), "alloc"), "initWithContentRect:styleMask:backing:defer:",
                          rect, style, 2, False, argtypes=[CGRect, c_ulong, c_ulong, c_bool])
        msg(self.window, "setReleasedWhenClosed:", False, argtypes=[c_bool])
        msg(self.window, "setTitle:", nsstr(self.title))
        msg(self.window, "setTitlebarAppearsTransparent:", True, argtypes=[c_bool])
        msg(self.window, "setContentMinSize:", CGSize(*self.min_size), argtypes=[CGSize])
        msg(self.window, "setDelegate:", delegate)
        self._apply_theme(self.theme)

        config = new("WKWebViewConfiguration")
        controller = msg(config, "userContentController")
        msg(controller, "addScriptMessageHandler:name:", new_instance(bridge_cls), nsstr("zepygui"))
        prefs = msg(config, "preferences")
        msg(prefs, "setValue:forKey:", nsbool(True), nsstr("allowFileAccessFromFileURLs"))
        if self.debug:
            msg(prefs, "setValue:forKey:", nsbool(True), nsstr("developerExtrasEnabled"))

        self.webview = msg(msg(_cls("WKWebView"), "alloc"), "initWithFrame:configuration:", rect, config,
                           argtypes=[CGRect, c_void_p])
        msg(self.webview, "setAutoresizingMask:", 18, argtypes=[c_ulong])  # width + height sizable
        msg(self.webview, "setValue:forKey:", nsbool(False), nsstr("drawsBackground"))  # no white flash
        msg(self.window, "setContentView:", self.webview)
        url = msg(_cls("NSURL"), "fileURLWithPath:", nsstr(self.html_path))
        access = msg(_cls("NSURL"), "fileURLWithPath:", nsstr(self.read_access))
        msg(self.webview, "loadFileURL:allowingReadAccessToURL:", url, access)

        msg(self.window, "center")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", self.title)
        msg(self.window, "setFrameAutosaveName:", nsstr(f"ZePyGUI-{slug}"))
        msg(self.window, "makeKeyAndOrderFront:", None)
        msg(self.app, "activateIgnoringOtherApps:", True, argtypes=[c_bool])
        try:
            msg(self.app, "run")
        finally:
            webview, self.webview = self.webview, None
            if webview:
                msg(webview, "stopLoading:", None)
            if self.window:
                msg(self.window, "orderOut:", None)
            self.window = None
            _active["window"] = None
            msg(pool, "drain")


def new_instance(class_ptr):
    return msg(msg(class_ptr, "alloc"), "init")


__all__ = ["MacWindow", "CGRect", "CGSize", "CGPoint", "POINTER"]

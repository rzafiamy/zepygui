"""Open the UI in a chrome-less native window using a Chromium engine already on the system.

Like Tauri relies on the OS webview, ZePyGUI reuses an installed Chromium-based browser
(Edge ships with Windows; Chrome/Brave/Chromium elsewhere) in ``--app`` mode: no tabs,
no address bar, its own window and dock/taskbar entry, and a private profile per app.
Set ``ZEPYGUI_BROWSER=/path/to/browser`` to choose one explicitly.

The browser is started on a small file in its (private) profile folder that forwards to the
app's URL, so the launch token never appears on the command line, which every local user can
read in the process list.
"""
from __future__ import annotations

import html
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path


def find_browser():
    custom = os.environ.get("ZEPYGUI_BROWSER")
    if custom:
        return custom if os.path.exists(custom) else shutil.which(custom)
    system = platform.system()
    if system == "Darwin":
        apps = ["Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium", "Vivaldi", "Google Chrome Canary"]
        for base in ("/Applications", str(Path.home() / "Applications")):
            for name in apps:
                exe = f"{base}/{name}.app/Contents/MacOS/{name}"
                if os.path.exists(exe):
                    return exe
    elif system == "Windows":
        rels = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
                r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Chromium\Application\chrome.exe"]
        bases = [os.environ.get(v) for v in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        for rel in rels:
            for base in filter(None, bases):
                exe = os.path.join(base, rel)
                if os.path.exists(exe):
                    return exe
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
                 "microsoft-edge-stable", "brave-browser", "vivaldi"):
        exe = shutil.which(name)
        if exe:
            return exe
    return None


def _profile_dir(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "app"
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Caches" / "zepygui"
    elif system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "zepygui"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "zepygui"
    path = base / "profiles" / slug
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(path, 0o700)  # the profile holds the window's cookie and the launch file
        except OSError:
            pass
    return path


def write_launch_file(folder, url):
    """A page, readable only by this user, that forwards the browser to ``url``. Returns its path."""
    path = Path(folder) / "launch.html"
    page = (f'<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer">'
            f'<meta http-equiv="refresh" content="0;url={html.escape(url)}"><body style="background:#0b0d12">')
    try:
        os.remove(path)  # recreate it so the permissions below apply even to an old file
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(page.encode("utf-8"))
    return path


def open_window(url, title, width, height):
    """Launch an app window. Returns ``(process, launch_file)``; the process is None if no
    Chromium was found. Delete ``launch_file`` once the window has used it."""
    exe = find_browser()
    if not exe:
        return None, None
    profile = _profile_dir(title)
    try:
        launch = write_launch_file(profile, url)
        target = launch.resolve().as_uri()
    except OSError:
        launch, target = None, url
    args = [
        exe,
        f"--app={target}",
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
        "--disable-background-networking",
        "--disable-sync",
    ]
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if platform.system() != "Windows":
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(args, **kwargs), launch
    except OSError:
        if launch:
            try:
                os.remove(launch)
            except OSError:
                pass
        return None, None

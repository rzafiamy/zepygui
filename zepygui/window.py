"""Open the UI in a chrome-less native window using a Chromium engine already on the system.

Like Tauri relies on the OS webview, ZePyGUI reuses an installed Chromium-based browser
(Edge ships with Windows; Chrome/Brave/Chromium elsewhere) in ``--app`` mode: no tabs,
no address bar, its own window and dock/taskbar entry, and a private profile per app.
Set ``ZEPYGUI_BROWSER=/path/to/browser`` to choose one explicitly.
"""
from __future__ import annotations

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
    return path


def open_window(url, title, width, height):
    """Launch an app window. Returns the browser process, or None if no Chromium was found."""
    exe = find_browser()
    if not exe:
        return None
    args = [
        exe,
        f"--app={url}",
        f"--user-data-dir={_profile_dir(title)}",
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
        return subprocess.Popen(args, **kwargs)
    except OSError:
        return None

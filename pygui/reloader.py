"""Development auto-reload: restart the app process whenever a source file changes."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_SKIP_DIRS = {"__pycache__", "node_modules", "venv", "env", "site-packages", "build", "dist"}
_EXTS = {".py", ".css", ".js", ".html", ".json", ".md"}


def _snapshot(root):
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]
        for name in filenames:
            if os.path.splitext(name)[1] in _EXTS:
                path = os.path.join(dirpath, name)
                try:
                    found[path] = os.stat(path).st_mtime
                except OSError:
                    pass
        if len(found) > 5000:
            break
    return found


def run_with_reloader():
    root = Path(sys.argv[0]).resolve().parent
    env = dict(os.environ, PYGUI_CHILD="1")
    cmd = [sys.executable] + sys.argv

    def start():
        return subprocess.Popen(cmd, env=env)

    print(f"[pygui] watching {root} for changes")
    child = start()
    files = _snapshot(root)
    crashed = False
    try:
        while True:
            time.sleep(0.5)
            code = child.poll()
            if code == 0 and not crashed:
                return  # window closed by the user
            if code is not None and not crashed:
                crashed = True
                print("[pygui] app exited with an error; fix it and save to restart")
            current = _snapshot(root)
            if current != files:
                files = current
                print("[pygui] change detected, reloading…")
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                child = start()
                crashed = False
    except KeyboardInterrupt:
        pass
    finally:
        if child.poll() is None:
            child.terminate()

"""OS integration without dependencies: native file dialogs, notifications, opening files/URLs.

Dialog functions block until the user answers, so call them from event handlers
(each window has its own thread, the UI stays responsive to other windows) and they
return ``None`` when cancelled.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import webbrowser

_SYSTEM = platform.system()


def _as(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _osascript(script):
    r = subprocess.run(["osascript", "-"], input=script, capture_output=True, text=True)
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


def _ps(script):
    r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _ps_str(s):
    return "'" + str(s).replace("'", "''") + "'"


def _win_filter(types):
    if not types:
        return "All files (*.*)|*.*"
    pats = ";".join(f"*.{t.lstrip('.')}" for t in types)
    return f"Supported files ({pats})|{pats}|All files (*.*)|*.*"


def _linux(args):
    for tool in ("zenity", "kdialog"):
        if shutil.which(tool):
            r = subprocess.run([tool] + args[tool], capture_output=True, text=True)
            return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    print("[zepygui] install zenity or kdialog for native file dialogs")
    return None


def open_file(title="Open", types=None, multiple=False):
    """Ask for a file to open. ``types`` like ``["png", "jpg"]``. Returns a path (or list if ``multiple``)."""
    types = [t.lstrip(".") for t in (types or [])]
    if _SYSTEM == "Darwin":
        of_type = f" of type {{{', '.join(_as(t) for t in types)}}}" if types else ""
        multi = " with multiple selections allowed" if multiple else ""
        out = _osascript(f"""
            set picked to choose file with prompt {_as(title)}{of_type}{multi}
            if class of picked is list then
                set acc to ""
                repeat with f in picked
                    set acc to acc & POSIX path of f & linefeed
                end repeat
                return acc
            end if
            return POSIX path of picked""")
    elif _SYSTEM == "Windows":
        out = _ps(f"""Add-Type -AssemblyName System.Windows.Forms
            $d = New-Object System.Windows.Forms.OpenFileDialog
            $d.Title = {_ps_str(title)}; $d.Filter = {_ps_str(_win_filter(types))}
            $d.Multiselect = ${str(bool(multiple)).lower()}
            if ($d.ShowDialog() -eq 'OK') {{ $d.FileNames -join "`n" }}""")
    else:
        zen = ["--file-selection", f"--title={title}"] + (["--multiple", "--separator=\n"] if multiple else [])
        if types:
            zen.append("--file-filter=" + " ".join(f"*.{t}" for t in types))
        kde = ["--getopenfilename", os.getcwd(), " ".join(f"*.{t}" for t in types)] + \
            (["--multiple", "--separate-output"] if multiple else [])
        out = _linux({"zenity": zen, "kdialog": kde})
    if not out:
        return None
    paths = [p for p in out.splitlines() if p.strip()]
    return paths if multiple else (paths[0] if paths else None)


def save_file(title="Save", default_name="", types=None):
    """Ask where to save a file. Returns the chosen path or None."""
    if _SYSTEM == "Darwin":
        return _osascript(f"return POSIX path of (choose file name with prompt {_as(title)} "
                          f"default name {_as(default_name or 'Untitled')})") or None
    if _SYSTEM == "Windows":
        return _ps(f"""Add-Type -AssemblyName System.Windows.Forms
            $d = New-Object System.Windows.Forms.SaveFileDialog
            $d.Title = {_ps_str(title)}; $d.FileName = {_ps_str(default_name)}
            $d.Filter = {_ps_str(_win_filter(types))}
            if ($d.ShowDialog() -eq 'OK') {{ $d.FileName }}""")
    return _linux({"zenity": ["--file-selection", "--save", "--confirm-overwrite", f"--title={title}",
                              f"--filename={default_name}"],
                   "kdialog": ["--getsavefilename", os.path.join(os.getcwd(), default_name)]})


def choose_folder(title="Choose a folder"):
    """Ask for a directory. Returns its path or None."""
    if _SYSTEM == "Darwin":
        return _osascript(f"return POSIX path of (choose folder with prompt {_as(title)})") or None
    if _SYSTEM == "Windows":
        return _ps(f"""Add-Type -AssemblyName System.Windows.Forms
            $d = New-Object System.Windows.Forms.FolderBrowserDialog
            $d.Description = {_ps_str(title)}
            if ($d.ShowDialog() -eq 'OK') {{ $d.SelectedPath }}""")
    return _linux({"zenity": ["--file-selection", "--directory", f"--title={title}"],
                   "kdialog": ["--getexistingdirectory", os.getcwd()]})


def notify(title, message=""):
    """System notification (Notification Center / notify-send). Returns False if unsupported."""
    if _SYSTEM == "Darwin":
        return _osascript(f"display notification {_as(message)} with title {_as(title)}") is not None
    if _SYSTEM == "Linux" and shutil.which("notify-send"):
        return subprocess.run(["notify-send", str(title), str(message)]).returncode == 0
    if _SYSTEM == "Windows":
        script = f"""Add-Type -AssemblyName System.Windows.Forms
            $n = New-Object System.Windows.Forms.NotifyIcon
            $n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true
            $n.ShowBalloonTip(5000, {_ps_str(title)}, {_ps_str(message or ' ')}, 'Info'); Start-Sleep 6; $n.Dispose()"""
        subprocess.Popen(["powershell", "-NoProfile", "-Command", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    return False


def open_url(url):
    """Open a web page in the user's default browser."""
    webbrowser.open(url)


def open_path(path, reveal=False):
    """Open a file/folder with its default app, or ``reveal`` it in Finder/Explorer."""
    path = os.path.abspath(path)
    if _SYSTEM == "Darwin":
        subprocess.Popen(["open", "-R", path] if reveal else ["open", path])
    elif _SYSTEM == "Windows":
        if reveal:
            subprocess.Popen(["explorer", "/select,", path])
        else:
            os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) if reveal else path])

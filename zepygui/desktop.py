"""OS integration without dependencies: native file dialogs, notifications, opening files/URLs.

On Windows the dialogs come straight from the system (``comdlg32``/``shell32`` through
``ctypes``): they open instantly, owned by the app window. PowerShell is only a fallback.

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


# -- Windows: the common dialogs, straight from comdlg32/shell32 (no PowerShell start-up) --
def _win_dialog(kind, title, types=None, multiple=False, default_name=""):
    """Native Windows dialog through ``ctypes``. Raises ``OSError``/``AttributeError`` if unavailable."""
    import ctypes
    from ctypes import wintypes

    ole32, user32 = ctypes.windll.ole32, ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    owner = user32.GetForegroundWindow()  # the app window: the dialog stays on top of it
    ole32.CoInitialize(None)
    try:
        if kind == "folder":
            class BROWSEINFOW(ctypes.Structure):
                _fields_ = [("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p),
                            ("pszDisplayName", wintypes.LPWSTR), ("lpszTitle", wintypes.LPCWSTR),
                            ("ulFlags", ctypes.c_uint), ("lpfn", ctypes.c_void_p), ("lParam", wintypes.LPARAM),
                            ("iImage", ctypes.c_int)]

            shell32 = ctypes.windll.shell32
            shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
            shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
            name = ctypes.create_unicode_buffer(260)
            info = BROWSEINFOW(hwndOwner=owner, pszDisplayName=ctypes.cast(name, wintypes.LPWSTR),
                               lpszTitle=title, ulFlags=0x0001 | 0x0040)  # file system only, resizable, new folder
            pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
            if not pidl:
                return None
            try:
                path = ctypes.create_unicode_buffer(32768)
                return path.value if shell32.SHGetPathFromIDListW(pidl, path) else None
            finally:
                ole32.CoTaskMemFree(ctypes.c_void_p(pidl))

        class OPENFILENAMEW(ctypes.Structure):
            _fields_ = [("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND),
                        ("hInstance", wintypes.HINSTANCE), ("lpstrFilter", ctypes.c_void_p),
                        ("lpstrCustomFilter", wintypes.LPWSTR), ("nMaxCustFilter", wintypes.DWORD),
                        ("nFilterIndex", wintypes.DWORD), ("lpstrFile", ctypes.c_void_p),
                        ("nMaxFile", wintypes.DWORD), ("lpstrFileTitle", wintypes.LPWSTR),
                        ("nMaxFileTitle", wintypes.DWORD), ("lpstrInitialDir", wintypes.LPCWSTR),
                        ("lpstrTitle", wintypes.LPCWSTR), ("Flags", wintypes.DWORD),
                        ("nFileOffset", wintypes.WORD), ("nFileExtension", wintypes.WORD),
                        ("lpstrDefExt", wintypes.LPCWSTR), ("lCustData", wintypes.LPARAM),
                        ("lpfnHook", ctypes.c_void_p), ("lpTemplateName", wintypes.LPCWSTR),
                        ("pvReserved", ctypes.c_void_p), ("dwReserved", wintypes.DWORD), ("FlagsEx", wintypes.DWORD)]

        size = 65536
        file_buf = ctypes.create_unicode_buffer(default_name or "", size)
        filt = _win_filter(types).replace("|", "\0") + "\0\0"  # pairs of "label\0pattern\0", then \0
        filt_buf = ctypes.create_unicode_buffer(filt, len(filt) + 1)
        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        ofn.hwndOwner = owner
        ofn.lpstrFilter = ctypes.cast(filt_buf, ctypes.c_void_p)
        ofn.nFilterIndex = 1
        ofn.lpstrFile = ctypes.cast(file_buf, ctypes.c_void_p)
        ofn.nMaxFile = size
        ofn.lpstrTitle = title
        explorer, nochangedir = 0x80000, 0x8
        if kind == "save":
            ofn.Flags = explorer | nochangedir | 0x2 | 0x800  # overwrite prompt, path must exist
            ofn.lpstrDefExt = types[0].lstrip(".") if types else None
            ok = ctypes.windll.comdlg32.GetSaveFileNameW(ctypes.byref(ofn))
        else:
            ofn.Flags = explorer | nochangedir | 0x1000 | 0x800 | (0x200 if multiple else 0)
            ok = ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn))
        if not ok:
            if ctypes.windll.comdlg32.CommDlgExtendedError():
                raise OSError("common dialog failed")
            return None  # cancelled
        raw = ctypes.wstring_at(file_buf, size).split("\0\0", 1)[0]
        parts = raw.split("\0")
        if kind == "open" and multiple:
            # one file: its full path; several: the folder, then each name
            return parts if len(parts) == 1 else [os.path.join(parts[0], n) for n in parts[1:]]
        return parts[0] or None
    finally:
        ole32.CoUninitialize()


def _win_try(kind, *args, **kw):
    try:
        return True, _win_dialog(kind, *args, **kw)
    except (OSError, AttributeError, ValueError, TypeError):
        return False, None  # fall back to PowerShell


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
        done, result = _win_try("open", title, types, multiple)
        if done:
            return result
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
        done, result = _win_try("save", title, types, default_name=default_name)
        if done:
            return result
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
        done, result = _win_try("folder", title)
        if done:
            return result
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

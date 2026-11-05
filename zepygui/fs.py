"""The file system as a file browser sees it: drives, known folders, fast listings, the trash.

Everything here is plain standard library and works the same on Windows, macOS and Linux:

    from zepygui import fs

    fs.drives()                  # [{"name": "Local Disk (C:)", "path": "C:\\\\", "kind": "fixed", ...}, ...]
    fs.places()                  # Home, Desktop, Documents, Downloads, Pictures, Music, Videos
    fs.listdir("C:\\\\Users")       # [Entry(...), ...] folders first, natural order ("file2" < "file10")
    fs.crumbs("C:\\\\Users\\\\me")    # [("Local Disk (C:)", "C:\\\\"), ("Users", "C:\\\\Users"), ("me", ...)]
    fs.trash(path)               # Recycle Bin / Trash, never a permanent delete

On Windows, drives come from ``GetLogicalDrives`` (with their labels and types), known
folders from ``SHGetKnownFolderPath`` (so a Documents folder moved to OneDrive is found),
hidden files from their file attributes, and :func:`trash` uses the Recycle Bin. No
PowerShell is started for any of it.

Listings are cached per folder and revalidated with the folder's modification time,
so going back and forth between folders costs one ``stat``.
"""
from __future__ import annotations

import ntpath
import os
import platform
import posixpath
import re
import shutil
import stat as _stat
import subprocess
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

SYSTEM = platform.system()
WINDOWS = SYSTEM == "Windows"
COMPUTER = ""  # the pseudo-path of the top level: drives and volumes ("This PC")
COMPUTER_LABEL = "This PC" if WINDOWS else "Computer"

__all__ = ["Entry", "COMPUTER", "COMPUTER_LABEL", "drives", "places", "listdir", "crumbs", "parent", "join", "kind_of",
           "human_size", "human_time", "is_hidden", "trash", "make_folder", "rename", "unique_name",
           "invalidate", "is_cached", "file_url", "home", "type_label", "check_name", "sort_entries"]

# =============================================================================
# Entries
# =============================================================================
_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4


class Entry:
    """One file or folder of a listing (cheap: built from ``os.scandir`` data)."""

    __slots__ = ("name", "path", "is_dir", "size", "modified", "hidden", "link", "ext", "kind")

    def __init__(self, name, path, is_dir, size=0, modified=0.0, hidden=False, link=False):
        self.name, self.path, self.is_dir = name, path, is_dir
        self.size, self.modified, self.hidden, self.link = size, modified, hidden, link
        dot = name.rfind(".")
        self.ext = name[dot + 1:].lower() if dot > 0 and not is_dir else ""
        self.kind = "folder" if is_dir else _EXT_KIND.get(self.ext, "file")

    @property
    def id(self):  # lets virtual lists and tables key rows by path
        return self.path

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    def __getitem__(self, key):  # tables read cells with row[key]
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __repr__(self):
        return f"Entry({self.path!r}{', dir' if self.is_dir else ''})"


def is_hidden(name, st=None):
    """Dot-files everywhere, plus the hidden and system attributes on Windows."""
    if name.startswith("."):
        return True
    attrs = getattr(st, "st_file_attributes", 0) if st is not None else 0
    return bool(attrs & (_FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM))


# =============================================================================
# File kinds: drive the icon and its colour
# =============================================================================
KINDS = {
    # kind: (label, extensions)
    "image": ("Image", "png jpg jpeg gif webp bmp svg ico tif tiff heic heif avif raw cr2 nef psd"),
    "video": ("Video", "mp4 mkv mov avi webm wmv flv m4v mpg mpeg 3gp"),
    "audio": ("Audio", "mp3 wav flac aac ogg m4a wma opus aiff mid midi"),
    "archive": ("Archive", "zip rar 7z tar gz tgz bz2 xz zst cab lz iso dmg"),
    "pdf": ("PDF document", "pdf"),
    "doc": ("Document", "doc docx odt rtf pages"),
    "sheet": ("Spreadsheet", "xls xlsx xlsm ods csv tsv numbers"),
    "slides": ("Presentation", "ppt pptx odp key"),
    "text": ("Text", "txt md markdown rst log ini cfg conf toml yaml yml nfo"),
    "code": ("Source code", "py pyw ipynb js mjs ts tsx jsx html htm css scss json xml c h cpp hpp cs java kt go "
             "rs rb php swift sh bash zsh ps1 bat cmd sql lua r dart vue svelte"),
    "exe": ("Application", "exe msi app apk appimage deb rpm com scr"),
    "font": ("Font", "ttf otf woff woff2 fon"),
    "data": ("Data", "db sqlite sqlite3 parquet bin dat pkl npy h5"),
    "link": ("Shortcut", "lnk url webloc desktop"),
}
_EXT_KIND = {ext: kind for kind, (_, exts) in KINDS.items() for ext in exts.split()}
KIND_LABELS = {kind: label for kind, (label, _) in KINDS.items()}
KIND_LABELS.update({"folder": "Folder", "file": "File"})
TEXT_KINDS = {"text", "code"}


def kind_of(name, is_dir=False):
    """``"folder"``, ``"image"``, ``"video"``, ``"audio"``, ``"archive"``, ``"pdf"``, ``"code"``… or ``"file"``."""
    if is_dir:
        return "folder"
    dot = name.rfind(".")
    return _EXT_KIND.get(name[dot + 1:].lower(), "file") if dot > 0 else "file"


def type_label(entry):
    """What Explorer shows in its Type column: "Folder", "PNG image", "Python source"…"""
    if entry.is_dir:
        return "Folder"
    if not entry.ext:
        return "File"
    label = KIND_LABELS.get(entry.kind, "File")
    if entry.kind in ("file", "pdf"):
        return f"{entry.ext.upper()} file" if entry.kind == "file" else label
    return f"{entry.ext.upper()} {label.lower()}"


# =============================================================================
# Formatting
# =============================================================================
def human_size(n):
    """``1536`` -> ``"1.5 KB"`` (powers of 1024, like Explorer and Finder's list view)."""
    if n is None:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" or n >= 100 else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def human_time(ts, now=None):
    """A short, friendly timestamp: "14:05" today, "Yesterday", "Mar 3", "2024-03-03"."""
    if not ts:
        return ""
    now = now or time.time()
    d, today = datetime.fromtimestamp(ts), datetime.fromtimestamp(now)
    if d.date() == today.date():
        return d.strftime("Today %H:%M")
    if (today.date() - d.date()).days == 1:
        return d.strftime("Yesterday %H:%M")
    if d.year == today.year:
        return d.strftime("%b %d, %H:%M")
    return d.strftime("%Y-%m-%d")


# =============================================================================
# Paths: pass ``flavor=ntpath`` to handle Windows paths on any system
# =============================================================================
def _flavor(path, flavor=None):
    if flavor is not None:
        return flavor
    return ntpath if WINDOWS else posixpath


def home():
    return str(Path.home())


def join(folder, name, flavor=None):
    return _flavor(folder, flavor).join(folder, name)


def parent(path, flavor=None):
    """The folder above ``path``; :data:`COMPUTER` above a drive or the root."""
    if not path:
        return None
    f = _flavor(path, flavor)
    norm = f.normpath(path)
    _, rest = f.splitdrive(norm)
    if not rest.strip("\\/"):
        return COMPUTER
    return f.dirname(norm)


def _drive_label(drive, info=None):
    """"Local Disk (C:)", "USB Drive (E:)", "share (\\\\server)"."""
    info = info or {}
    letter = drive.rstrip("\\/")
    if letter.startswith("\\\\"):
        parts = letter.strip("\\").split("\\")
        return f"{parts[1]} (\\\\{parts[0]})" if len(parts) > 1 else letter
    default = {"fixed": "Local Disk", "removable": "USB Drive", "network": "Network Drive",
               "cdrom": "CD Drive", "ram": "RAM Disk"}.get(info.get("kind"), "Local Disk")
    return f"{info.get('label') or default} ({letter})"


def crumbs(path, flavor=None):
    """The breadcrumb trail of ``path`` as ``[(label, path), ...]``, from the drive or root down.

        crumbs("C:\\\\Users\\\\me", ntpath)  ->  [("Local Disk (C:)", "C:\\\\"), ("Users", "C:\\\\Users"), ("me", "C:\\\\Users\\\\me")]
        crumbs("/home/me")               ->  [("/", "/"), ("home", "/home"), ("me", "/home/me")]
    """
    if not path:
        return []
    f = _flavor(path, flavor)
    norm = f.normpath(path)
    drive, rest = f.splitdrive(norm)
    out = []
    if f is ntpath:
        root = drive + "\\"
        info = _drive_info_cache.get(f.normcase(root)) if WINDOWS else None
        out.append((_drive_label(drive, info) if drive else "\\", root if drive else "\\"))
    else:
        root = "/"
        out.append(("/", "/"))
    cur = root
    for part in [p for p in re.split(r"[\\/]+", rest) if p]:
        cur = f.join(cur, part)
        out.append((part, cur))
    return out


def file_url(path):
    """A URL a window can load ``path`` from (images, videos…), in any run mode.

    In the native macOS window this is a ``file://`` URL; in the server-backed window it
    is a private, token-protected address of the app's own server."""
    from .state import _runtime
    app = _runtime.get("app")
    if app is not None and app.window is None and app.token:
        return "/_pg/file?p=" + quote(str(path), safe="")
    return Path(path).resolve().as_uri()


# =============================================================================
# Listings
# =============================================================================
_cache = OrderedDict()   # (normcased path, hidden) -> (mtime_ns, entries)
_cache_lock = threading.Lock()
_CACHE_SIZE = 64


def invalidate(path=None):
    """Forget the cached listing of ``path`` (every listing if None)."""
    with _cache_lock:
        if path is None:
            _cache.clear()
        else:
            norm = os.path.normcase(os.path.normpath(path))
            for k in [k for k in _cache if k[0] == norm]:
                del _cache[k]


_NATURAL = re.compile(r"(\d+)")


def natural_key(name):
    """Sort "file2" before "file10", case-insensitively, as Explorer and Finder do."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in _NATURAL.split(name.casefold()) if t]


def sort_entries(entries, by="name", reverse=False, folders_first=True):
    """Sort in place by ``name``, ``size``, ``modified`` or ``kind``, folders first."""
    if by == "size":
        key = lambda e: (e.size, natural_key(e.name))  # noqa: E731
    elif by == "modified":
        key = lambda e: (e.modified, natural_key(e.name))  # noqa: E731
    elif by == "kind":
        key = lambda e: (e.kind, e.ext, natural_key(e.name))  # noqa: E731
    else:
        key = lambda e: natural_key(e.name)  # noqa: E731
    entries.sort(key=key, reverse=reverse)
    if folders_first:
        entries.sort(key=lambda e: not e.is_dir)  # stable: keeps the order within each group
    return entries


def _scan(path, hidden):
    out = []
    with os.scandir(path) as it:
        for e in it:
            try:
                # On Windows, DirEntry.stat() comes free with the directory listing.
                st = e.stat()
                is_dir = _stat.S_ISDIR(st.st_mode)
                link = e.is_symlink()
            except OSError:
                try:  # a dangling link or a file we cannot stat: still list it
                    st, is_dir, link = None, False, e.is_symlink()
                except OSError:
                    continue
            hide = is_hidden(e.name, st)
            if hide and not hidden:
                continue
            out.append(Entry(e.name, e.path, is_dir, 0 if is_dir or st is None else st.st_size,
                             st.st_mtime if st is not None else 0.0, hide, link))
    return out


def listdir(path, *, hidden=False, sort="name", reverse=False, folders_first=True, cache=True):
    """The entries of folder ``path`` as :class:`Entry` objects, sorted (folders first).

    Raises ``OSError`` (``PermissionError``, ``FileNotFoundError``…) like ``os.scandir``.
    The listing, and each order it was sorted in, is cached until the folder's modification
    time changes, so showing the same folder again costs one ``stat``. The result is a new
    list each time: callers may filter or re-sort it.
    """
    if path == COMPUTER:
        return [Entry(d["name"], d["path"], True) for d in drives()]
    if not cache:
        return sort_entries(_scan(path, hidden), sort, reverse, folders_first)
    key = (os.path.normcase(os.path.normpath(path)), bool(hidden))
    mtime = os.stat(path).st_mtime_ns
    order = (sort, bool(reverse), bool(folders_first))
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] == mtime:
            _cache.move_to_end(key)
            done = hit[2].get(order)
            if done is not None:
                return list(done)
            entries = list(hit[1])
        else:
            hit = entries = None
    if entries is None:
        entries = _scan(path, hidden)
        hit = (mtime, tuple(entries), {})
    sort_entries(entries, sort, reverse, folders_first)
    hit[2][order] = tuple(entries)
    with _cache_lock:
        _cache[key] = hit
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return entries


def is_cached(path, hidden=False):
    """True if :func:`listdir` would answer ``path`` from its cache (no folder scan)."""
    if path == COMPUTER:
        return True
    key = (os.path.normcase(os.path.normpath(path)), bool(hidden))
    with _cache_lock:
        hit = _cache.get(key)
    if hit is None:
        return False
    try:
        return os.stat(path).st_mtime_ns == hit[0]
    except OSError:
        return False


# =============================================================================
# Drives and volumes
# =============================================================================
_drive_info_cache = {}


def _usage(path):
    try:
        u = shutil.disk_usage(path)
        return u.total, u.free
    except OSError:
        return None, None


def _windows_drives():
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    # never pop up "There is no disk in the drive" while probing an empty card reader
    old = k32.SetErrorMode(0x0001 | 0x8000)  # SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX
    try:
        mask = k32.GetLogicalDrives()
        out = []
        types = {2: "removable", 3: "fixed", 4: "network", 5: "cdrom", 6: "ram"}
        for i in range(26):
            if not mask & (1 << i):
                continue
            root = f"{chr(65 + i)}:\\"
            kind = types.get(k32.GetDriveTypeW(ctypes.c_wchar_p(root)), "fixed")
            label = None
            if kind != "network":  # a disconnected share can block for seconds
                buf = ctypes.create_unicode_buffer(261)
                fs_buf = ctypes.create_unicode_buffer(261)
                serial, maxlen, flags = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
                if k32.GetVolumeInformationW(ctypes.c_wchar_p(root), buf, 261, ctypes.byref(serial),
                                             ctypes.byref(maxlen), ctypes.byref(flags), fs_buf, 261):
                    label = buf.value or None
                elif kind in ("removable", "cdrom"):
                    label = None  # no medium inserted
            total, free = _usage(root) if kind != "network" else (None, None)
            info = {"label": label, "kind": kind}
            _drive_info_cache[ntpath.normcase(root)] = info
            out.append({"name": _drive_label(root[:2], info), "path": root, "kind": kind, "label": label,
                        "total": total, "free": free})
        return out
    finally:
        k32.SetErrorMode(old)


def _unix_volumes():
    out = []
    total, free = _usage("/")
    if SYSTEM == "Darwin":
        out.append({"name": "Macintosh HD", "path": "/", "kind": "fixed", "label": None, "total": total, "free": free})
        bases = ["/Volumes"]
    else:
        out.append({"name": "File System", "path": "/", "kind": "fixed", "label": None, "total": total, "free": free})
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        bases = [f"/media/{user}", f"/run/media/{user}", "/mnt", "/media"]
    seen = {os.path.realpath("/")}
    for base in bases:
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            p = os.path.join(base, name)
            real = os.path.realpath(p)
            if real in seen or not os.path.isdir(p) or not os.path.ismount(p):
                continue
            seen.add(real)
            t, f = _usage(p)
            out.append({"name": name, "path": p, "kind": "removable", "label": name, "total": t, "free": f})
    return out


_drives_cache = [0.0, None]


def drives(max_age=3.0):
    """Drives (Windows) or the root and mounted volumes (macOS, Linux), with their usage.

    Each is a dict: ``name`` ("Local Disk (C:)"), ``path``, ``kind`` (fixed, removable,
    network, cdrom), ``label``, ``total`` and ``free`` bytes (None when unknown). The answer
    is reused for ``max_age`` seconds, so a window can show it on every render."""
    now = time.monotonic()
    if _drives_cache[1] is not None and now - _drives_cache[0] < max_age:
        return [dict(d) for d in _drives_cache[1]]
    try:
        found = _windows_drives() if WINDOWS else _unix_volumes()
    except (OSError, AttributeError, ValueError):
        found = [{"name": "Root", "path": os.path.abspath(os.sep), "kind": "fixed", "label": None,
                  "total": None, "free": None}]
    _drives_cache[:] = [now, found]
    return [dict(d) for d in found]


# =============================================================================
# Known folders
# =============================================================================
_KNOWN = [  # name, icon, Windows KNOWNFOLDERID, XDG key
    ("Desktop", "monitor", "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "DESKTOP"),
    ("Documents", "file-text", "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", "DOCUMENTS"),
    ("Downloads", "download", "{374DE290-123F-4565-9164-39C4925E467B}", "DOWNLOAD"),
    ("Pictures", "image", "{33E28130-4E1E-4676-835A-98395C3BC3BB}", "PICTURES"),
    ("Music", "music", "{4BD8D571-6D19-48D3-BE97-422220080E43}", "MUSIC"),
    ("Videos", "video", "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", "VIDEOS"),
]


def _windows_known_folder(guid):
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8)]

    g = GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(guid), ctypes.byref(g))
    out = ctypes.c_wchar_p()
    ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out))
    try:
        return out.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def _xdg_dirs():
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "user-dirs.dirs"
    out = {}
    try:
        for line in cfg.read_text("utf-8").splitlines():
            m = re.match(r'\s*XDG_(\w+)_DIR\s*=\s*"(.*)"', line)
            if m:
                out[m.group(1)] = m.group(2).replace("$HOME", str(Path.home()))
    except OSError:
        pass
    return out


_places_cache = []


def places():
    """The user's folders: Home, Desktop, Documents, Downloads, Pictures, Music, Videos.

    Only folders that exist are returned, each as ``{"name", "path", "icon"}``. On Windows
    they come from the shell (so redirected folders, e.g. to OneDrive, are right); on Linux
    from ``~/.config/user-dirs.dirs``."""
    if _places_cache:
        return [dict(p) for p in _places_cache]
    home_dir = home()
    out = [{"name": "Home", "path": home_dir, "icon": "home"}]
    xdg = _xdg_dirs() if not WINDOWS and SYSTEM != "Darwin" else {}
    for name, icon, guid, xdg_key in _KNOWN:
        path = None
        if WINDOWS:
            try:
                path = _windows_known_folder(guid)
            except (OSError, AttributeError, ValueError):
                path = None
        elif xdg_key in xdg:
            path = xdg[xdg_key]
            if os.path.normpath(path) == os.path.normpath(home_dir):
                continue  # XDG says "not set" by pointing at $HOME
        path = path or os.path.join(home_dir, name)
        if os.path.isdir(path):
            out.append({"name": name, "path": path, "icon": icon})
    _places_cache[:] = out
    return [dict(p) for p in out]


# =============================================================================
# Operations
# =============================================================================
def unique_name(folder, name):
    """``name``, or "name (2)", "name (3)"… if ``folder`` already has it."""
    if not os.path.exists(os.path.join(folder, name)):
        return name
    stem, dot, ext = name.rpartition(".") if "." in name.lstrip(".") else (name, "", "")
    i = 2
    while True:
        candidate = f"{stem} ({i}){dot}{ext}"
        if not os.path.exists(os.path.join(folder, candidate)):
            return candidate
        i += 1


_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def check_name(name):
    """None if ``name`` is a valid file name on every system, else why not."""
    name = (name or "").strip()
    if not name or name in (".", ".."):
        return "Enter a name"
    if _BAD_NAME.search(name):
        return 'A name cannot contain any of  \\ / : * ? " < > |'
    if name.split(".")[0].upper() in _RESERVED:
        return f"{name} is a reserved name on Windows"
    if name.endswith((" ", ".")):
        return "A name cannot end with a space or a dot"
    return None


def make_folder(folder, name="New folder"):
    """Create a sub-folder (renamed "New folder (2)"… if taken) and return its path."""
    path = os.path.join(folder, unique_name(folder, name))
    os.mkdir(path)
    invalidate(folder)
    return path


def rename(path, new_name):
    """Rename a file or folder in place; returns the new path."""
    problem = check_name(new_name)
    if problem:
        raise ValueError(problem)
    folder = os.path.dirname(path)
    target = os.path.join(folder, new_name.strip())
    if os.path.exists(target) and os.path.normcase(target) != os.path.normcase(path):
        raise FileExistsError(f"{new_name} already exists")
    os.rename(path, target)
    invalidate(folder)
    return target


def _windows_recycle(paths):
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = "\0".join(os.path.abspath(p) for p in paths) + "\0\0"  # double-null-terminated list
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc or op.fAnyOperationsAborted:
        raise OSError(f"could not move to the Recycle Bin (error {rc:#x})")


def _freedesktop_trash(path):
    """The freedesktop.org trash (what GNOME Files, Dolphin and others use)."""
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    trash_dir = data / "Trash"
    files, info = trash_dir / "files", trash_dir / "info"
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    if os.stat(path).st_dev != os.stat(files).st_dev:
        gio = shutil.which("gio")
        if gio and subprocess.run([gio, "trash", path], capture_output=True).returncode == 0:
            return
        raise OSError("this file is on another volume, which has no trash")
    name = unique_name(str(files), os.path.basename(path.rstrip(os.sep)))
    (info / f"{name}.trashinfo").write_text(
        f"[Trash Info]\nPath={quote(os.path.abspath(path))}\nDeletionDate={datetime.now():%Y-%m-%dT%H:%M:%S}\n",
        "utf-8")
    os.rename(path, files / name)


def trash(*paths):
    """Move files or folders to the Recycle Bin (Windows) or the Trash (macOS, Linux).

    Never deletes permanently: raises ``OSError`` if the system has no trash for a path."""
    paths = [os.path.abspath(p) for p in paths]
    if not paths:
        return
    if WINDOWS:
        _windows_recycle(paths)
    elif SYSTEM == "Darwin":
        items = ", ".join('POSIX file "' + p.replace("\\", "\\\\").replace('"', '\\"') + '"' for p in paths)
        r = subprocess.run(["osascript", "-e", f'tell application "Finder" to delete {{{items}}}'],
                           capture_output=True, text=True)
        if r.returncode:
            raise OSError(r.stderr.strip() or "could not move to the Trash")
    else:
        for p in paths:
            _freedesktop_trash(p)
    for p in paths:
        invalidate(os.path.dirname(p))

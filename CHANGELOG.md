# Changelog

All notable changes to ZePyGUI are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/).

## [0.2.0] - unreleased

### Added
- **File browsing.** `ui.file_browser`: an Explorer/Finder-like browser with Quick access, drives with
  usage bars, a breadcrumb address bar you can type into, back/forward/up/refresh, search with
  wildcards, details and icon views with image thumbnails, sorting, multi-selection, keyboard
  navigation and type-ahead, and (with `manage=True`) New folder, Rename and Delete to the
  Recycle Bin/Trash.
- `ui.file_dialog`: an in-app open / save / folder dialog that looks the same on every OS.
- `ui.file_icon`: coloured two-tone icons for folders (with marks for Desktop, Documents…),
  drives and 14 file kinds; `ui.breadcrumbs`.
- `zepygui.fs`: drives (`GetLogicalDrives` on Windows), known folders (`SHGetKnownFolderPath`, XDG),
  cached natural-order listings, Windows hidden/system attributes, `trash()` (Recycle Bin,
  Finder, freedesktop Trash), name checks valid on every OS, `file_url()` for showing local files.
- 30 new icons: folder-open, folder-plus, hard-drive, usb, disc, server, monitor, laptop, music,
  video, archive, file-text, file-code, table, database, eye-off, clipboard, scissors, pin…
- `app.run(mode="server")` and the `ZEPYGUI_MODE` / `ZEPYGUI_PORT` environment variables.
- `examples/explorer.py`, `tools/screenshots.mjs` and `tools/demo_home.py`, screenshots in the README.
- Benchmarks for re-rendering after a keystroke and for the file browser.
- Continuous integration on Linux, macOS and Windows, Python 3.9 to 3.13.

### Changed
- **Incremental renders.** After the first render, a window receives a patch: unchanged subtrees
  are sent as the index of the node it already has. A keystroke above a 5,000-row table now sends
  0.6 KB instead of 0.9 MB. A window that cannot apply a patch asks for a full tree.
- **Windows dialogs** (`open_file`, `save_file`, `choose_folder`) call `comdlg32`/`shell32`
  through `ctypes`: they open at once, owned by the app window. PowerShell is only a fallback.
- Mouse events carry the modifier keys; scroll events carry the element's size; an event on a list
  carries the `data-pg-item` of the row it happened on (event delegation).

## [0.1.0] - 2026-10

First release: native macOS window, Edge/Chromium app window on Windows and Linux, reactive
state, 50+ components, charts, background tasks, log console, virtual tables, validation.

[0.2.0]: https://github.com/rzafiamy/zepygui/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/rzafiamy/zepygui/releases/tag/v0.1.0

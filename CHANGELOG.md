# Changelog

All notable changes to ZePyGUI are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

### Security
- The launch token in the window's URL now works **once** (outside `server` mode) and is no longer the
  session secret: the cookie holds a separate one. A URL seen in the process list or the browser's
  history can no longer open the app.
- The app window is started on a launch file in its private profile folder (`0600`), so the token
  never appears on the browser's command line.
- A loopback server refuses a `Host` other than its own address and port (DNS rebinding), and any
  WebSocket or POST whose `Origin` is not the app. `App(allowed_hosts=...)` or `ZEPYGUI_ALLOWED_HOSTS`
  adds names, for a reverse proxy.
- ZePyGUI's page carries a strict Content-Security-Policy: scripts need a per-response nonce, so markup
  injected through `ui.html` can no longer run inline handlers or `javascript:` URLs. Scripts added with
  `head=` / `app.add_head` get the nonce automatically. `App(csp=...)` replaces the policy, `csp=False`
  turns it off.
- Every response carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: SAMEORIGIN`, `Cross-Origin-Opener-Policy` / `Cross-Origin-Resource-Policy:
  same-origin` and a Permissions-Policy that turns camera, microphone, location... off
  (`App(permissions_policy=...)` to change it).

### Changed
- `ui.run_js` runs its code as a nonce'd script instead of `new Function`, so the page needs no
  `unsafe-eval`. The code still runs as a function body (`return` works).
- A valid launch token answers with a page that forwards to the URL without it, instead of a 302.
- Inline event handlers (`onclick="..."`) in `ui.html` markup no longer run: bind events with
  components instead, or pass `csp=False`.

## [0.3.0] - 2026-11-18

### Added
- `ui.code_editor`: a code editor with syntax highlighting for YAML, INI, JSON, TOML, Python and shell,
  line numbers, problem markers in the gutter (error / warning / info, with their messages), a status
  bar, Tab / Shift+Tab indentation, auto-indent, Ctrl+/ comments, `on_save` for Ctrl+S / Cmd+S and
  `goto` to move the caret to a line. Two-way binds a `State` like `ui.input`.
- `ui.dropdown`: a "⋯" (or labelled) button opening a menu of actions with icons, hints, separators,
  disabled and danger items. It closes on a choice, a click outside or Escape, moves with the arrow keys,
  never clicks the table row it sits in, and is positioned so that no scrolling parent or lifted card
  clips or shifts it.
- `donut(..., colors=...)` takes a list or a `{label: colour}` dict.
- The log console tints success lines (`SUCCESS`, `PASSED`, `✔`) green and section lines (`▶`, `━━`) bold.

### Fixed
- The legend of `line_chart` now uses the `colors` passed to the chart.

## [0.2.0] - 2026-11-05

### Added
- `app.http(prefix, fn)` answers GET and POST under a prefix, behind the window's token, and
  `app.index(fn)` replaces the UI root with the app's own page: an app can bring its own front end.
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

[0.3.0]: https://github.com/rzafiamy/zepygui/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/rzafiamy/zepygui/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rzafiamy/zepygui/releases/tag/v0.1.0

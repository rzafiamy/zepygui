# PyGUI — Specification

Version of record: `0.1.0` (see `pyproject.toml`, `pygui/__init__.py`).

## 1. Purpose and scope

PyGUI is a framework for building desktop applications in Python, with no
dependency outside the standard library. An application declares pages as
Python functions returning a tree of components; PyGUI renders that tree in a
native window that hosts the operating system's web engine, and keeps it in
sync with reactive state. This document lists what the framework does (§4)
and states each behaviour as an atomic requirement (§5).

**Scope.** The `pygui` package (runtime, component library, design system,
client runtime, window backends, desktop helpers, developer tools), the
examples under `examples/`, and the tests under `tests/`.
Out of scope: applications built with PyGUI, and the third-party engines it
drives (WebKit, Chromium).

### 1.1 Architecture at a glance

```
 page function ──► Element tree ──► Renderer ──► JSON tree ──► client.js ──► DOM
      ▲                                                            │
      └──── Session worker thread ◄──── events / navigation ◄──────┘
```

- **Session** — one per window. A dedicated worker thread processes that
  window's events in order, then renders once when its queue is empty.
- **Renderer** — walks the element tree, expands `@component` calls with their
  hook state, registers event handlers under stable path ids, and produces a
  JSON tree.
- **Client runtime** (`static/client.js`) — patches the DOM against the
  received tree, reusing nodes by tag and key, and sends DOM events back.
- **Transports** — on macOS, an in-process WebKit script-message bridge
  (`macos.py`, no socket). Elsewhere, a loopback WebSocket protected by a
  launch token (`server.py`), shown in a Chromium app window (`window.py`).

## 2. How to read the requirements

Each requirement is **atomic**: one verifiable statement, one behaviour. They
are written to be testable — a reader must be able to say "pass" or "fail"
without interpreting intent.

- `MUST` — mandatory; a violation is a defect.
- `MUST NOT` — prohibited.
- `SHOULD` — strong default, deviation needs a recorded reason.

Identifiers are stable: `REQ-<AREA>-<NNN>`. **Never renumber.** A retired
requirement keeps its id and is marked `WITHDRAWN`.

A requirement marked **[T]** is covered by an automated test. One marked **[M]**
is verified by a procedure in [manual.md](manual.md) — it needs a person,
a second operating system, a system dialog or a judgement of how something
looks.

These markers are a convenience copy. **[matrix.md](matrix.md) is
authoritative**: it is generated from the tests themselves by
`python3 tests/matrix.py`, which fails if any requirement here has no test, or
if a marker disagrees with the coverage found. A requirement added to this
file without a test breaks that command — which is the point.

Automated tests come in two kinds. **Unit/integration** tests run headless
everywhere (`python3 -m unittest discover -s tests`). **GUI** tests open a
real native window and run only on macOS when `PYGUI_GUI_TESTS=1` is set;
the matrix labels them `auto (gui)`.

## 3. Definitions

| Term | Meaning |
|---|---|
| **App** | The `App` object: routes, layout, timers, exposed functions, theme and window settings. |
| **Window** | One displayed instance of the UI: the native macOS window, or one Chromium app window / browser tab. |
| **Session** | The server-side state of one window: current path, query, theme, hook states, event handlers and a worker thread. |
| **Page** | A function registered with `@app.page(path)`, returning the content for that path. |
| **Layout** | A function registered with `@app.layout`, receiving a page's content and returning the shell around it. |
| **Element** | A node of the UI tree: tag, attributes, events, children, optional key. |
| **Component** | A function decorated with `@ui.component`; rendered lazily, with its own hook state. |
| **State** | A reactive value (`pygui.State`). Reading it during a render subscribes the window; setting it re-renders subscribers. |
| **Hook** | A per-window `State` obtained with `ui.use_state` inside a page or component, identified by its position in the tree. |
| **Render** | Building the JSON tree of a window and sending it to the client. |
| **Handler** | A Python callable attached to an element event (`on_click=…`). |
| **Event spec** | What the client receives for one handler: handler id plus options (`keys`, `debounce`, `prevent`, `stop`, `self`). |
| **Sequence number / ack** | The client numbers each event; a render carries the highest number Python has processed (`ack`). |
| **Backend** | How a window is shown: `native` (macOS WKWebView), `window` (Chromium app window) or `browser`. |
| **Bridge** | The native transport: WebKit script messages (JS → Python) and `evaluateJavaScript` (Python → JS). |
| **Launch token** | A random secret in the URL that opens a server-backed window, exchanged for a cookie. |

## 4. Feature inventory

### 4.1 Core

| # | Feature |
|---|---|
| F-01 | Pages as Python functions, with typed route parameters |
| F-02 | Reactive `State`, shared across windows, thread-safe |
| F-03 | Per-window hook state (`use_state`) and reusable `@component`s |
| F-04 | Two equivalent authoring styles: nested calls and `with` blocks |
| F-05 | Event handlers with automatic arity, async support and background work |
| F-06 | Layout shell wrapping every page |
| F-07 | Error page with traceback instead of a crash |

### 4.2 Component library and design system

| # | Feature |
|---|---|
| F-08 | Layout primitives: column, row, grid, container, card, shell, sidebar, header |
| F-09 | Inputs with two-way binding: input, textarea, checkbox, switch, slider, select, radio group, segmented control, form |
| F-10 | Display: badge, avatar, icon set, progress, spinner, alert, stat tile, sortable table, tabs, accordion, modal, tooltip, empty state |
| F-11 | Charts: line, bar, donut, sparkline — pure SVG/CSS |
| F-12 | Markdown rendering |
| F-13 | Light and dark themes, accent colour and radius tokens, theme toggle |
| F-14 | Toast notifications |

### 4.3 Desktop platform

| # | Feature |
|---|---|
| F-15 | Native macOS window (NSWindow + WKWebView via `ctypes`), menu bar, theme-matched title bar, remembered frame |
| F-16 | Chromium app-window backend for Windows and Linux |
| F-17 | Native file open / save / folder dialogs, system notifications, open files and URLs |
| F-18 | External links open in the default browser |

### 4.4 Developer experience

| # | Feature |
|---|---|
| F-19 | Auto-reload on save (`reload=True`) |
| F-20 | Web inspector (`debug=True`) |
| F-21 | Project scaffolding (`python -m pygui new`) |
| F-22 | JavaScript → Python calls (`@app.expose`) and Python → JavaScript (`ui.run_js`) |
| F-23 | Periodic background timers (`@app.timer`) |

## 5. Atomic requirements

### 5.1 Reactive state (REQ-STA)

- **REQ-STA-001** Setting a `State` to a new value MUST notify every window subscribed to it. **[T]**
- **REQ-STA-002** Setting a `State` to an immutable value equal to its current value MUST NOT notify subscribers. **[T]**
- **REQ-STA-003** Reading `State.value` during a render MUST subscribe the rendering window. **[T]**
- **REQ-STA-004** Reading `State.value` outside a render MUST NOT subscribe anything. **[T]**
- **REQ-STA-005** The list helpers `append`, `extend`, `insert`, `remove`, `pop`, `clear` and item assignment or deletion MUST notify subscribers after mutating. **[T]**
- **REQ-STA-006** `State.notify()` MUST re-render subscribers without changing the value. **[T]**
- **REQ-STA-007** A `State` changed from a thread other than a window's worker MUST re-render the subscribed windows. **[T]**
- **REQ-STA-008** A subscription MUST NOT keep a window's session alive. **[T]**

### 5.2 Element tree (REQ-TRE)

- **REQ-TRE-001** A tree built with nested calls and the same tree built with `with` blocks MUST serialise identically. **[T]**
- **REQ-TRE-002** A keyword `on_<event>` given a callable MUST register a handler for the DOM event `<event>`. **[T]**
- **REQ-TRE-003** Any other keyword MUST become an HTML attribute, with `_` replaced by `-` and one trailing `_` dropped. **[T]**
- **REQ-TRE-004** A numeric style value MUST be emitted in pixels, except for unitless properties and custom properties. **[T]**
- **REQ-TRE-005** A child that is `None`, `True` or `False` MUST render nothing. **[T]**
- **REQ-TRE-006** A `State` used as a child or an attribute MUST render its current value. **[T]**
- **REQ-TRE-007** An element's `key` MUST be sent to the client. **[T]**
- **REQ-TRE-008** A fragment MUST render its children without a wrapper element. **[T]**

### 5.3 Hooks and components (REQ-HOK)

- **REQ-HOK-001** `use_state` MUST return the same `State` for the same page or component position across renders. **[T]**
- **REQ-HOK-002** Two instances of one component MUST keep independent `use_state` values. **[T]**
- **REQ-HOK-003** `use_state` called outside a render MUST raise `RuntimeError`. **[T]**
- **REQ-HOK-004** A callable default given to `use_state` MUST be evaluated only when the hook is created. **[T]**
- **REQ-HOK-005** The hook state of a component no longer rendered MUST be discarded after that render. **[T]**
- **REQ-HOK-006** An element passed as an argument to a component MUST NOT also render where it was created. **[T]**

### 5.4 Rendering (REQ-RND)

- **REQ-RND-001** A render MUST send the complete tree together with the highest event sequence number processed. **[T]**
- **REQ-RND-002** State changes made while handling one event MUST produce a single render. **[T]**
- **REQ-RND-003** A page that raises MUST render an error view containing the traceback, and the window MUST stay usable. **[T]**
- **REQ-RND-004** A path matching no page MUST render the not-found page. **[T]**
- **REQ-RND-005** The window title MUST be `<page title> · <app title>` when the page has a title, and the app title otherwise. **[T]**
- **REQ-RND-006** The client MUST reuse a DOM node whose tag and key match the new tree, and keyed children MUST keep their node when reordered. **[T]**
- **REQ-RND-007** The client MUST NOT overwrite an input's value while that input has an event Python has not yet acknowledged, and MUST apply a value Python changes once it has. **[T]**
- **REQ-RND-008** A newly connected window MUST receive exactly one first render. **[T]**

### 5.5 Events (REQ-EVT)

- **REQ-EVT-001** A handler MUST be called with an argument only if its signature accepts one. **[T]**
- **REQ-EVT-002** Input components MUST pass `on_change` a converted value: text as `str`, a number field as `int`/`float`/`None`, a toggle as `bool`, a slider as a number. **[T]**
- **REQ-EVT-003** A select MUST pass the original option value, with its original type. **[T]**
- **REQ-EVT-004** An exception raised by a handler MUST be shown as an error toast and MUST NOT stop the window from processing later events. **[T]**
- **REQ-EVT-005** An `async` handler MUST run without blocking the window's event queue. **[T]**
- **REQ-EVT-006** A `debounce` delay MUST be sent to the client in the event spec. **[T]**
- **REQ-EVT-007** `on_enter` MUST be sent as a keydown handler filtered to the Enter key. **[T]**
- **REQ-EVT-008** The events of one window MUST be handled in the order they arrive. **[T]**
- **REQ-EVT-009** An event naming a handler absent from the last render MUST be ignored. **[T]**
- **REQ-EVT-010** `ui.form(on_submit=…)` MUST pass a dict of its named fields, with checkboxes as booleans. **[M]**

### 5.6 Routing (REQ-RTE)

- **REQ-RTE-001** A static route MUST match its exact path, with or without one trailing slash, and nothing longer. **[T]**
- **REQ-RTE-002** Route parameters typed `int`, `float` or `path` MUST be converted before the page is called. **[T]**
- **REQ-RTE-003** A page MUST receive only the route parameters its signature accepts. **[T]**
- **REQ-RTE-004** `ui.navigate(path)` MUST send the new path to the client and render the matching page. **[T]**
- **REQ-RTE-005** The query string MUST be available as `session.query`, with repeated keys as lists. **[T]**
- **REQ-RTE-006** A registered layout MUST wrap every page. **[T]**

### 5.7 Components (REQ-CMP)

- **REQ-CMP-001** Every component exported by `pygui.ui` MUST render with minimal arguments. **[T]**
- **REQ-CMP-002** `modal` MUST render nothing while its `State` is false. **[T]**
- **REQ-CMP-003** `tabs` MUST render only the active tab's content. **[T]**
- **REQ-CMP-004** Clicking a sortable table header MUST cycle the rows through ascending, descending and original order. **[T]**
- **REQ-CMP-005** A table column `format` function taking two parameters MUST receive the cell value and its row. **[T]**
- **REQ-CMP-006** `nav_item` MUST mark itself active when the current path equals its target or lies below it. **[T]**
- **REQ-CMP-007** A chart given no data MUST render an empty state. **[T]**
- **REQ-CMP-008** An input bound to a `State` MUST update that `State` on each input event. **[T]**
- **REQ-CMP-009** `theme_toggle` MUST show the icon of the theme it switches to. **[T]**
- **REQ-CMP-010** The copy button of `code_block` MUST copy the block's text to the clipboard. **[M]**

### 5.8 Theming (REQ-THM)

- **REQ-THM-001** `theme="auto"` MUST follow the operating system's appearance at launch. **[M]**
- **REQ-THM-002** `ui.set_theme` MUST send the theme to the window and update `session.theme`. **[T]**
- **REQ-THM-003** The `accent` and `radius` settings MUST be applied as the `--accent` and `--radius` CSS variables. **[T]**
- **REQ-THM-004** A theme chosen by the user MUST persist across launches of the same app. **[M]**

### 5.9 Native macOS window (REQ-WIN)

- **REQ-WIN-001** On macOS, `mode="auto"` MUST show the UI in an NSWindow hosting a WKWebView. **[T]**
- **REQ-WIN-002** The native backend MUST NOT open any network socket. **[T]**
- **REQ-WIN-003** The window MUST provide a menu bar whose Undo, Redo, Cut, Copy, Paste and Select All items work with their standard shortcuts in text fields. **[M]**
- **REQ-WIN-004** Closing the window MUST make `app.run()` return after running the shutdown hooks. **[T]**
- **REQ-WIN-005** The title bar and window background MUST follow the active theme. **[M]**
- **REQ-WIN-006** The window MUST reopen at its last size and position. **[M]**
- **REQ-WIN-007** An external `http`, `https` or `mailto` link MUST open in the default browser, never inside the window. **[M]**
- **REQ-WIN-008** Ctrl+C in the launching terminal MUST quit the app. **[M]**
- **REQ-WIN-009** An `icon` given to `App` MUST be used as the Dock icon. **[M]**
- **REQ-WIN-010** Files mounted with `app.static` MUST load through relative URLs. **[T]**
- **REQ-WIN-011** In-app links MUST navigate without reloading and record the path in the URL hash. **[T]**

### 5.10 Server-backed window (REQ-FBK)

- **REQ-FBK-001** On Windows and Linux, `mode="auto"` MUST open an installed Chromium-based browser in app mode with a private per-app profile. **[M]**
- **REQ-FBK-002** When no Chromium-based browser is found, the app MUST open in the default browser and say so in the terminal. **[M]**
- **REQ-FBK-003** The server MUST bind to `127.0.0.1` unless told otherwise. **[T]**
- **REQ-FBK-004** In `window` mode the app MUST shut down about three seconds after its last window disconnects. **[M]**
- **REQ-FBK-005** A window reconnecting with the same session id MUST resume its session, hook state included. **[T]**
- **REQ-FBK-006** A window that reconnects to a restarted app MUST reload itself. **[M]**

### 5.11 Security (REQ-SEC)

- **REQ-SEC-001** A server-backed window MUST require the launch token or its cookie for every page and for the WebSocket; only `/_pg/` assets MAY be served without it. **[T]**
- **REQ-SEC-002** A request carrying a valid token MUST receive an `HttpOnly`, `SameSite=Strict` cookie scoped to the port and a redirect to the same URL without the token. **[T]**
- **REQ-SEC-003** Static file serving MUST refuse any path resolving outside its directory. **[T]**
- **REQ-SEC-004** Markdown MUST escape raw HTML and neutralise `javascript:`, `vbscript:` and `data:` URLs. **[T]**
- **REQ-SEC-005** Text children MUST be inserted as text nodes, never parsed as HTML. **[M]**
- **REQ-SEC-006** A WebSocket message larger than 32 MiB MUST close the connection. **[T]**
- **REQ-SEC-007** A request from the UI to open a URL MUST be honoured only for `http`, `https` and `mailto` URLs. **[T]**

### 5.12 Desktop integration (REQ-DSK)

- **REQ-DSK-001** `open_file`, `save_file` and `choose_folder` MUST show the system dialog and return `None` when it is cancelled. **[M]**
- **REQ-DSK-002** Text passed to AppleScript MUST have its quotes and backslashes escaped. **[T]**
- **REQ-DSK-003** Text passed to PowerShell MUST have its single quotes escaped. **[T]**
- **REQ-DSK-004** `notify` MUST show a system notification on macOS. **[M]**
- **REQ-DSK-005** `open_path(path, reveal=True)` MUST select the file in Finder or Explorer. **[M]**

### 5.13 Developer tools (REQ-DEV)

- **REQ-DEV-001** `app.run(reload=True)` MUST restart the app when a watched source file changes. **[M]**
- **REQ-DEV-002** The reload watcher MUST ignore hidden, `__pycache__`, virtual-environment and `node_modules` directories, and files other than source and style files. **[T]**
- **REQ-DEV-003** `app.run(debug=True)` MUST enable the web inspector. **[M]**
- **REQ-DEV-004** `python -m pygui new <dir>` MUST create a valid `app.py` and MUST refuse to overwrite an existing one. **[T]**
- **REQ-DEV-005** The examples MUST run with `python3 examples/<name>.py` without installing the package. **[M]**
- **REQ-DEV-006** A function registered with `@app.expose` MUST be callable from JavaScript and return its result, or its error. **[T]**
- **REQ-DEV-007** A function registered with `@app.timer` MUST run periodically while the app runs, and stop when it ends. **[T]**

### 5.14 Packaging (REQ-PKG)

- **REQ-PKG-001** The package MUST import only the Python standard library. **[T]**
- **REQ-PKG-002** The package MUST run on Python 3.9 and later. **[M]**
- **REQ-PKG-003** The client runtime and stylesheet MUST be shipped as package data. **[T]**

## 6. Traceability

Full matrix: [matrix.md](matrix.md), generated by `python3 tests/matrix.py`.
Coverage is claimed where the test lives — a `covers:` line in a test's
docstring, or a row of `manual.md` — so it cannot drift out of sync the way a
hand-kept table does.

| Area | Primary source | Tests |
|---|---|---|
| REQ-STA | `pygui/state.py` | `tests/test_state.py` |
| REQ-TRE, REQ-HOK, REQ-CMP | `pygui/ui.py`, `pygui/app.py` (`Renderer`) | `tests/test_tree.py` |
| REQ-RND | `pygui/app.py` (`Session`, `Renderer`), `pygui/static/client.js` | `tests/test_runtime.py`, `tests/test_native.py` |
| REQ-EVT, REQ-RTE, REQ-THM | `pygui/app.py`, `pygui/ui.py` | `tests/test_runtime.py` |
| REQ-WIN | `pygui/macos.py`, `pygui/static/client.js` | `tests/test_native.py` (GUI, opt-in) |
| REQ-FBK, REQ-SEC | `pygui/server.py`, `pygui/window.py`, `pygui/app.py` | `tests/test_platform.py` |
| REQ-DSK | `pygui/desktop.py` | `tests/test_platform.py` |
| REQ-DEV | `pygui/reloader.py`, `pygui/__main__.py`, `pygui/app.py` | `tests/test_platform.py`, `tests/test_runtime.py` |
| REQ-PKG | `pyproject.toml`, `pygui/` | `tests/test_platform.py` |

## 7. Known gaps

These are stated rather than hidden; each is a candidate requirement, not a
current one.

1. **No native backend for Windows or Linux.** Both use a Chromium app window
   over a loopback socket (§5.10). WebView2 (Windows) and WebKitGTK (Linux)
   backends through `ctypes` would remove the browser requirement and the
   socket.
2. **The Windows and Linux paths have never been run on those systems.** The
   server-backed window is tested on macOS with Chrome; the browser discovery
   paths, the PowerShell dialogs and `zenity`/`kdialog` are unverified (see
   the platform rows of `manual.md`).
3. **One window per app on macOS.** The native backend creates a single window
   and a single session; there is no API to open a second window.
4. **No application packaging.** Nothing produces a signed `.app`, `.exe` or
   Linux bundle; the Dock shows "Python" for an unbundled script.
5. **Dialogs run in another process.** File dialogs use `osascript`,
   PowerShell or `zenity`, so they are not sheets attached to the window and
   can open behind it.
6. **Hooks are positional.** Hook state is keyed by tree position; inserting
   an unkeyed sibling before a component shifts its state. Keys avoid it, but
   nothing warns.
7. **No accessibility audit.** Components carry some ARIA roles; keyboard
   navigation and screen-reader output have not been reviewed.
8. **Python 3.9 is the only version exercised** (REQ-PKG-002); 3.10–3.13 are
   expected to work but no run is on record.

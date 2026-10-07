# PyGUI

**Beautiful native desktop apps in pure Python. Zero dependencies.**

PyGUI works like Tauri, but you write Python instead of Rust and JavaScript. Your app runs in
a real native window using the operating system's web engine, comes with a polished design system,
and updates itself when your data changes.

```python
from pygui import App, State, ui

app = App("Hello")
count = State(0)

@app.page("/")
def home():
    return ui.column(
        ui.h1(f"Clicked {count.value} times"),
        ui.button("Click me", lambda: count.set(count.value + 1)),
    )

app.run()
```

```bash
python hello.py
```

No `pip install`, no Node, no Rust toolchain. You only need Python 3.9+.

---

## Why PyGUI

| | |
|---|---|
| **Native window** | On macOS, a real `NSWindow` + `WKWebView` (the same approach Tauri takes), driven via `ctypes`. Native menu bar, copy/paste, full screen, the title bar follows your theme, and the window remembers its size and position. |
| **No dependencies** | Only the standard library. Nothing to install, nothing to break. |
| **Beautiful by default** | 50+ components: buttons, inputs, tables, tabs, modals, toasts, charts, sidebar layouts. Dark and light themes, smooth animations. |
| **Reactive** | Change a `State` and every window that shows it re-renders automatically, even from background threads. |
| **Simple** | Your UI is just Python functions that return components. |
| **Desktop APIs** | Native open/save/folder dialogs, system notifications, open files/URLs. |
| **Dev friendly** | `app.run(reload=True)` restarts the app on save; `debug=True` enables the web inspector. |

### How it works

```
 Your Python code ──► builds a tree of components ──► sent to the window over an in-process bridge
        ▲                                                       │
        └──────────── events (click, input, …) ◄────────────────┘
```

* **macOS**: native `NSWindow` + `WKWebView`. No server and no network port: Python and the UI talk
  through a WebKit script-message bridge.
* **Windows / Linux**: a frameless app window using the system's Edge/Chromium (Edge ships with
  Windows), talking to Python over a private, token-protected loopback channel. It's the same API, and
  native WebView2/WebKitGTK backends can be added without changing any app code.

---

## Quick start

Make `pygui` importable from anywhere (one time, from this folder):

```bash
python3 -m pip install -e .
```

Then create and run an app:

```bash
python3 -m pygui new myapp     # creates myapp/app.py (with a sidebar, pages, theme toggle)
python3 myapp/app.py
```

(Without installing, put your app next to the `pygui/` folder, or run the examples below, which find it on their own.)

Or run the examples:

```bash
python examples/hello.py       # counter
python examples/todo.py        # to-do list
python examples/dashboard.py   # full app: sidebar, live charts, table, modal, settings, file dialogs
```

---

## The basics

### Pages

```python
@app.page("/", title="Home")
def home():
    return ui.h1("Home")

@app.page("/user/{id:int}", title="Profile")   # parameters: {name}, {name:int}, {name:float}, {name:path}
def profile(id):
    return ui.h1(f"User #{id}")
```

Navigate with `ui.link("Profile", to="/user/3")`, `ui.nav_item(...)`, or `ui.navigate("/user/3")`.

### State: the UI updates itself

```python
count = State(0)           # shared by all windows of the app

count.value                # read (inside a page, this subscribes the window)
count.set(5)               # write → UI re-renders
count.value += 1           # also works
count.update(lambda n: n * 2)

todos = State([])
todos.append("Write docs")  # list helpers: append, remove, pop, insert, clear, extend
todos.value[0] = "Edited"
todos.notify()              # after mutating in place yourself
```

**Local state** for one page or component uses `ui.use_state`:

```python
@app.page("/search")
def search():
    query = ui.use_state("")
    return ui.input(query, placeholder="Search…")    # a State as `value` means two-way binding
```

### Two ways to write layouts

Nested calls:

```python
ui.card(
    ui.h3("Sign in"),
    ui.input(email, label="Email"),
    ui.button("Continue", login, full=True),
)
```

…or `with` blocks:

```python
with ui.card():
    ui.h3("Sign in")
    ui.input(email, label="Email")
    ui.button("Continue", login, full=True)
```

### Reusable components

```python
@ui.component
def Counter(label):
    n = ui.use_state(0)                       # each Counter keeps its own count
    return ui.button(f"{label}: {n.value}", lambda: n.set(n.value + 1))

ui.row(Counter("Apples"), Counter("Pears"))
```

In lists, give items a `key=` so their state follows them when the list is reordered.

### Event handlers

Handlers can take zero or one argument; PyGUI passes the argument only if your function accepts it.

```python
ui.button("Save", on_click=save)                       # save()
ui.input(on_change=lambda text: print(text))           # gets the text
ui.input(on_enter=lambda text: send(text))
ui.select(["S", "M", "L"], on_change=set_size)         # gets the chosen option
ui.el("div", "Hover me", on_mouseenter=lambda e: ...)  # any DOM event, gets an Event

async def load():                                      # async handlers work too
    await asyncio.sleep(1)
    data.set(await fetch())
```

Slow work? Use `ui.background(fn, *args)` so the window stays responsive.

### App shell layout

```python
@app.layout
def layout(content):
    return ui.shell(
        content,
        sidebar=ui.sidebar(
            ui.nav_item("Home", "/", icon="home"),
            ui.nav_item("Inbox", "/inbox", icon="mail", badge=3),
            ui.nav_section("Account"),
            ui.nav_item("Settings", "/settings", icon="settings"),
            title="Acme", logo="zap",
        ),
        header=ui.header(ui.spacer(), ui.theme_toggle()),
    )
```

---

## Components

**Layout:** `column`, `row`, `grid`, `container`, `card`, `spacer`, `divider`, `scroll_area`,
`shell`, `sidebar`, `nav_item`, `nav_section`, `header`

**Text:** `h1`–`h4`, `text`, `link`, `code`, `code_block`, `markdown`, `kbd`

**Inputs:** `button`, `icon_button`, `input`, `textarea`, `checkbox`, `switch`, `slider`, `select`,
`radio_group`, `segmented`, `form`

**Display:** `badge`, `avatar`, `icon`, `image`, `progress`, `spinner`, `alert`, `stat`, `table`,
`tabs`, `accordion`, `modal`, `tooltip`, `empty_state`, `theme_toggle`

**Charts:** `line_chart`, `bar_chart`, `donut`, `sparkline`

**Actions:** `toast`, `navigate`, `set_theme`, `toggle_theme`, `set_title`, `copy`, `run_js`, `background`

**Desktop:** `open_file`, `save_file`, `choose_folder`, `notify`, `open_url`, `open_path`

A few examples:

```python
ui.button("Delete", on_click=delete, variant="danger", icon="trash")   # primary/secondary/outline/ghost/soft/danger/success
ui.input(email, label="Email", type="email", icon="mail", error="Invalid email" if bad else None)
ui.switch("Dark mode", dark)
ui.slider(volume, min=0, max=100, label="Volume", format=lambda v: f"{v}%")
ui.grid(ui.stat("Revenue", "$12k", delta="+8%", icon="dollar"), ..., cols=4)

ui.table(users, [
    ("name", "Name"),
    {"key": "role", "label": "Role", "format": lambda v: ui.badge(v, "blue")},
    {"key": "spent", "label": "Spent", "align": "right", "format": lambda v: f"${v:,}"},
], on_row_click=open_user)                                              # sortable by default

ui.tabs({"Profile": profile_tab, "Billing": billing_tab}, variant="pills")
ui.modal(show_dialog, ui.text("Are you sure?"), title="Confirm",
         footer=[ui.button("Cancel", close, variant="ghost"), ui.button("Yes", confirm)])
ui.line_chart({"Sales": [3, 5, 4, 8], "Costs": [2, 3, 3, 4]}, ["Q1", "Q2", "Q3", "Q4"])
ui.donut({"Free": 120, "Pro": 45, "Team": 12}, center_label="users")
```

Every component accepts `cls=`, `style=` and `key=`, and any other keyword becomes an HTML attribute.
Spacing (`gap`, `padding`) uses a 4px scale: `gap=4` is 16px. Strings like `"1.5rem"` pass through.

### Desktop features

```python
path = ui.open_file("Choose an image", types=["png", "jpg"])        # None if cancelled
paths = ui.open_file(multiple=True)
target = ui.save_file("Export", "report.csv")
folder = ui.choose_folder()
ui.notify("Export finished", "report.csv was saved")                # system notification
ui.open_path(target, reveal=True)                                   # show in Finder/Explorer
```

### Background updates

```python
@app.timer(1.0)
def tick():
    clock.set(time.strftime("%H:%M:%S"))     # every open window updates
```

---

## Customizing

```python
app = App(
    "My App",
    theme="auto",            # "auto" (follows the OS), "dark" or "light"
    accent="#10b981",        # one color drives the whole palette
    width=1200, height=800, min_size=(600, 400),
    radius=12,               # corner roundness
    font="'Inter', sans-serif",
    icon="icon.png",         # dock icon (macOS)
)

app.add_css(""".hero { background: linear-gradient(135deg, var(--accent), #ec4899); }""")
app.static("/assets", "assets")       # then ui.image("assets/logo.png")
ui.register_icon("diamond", "M12 2 22 12 12 22 2 12Z")   # SVG paths on a 24x24 grid
```

Theme variables you can use in your CSS: `--accent`, `--bg`, `--surface`, `--surface-2`, `--border`,
`--text`, `--text-2`, `--muted`, `--green`, `--red`, `--yellow`, `--blue`, `--radius`, `--shadow`.

### Escape hatches

```python
ui.el("video", src="intro.mp4", controls=True, autoplay=True)   # any HTML tag
ui.html("<marquee>raw HTML</marquee>")                          # raw markup (trusted content only)
ui.run_js("document.body.requestFullscreen()")

@app.expose                       # call Python from your own JavaScript:
def add(a, b):                    #   const sum = await pygui.call("add", 2, 3)
    return a + b
```

### Run options

```python
app.run()                    # native window (macOS) / app window (Windows, Linux)
app.run(reload=True)         # restart on file save, for development
app.run(debug=True)          # right-click → Inspect Element
app.run(mode="window")       # force the Edge/Chromium app window
app.run(mode="browser")      # open in your default browser (handy for dev tools)
```

---

## Project layout

```
pygui/
  app.py        App, routing, per-window sessions, renderer
  ui.py         component library
  state.py      reactive State
  macos.py      native NSWindow + WKWebView via ctypes
  window.py     Edge/Chromium app-window launcher (Windows/Linux)
  server.py     stdlib HTTP + WebSocket server (fallback transport only)
  desktop.py    file dialogs, notifications, open files/URLs
  reloader.py   restart on save
  static/       client runtime (DOM patching) + design system CSS
examples/       hello.py, todo.py, dashboard.py
tests/          python3 -m unittest discover -s tests   (headless)
                PYGUI_GUI_TESTS=1 python3 -m unittest discover -s tests   (+ real native windows, macOS)
                python3 tests/matrix.py   (rebuild specs/matrix.md; fails on any uncovered requirement)
specs/         specification, traceability matrix, manual test suite
licences/      licence texts of third-party material (see CREDITS.md)
```

## Status

* **macOS**: native backend, tested.
* **Windows / Linux**: use the Edge/Chromium app window. If no Chromium browser is installed, the app
  opens in the default browser. Native WebView2 (Windows) and WebKitGTK (Linux) backends are the next step.
* Packaging into a standalone `.app`/`.exe` is not built in yet; tools such as PyInstaller can bundle
  a PyGUI app because it has no dependencies to collect.

## Specifications

* [`specs/specification.md`](specs/specification.md): what PyGUI does, as atomic, testable requirements
* [`specs/matrix.md`](specs/matrix.md): traceability matrix, generated by `python3 tests/matrix.py`
* [`specs/manual.md`](specs/manual.md): manual test procedures for what automation cannot reach

## License

MIT License, copyright (c) 2026 Rija Z. See [`LICENSE`](LICENSE).
Third-party material: [`CREDITS.md`](CREDITS.md).

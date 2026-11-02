# Manual test suite

The requirements that no automated test reaches, as procedures a person runs.

**Why these are manual.** Four reasons, and it is worth keeping them apart:

1. **It needs another operating system.** The Windows and Linux paths cannot be
   exercised from the macOS development machine.
2. **It needs a system dialog, notification or menu.** These belong to the OS,
   not to the page, and cannot be driven from the window's JavaScript.
3. **It needs a person's judgement** — that a title bar *matches* the theme, that
   a window *reopens* where it was.
4. **It needs a process boundary a test cannot cross cleanly** — a terminal's
   Ctrl+C, a file saved in an editor, a relaunch.

**What is not manual.** Anything the page itself can report is automated:
`tests/test_native.py` opens a real native window, drives it with JavaScript and
reads the DOM back over the bridge (`ZEPYGUI_GUI_TESTS=1`). A procedure belongs here
only when that is not enough.

Run the whole suite before a release; run the affected sections when an area
changes. Record the result in the release checklist — a manual test nobody ran
is not coverage, and this file is the honest place for that to show.

**Environment**, unless a test says otherwise: macOS with Python 3.9+, the
repository checked out, and a terminal in its root. The dashboard example is
`python3 examples/dashboard.py`.

---

## MT — Native macOS window

| Id | Test | Requirements |
|---|---|---|
| MT-001 | Run the dashboard. Open Customers › **Add customer**, type a name in the first field, select it with **⌘A**, cut with **⌘X**, paste it into the email field with **⌘V**, undo with **⌘Z** and redo with **⇧⌘Z**. Copy a table cell's text with **⌘C** and paste it into a field. Confirm every shortcut acts, and that the same items exist in the **Edit** menu. | REQ-WIN-003 |
| MT-002 | Run the dashboard in dark mode, then press the theme toggle in the header. Confirm the window's title bar and the area behind the page switch between dark and light together with the page, with no light strip or flash around the content. | REQ-WIN-005 |
| MT-003 | Run the dashboard, move the window to another position and resize it. Close it with the red button, run it again. Confirm it reopens at the same position and size. | REQ-WIN-006 |
| MT-004 | Add `ui.link("Docs", href="https://example.com")` to the page of `examples/hello.py`, run it and click the link. Confirm the default browser opens the page and the app window still shows the app. Repeat with `new_tab=True` and with a `mailto:` link (Mail opens). | REQ-WIN-007 |
| MT-005 | Run `python3 examples/hello.py` from a terminal, then press **Ctrl+C** in that terminal. Confirm the window closes and the shell prompt returns within a second. | REQ-WIN-008 |
| MT-006 | Copy any PNG next to `examples/hello.py` as `icon.png`, change the app to `App("Hello", icon="icon.png")` and run it. Confirm the Dock shows that image instead of the Python rocket. **Revert afterwards.** | REQ-WIN-009 |

## MT — Theming

| Id | Test | Requirements |
|---|---|---|
| MT-010 | In System Settings › Appearance choose **Light**, run `examples/todo.py` (theme `auto`): confirm a light UI. Quit, choose **Dark**, run it again: confirm a dark UI. Run this before MT-011 and without touching the theme toggle: a theme chosen with the toggle is remembered and overrides `auto`. | REQ-THM-001 |
| MT-011 | Run the dashboard, switch the theme with the header toggle, quit and run it again. Confirm it reopens in the theme you chose, not the system's. | REQ-THM-004 |

## MT — Components

| Id | Test | Requirements |
|---|---|---|
| MT-020 | Add to a page: `ui.form(ui.input(name="email"), ui.checkbox("Agree", name="agree"), ui.button("Send", submit=True), on_submit=print)`. Run it, type `a@b.c`, leave the box unchecked, press **Send**: the terminal prints `{'email': 'a@b.c', 'agree': False}`. Check the box and send again: `'agree': True`. Confirm the page does not reload. | REQ-EVT-010 |
| MT-021 | Add `ui.code_block("print('hi')")` to a page, run it and press the copy icon at the block's top right. Confirm a "Copied to clipboard" toast appears and that pasting into a text editor gives exactly `print('hi')`. | REQ-CMP-010 |
| MT-022 | Add `ui.text("<b>not bold</b> <img src=x onerror=alert(1)>")` to a page and run it. Confirm the text shows literally, with the angle brackets, and no alert or broken image appears. | REQ-SEC-005 |

## MT — Desktop integration

| Id | Test | Requirements |
|---|---|---|
| MT-030 | In the dashboard, open Files › **Open files…**, pick two files: confirm the table lists both with their sizes. Open it again and press **Cancel**: confirm nothing changes and no error toast appears. Do the same with **Choose folder…** (a toast shows the path; Cancel shows nothing). On the Overview page press **Export**, save `report.csv` to the Desktop: confirm the file exists and holds the customer rows; repeat and Cancel: nothing is written. | REQ-DSK-001 |
| MT-031 | On the Overview page press **Export** and save the file. Confirm a macOS notification "Your report has been exported" appears (allow notifications for Script Editor / osascript if macOS asks). | REQ-DSK-004 |
| MT-032 | In the dashboard's Files page, pick a file, then click its row. Confirm Finder opens with that file selected. | REQ-DSK-005 |

## MT — Developer tools

| Id | Test | Requirements |
|---|---|---|
| MT-040 | `python3 -m zepygui new /tmp/mtapp` (with the package installed, or `PYTHONPATH=.`), then `python3 /tmp/mtapp/app.py`. With the window open, change the heading text in `app.py` and save. Confirm the terminal prints a reload notice and the window shows the new heading within about two seconds. Introduce a syntax error and save: the terminal reports it and waits; fix it and save: the app comes back. | REQ-DEV-001 |
| MT-041 | Run the dashboard (it calls `app.run(debug=True)`), right-click anywhere on the page. Confirm **Inspect Element** is offered and opens Web Inspector. Run `examples/hello.py` (no debug): confirm the item is absent. | REQ-DEV-003 |
| MT-042 | From a fresh clone, without installing anything, run `python3 examples/hello.py`, `python3 examples/todo.py` and `python3 examples/dashboard.py`, each from the repository root and once from inside `examples/`. Confirm each opens its window with no `ModuleNotFoundError`. | REQ-DEV-005 |

## MT — Platforms and server-backed window

| Id | Test | Requirements |
|---|---|---|
| MT-050 | **Windows 10/11** with Edge only: run `python examples\dashboard.py`. Confirm a window with no tabs or address bar opens (Edge app mode) and the app works. **Linux** with Chrome or Chromium installed: same check. On both, confirm a profile folder for the app exists (`%LOCALAPPDATA%\zepygui\profiles\northwind`, `~/.cache/zepygui/profiles/northwind`). | REQ-FBK-001 |
| MT-051 | On a Linux machine with **no** Chromium-based browser (or with `ZEPYGUI_BROWSER=/nonexistent`), run `examples/hello.py`. Confirm the terminal says no Edge/Chrome/Chromium was found and the app opens in the default browser and works. | REQ-FBK-002 |
| MT-052 | On macOS run `examples/hello.py` with `app.run(mode="window")` (Chrome installed). Close the window. Confirm the terminal prompt returns within about five seconds. **Revert afterwards.** | REQ-FBK-004 |
| MT-053 | Run `examples/todo.py` with `app.run(mode="browser", reload=True)`. With the tab open, add `ui.text("v2")` to the page and save. Confirm the tab shows "Reconnecting…" briefly, then reloads by itself and shows `v2`. **Revert afterwards.** | REQ-FBK-006 |
| MT-055 | **Windows 10/11**: run `python examples\explorer.py`. Confirm Quick access lists Desktop, Documents, Downloads, Pictures, Music and Videos (including a folder redirected to OneDrive), **This PC** shows every drive letter with its label, type and free space, and an empty card reader appears without any "no disk" pop-up. Show hidden items: confirm `desktop.ini` and `AppData` appear only then. Delete a file with the browser and confirm it is in the Recycle Bin. | REQ-FS-004, REQ-FS-006, REQ-FS-008 |
| MT-056 | **Windows 10/11**: in the dashboard, use Files → Open, Save and Choose folder. Confirm each system dialog opens at once (no PowerShell delay), in front of the app window, and that Save adds the extension and asks before replacing. | REQ-DSK-001 |
| MT-054 | With Python 3.9 **and** the newest available Python 3 (e.g. via `pyenv` or python.org installers), run `python3 -m unittest discover -s tests` and `examples/dashboard.py`. Confirm both pass and open on each version. Record the versions in the release checklist. | REQ-PKG-002 |

# Third-party credits

PyGUI has **no runtime dependencies**: it imports only the Python standard
library, and nothing is vendored into the repository as a library bundle.
This file records the third-party material that *is* included — adapted icon
artwork — and the platform components PyGUI relies on at run time without
shipping them.

The complete licence texts of included material are kept in
[`licences/`](licences/).

## Included material

| Material | Where | Used for | Licence | Website | Source repository |
| --- | --- | --- | --- | --- | --- |
| [Lucide](https://lucide.dev/) icon paths | `ICONS` in [`pygui/ui.py`](pygui/ui.py) | Built-in stroke icons (`ui.icon(...)`) | ISC | [lucide.dev](https://lucide.dev/) | [github.com/lucide-icons/lucide](https://github.com/lucide-icons/lucide) |
| [Feather](https://feathericons.com/) icon paths | `ICONS` in [`pygui/ui.py`](pygui/ui.py) | Built-in stroke icons (`ui.icon(...)`) | MIT | [feathericons.com](https://feathericons.com/) | [github.com/feathericons/feather](https://github.com/feathericons/feather) |

Many entries of `ICONS` reproduce or adapt SVG path data from Lucide and its
predecessor Feather (24×24 grid, 2px stroke, round caps). Others were drawn for
PyGUI in the same style: the `settings` gear is computed in `_gear()`, and the
circles are produced by `_circ()`. Both licences require their copyright notice
to accompany copies of the material:

- [`licences/LUCIDE-LICENSE.txt`](licences/LUCIDE-LICENSE.txt)
- [`licences/FEATHER-LICENSE.txt`](licences/FEATHER-LICENSE.txt)

## Platform components used at run time (not shipped)

PyGUI calls these through the operating system. They are neither copied into
this repository nor redistributed with an app built on PyGUI.

| Component | Used for | Licence | Provided by |
| --- | --- | --- | --- |
| [Python standard library](https://docs.python.org/3/library/) | Everything: HTTP/WebSocket server, threading, `ctypes` bridge | PSF License | The user's Python installation |
| [WebKit](https://webkit.org/) (`WKWebView`) | Rendering the UI in the native macOS window | BSD 2-Clause / LGPL 2.1 (WebKit components) | macOS |
| AppKit, Foundation, Objective-C runtime | Native window, menus, event loop | Apple system frameworks | macOS |
| [Chromium](https://www.chromium.org/)-based browsers (Edge, Chrome, Brave, Chromium, Vivaldi) | App window on Windows/Linux (`mode="window"`) | BSD 3-Clause (Chromium) and vendor terms | Installed by the user (Edge ships with Windows) |
| `osascript`, PowerShell / Windows Forms, `zenity` / `kdialog` / `notify-send` | Native file dialogs and notifications | Vendor / GPL tools | The operating system or distribution |

## Fonts

No font files are bundled. The default font stack names system fonts
(San Francisco on macOS, Segoe UI on Windows, Roboto/Helvetica elsewhere) and
`Inter` only if the user already has it installed.

## Acknowledgements

The architecture — a native window hosting the system web engine, with the
application logic outside the webview — follows the approach popularised by
[Tauri](https://tauri.app/). The visual language of the design system is
inspired by contemporary interface kits such as
[shadcn/ui](https://ui.shadcn.com/) and [Radix](https://www.radix-ui.com/).
No code from these projects is included.

## Notice

When third-party code, icons, fonts or other assets are added to PyGUI, add
them to this file and keep their upstream licence text in `licences/`.

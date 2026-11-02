"""A file explorer: drives, quick access, details and icon views, previews, rename/delete, file dialogs.

    python examples/explorer.py            # starts in your home folder
    python examples/explorer.py C:\\Users   # or anywhere else
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # run without installing

from zepygui import App, State, fs, ui

app = App("Explorer", width=1320, height=820, accent="#2b6ff2")

folder = State(sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else fs.home())
selection = State([])
show_open, show_save, show_folder = State(False), State(False), State(False)
picked = State(None)

PREVIEW_BYTES = 6000


def read_text(path):
    try:
        with open(path, "rb") as f:
            raw = f.read(PREVIEW_BYTES)
    except OSError as exc:
        return f"(cannot read: {exc})"
    if b"\0" in raw:
        return None
    text = raw.decode("utf-8", "replace")
    return text + ("\n…" if len(raw) == PREVIEW_BYTES else "")


def preview(paths):
    """The right-hand panel: what is selected, with a preview of images and text files."""
    if not paths:
        here = fs.crumbs(folder.value)[-1][0] if folder.value else fs.COMPUTER_LABEL
        return ui.column(
            ui.file_icon(here, 72, is_dir=True, special=here),
            ui.h4(here), ui.text("Select a file to see its details.", muted=True, size=13),
            align="center", gap=2, cls="xp-preview-empty",
        )
    if len(paths) > 1:
        size = sum(os.path.getsize(p) for p in paths if os.path.isfile(p))
        return ui.column(
            ui.row(*[ui.file_icon(p, 40, is_dir=os.path.isdir(p)) for p in paths[:4]], gap=1),
            ui.h4(f"{len(paths)} items selected"),
            ui.text(fs.human_size(size), muted=True),
            gap=3,
        )
    path = paths[0]
    try:
        st = os.stat(path)
    except OSError:
        return ui.text("This item no longer exists.", muted=True)
    entry = fs.Entry(os.path.basename(path), path, os.path.isdir(path), st.st_size, st.st_mtime)
    if entry.kind == "image":
        visual = ui.image(fs.file_url(path), alt=entry.name, cls="xp-preview-img", fit="contain")
    elif entry.kind in fs.TEXT_KINDS:
        text = read_text(path)
        visual = ui.code_block(text, copyable=False, cls="xp-preview-text") if text is not None else None
    else:
        visual = None
    facts = [("Type", fs.type_label(entry)), ("Modified", fs.human_time(entry.modified)),
             ("Location", os.path.dirname(path))]
    if not entry.is_dir:
        facts.insert(1, ("Size", f"{fs.human_size(entry.size)}  ({entry.size:,} bytes)"))
    return ui.column(
        visual or ui.row(ui.file_icon(entry, 88), justify="center", cls="xp-preview-icon"),
        ui.column(ui.h4(entry.name, cls="xp-break"), ui.text(fs.type_label(entry), muted=True, size=13), gap=0),
        ui.el("dl", *[ui.fragment(ui.el("dt", k), ui.el("dd", v)) for k, v in facts], cls="xp-facts"),
        ui.row(
            ui.button("Open", lambda: ui.open_path(path), icon="external", size="sm"),
            ui.button("Show in folder", lambda: ui.open_path(path, reveal=True), variant="secondary", size="sm",
                      icon="folder-open"),
            ui.icon_button("copy", lambda: ui.copy(path), tooltip="Copy path", size="sm"),
            gap=2, wrap=True,
        ),
        gap=4,
    )


@app.page("/", title="Explorer")
def home():
    return ui.column(
        ui.row(
            ui.column(ui.h2("Explorer"), ui.text("Browse every drive of this computer", muted=True, size=13), gap=0),
            ui.spacer(),
            ui.text(f"Last picked: {picked.value}", muted=True, size=12, mono=True, truncate=True,
                    style={"max-width": "380px"}) if picked.value else None,
            ui.button("Open…", lambda: show_open.set(True), variant="secondary", icon="folder-open", size="sm"),
            ui.button("Save as…", lambda: show_save.set(True), variant="secondary", icon="download", size="sm"),
            ui.button("Choose folder…", lambda: show_folder.set(True), variant="secondary", icon="folder", size="sm"),
            ui.theme_toggle(),
            gap=2,
        ),
        ui.row(
            ui.file_browser(folder, on_select=selection.set, manage=True, height="calc(100vh - 118px)",
                            style={"flex": 1, "min-width": 0}),
            ui.card(preview(selection.value), cls="xp-preview", padding=5),
            align="stretch", gap=4,
        ),
        ui.file_dialog(show_open, mode="open", multiple=True, on_done=picked.set, title="Open files"),
        ui.file_dialog(show_save, mode="save", default_name="report.csv", types=["csv"], on_done=picked.set),
        ui.file_dialog(show_folder, mode="folder", on_done=picked.set),
        padding=5, gap=4, style={"height": "100vh"},
    )


app.add_css("""
.xp-preview { width: 320px; flex-shrink: 0; overflow: auto; }
.xp-preview-empty { margin: auto 0; padding: 40px 0; text-align: center; }
.xp-preview-img { width: 100%; max-height: 260px; border-radius: 10px; background: var(--surface-2); }
.xp-preview-text { max-height: 260px; overflow: auto; font-size: 11px; }
.xp-preview-icon { padding: 18px 0 6px; }
.xp-break { word-break: break-word; }
.xp-facts { display: grid; grid-template-columns: auto 1fr; gap: 6px 14px; margin: 0; font-size: 13px; }
.xp-facts dt { color: var(--muted); }
.xp-facts dd { margin: 0; word-break: break-all; }
""")

if __name__ == "__main__":
    app.run()

"""Scan a folder tree in the background: progress, cancel, a 100k-row table, hashing in another process."""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # run without installing

from zepygui import App, State, ui

app = App("Files", width=1100, height=780, accent="#f59e0b")

folder = State(os.path.expanduser("~"))
files = State([])          # one dict per file, filled by the scan
scan = State(None)         # the running scan Task
digest = State(None)


def walk(root, task):
    """Runs on the thread pool: list every file under root, publishing results in batches."""
    found, batch, last = [], [], time.monotonic()
    stack = [root]
    while stack:
        task.check()
        path = stack.pop()
        try:
            with os.scandir(path) as entries:
                for e in entries:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            batch.append({"id": len(found) + len(batch), "name": e.name, "path": e.path,
                                          "size": st.st_size, "modified": st.st_mtime})
                    except OSError:
                        continue
        except OSError:
            continue
        if time.monotonic() - last > 0.25:  # show results as they come, 4 times a second
            found += batch
            batch = []
            files.set(list(found))
            task.report(message=f"{len(found):,} files · {path}")
            last = time.monotonic()
    found += batch
    files.set(found)
    return len(found)


def sha256(path):
    """Runs in a separate process (CPU-bound): no effect on the window or the GIL."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return path, h.hexdigest()


def choose():
    path = ui.choose_folder("Folder to scan")
    if path:
        folder.set(path)
        start()


def start():
    if scan.value is not None and scan.value.running:
        return
    files.set([])
    scan.set(ui.task(walk, folder.value, on_done=lambda n: ui.toast(f"{n:,} files found", "success")))


def hash_file(row):
    digest.set((row["name"], "…"))
    ui.task(sha256, row["path"], process=True,
            on_done=lambda result: digest.set((os.path.basename(result[0]), result[1])))


def size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


@app.page("/", title="Files")
def home():
    task = scan.value
    busy = task is not None and task.running
    rows = files.value
    total = sum(r["size"] for r in rows)
    return ui.container(
        ui.row(
            ui.column(ui.h2("Files"), ui.text(folder.value, muted=True, mono=True), gap=1),
            ui.spacer(),
            ui.button("Choose folder", choose, variant="outline", icon="folder", disabled=busy),
            ui.button("Cancel", task.cancel, variant="danger", icon="x") if busy else
            ui.button("Scan", start, icon="search"),
        ),
        ui.grid(
            ui.stat("Files", f"{len(rows):,}", icon="file"),
            ui.stat("Total size", size(total), icon="box"),
            ui.stat("Status", task.status.value.title() if task else "Idle", icon="activity"),
            cols=3,
        ),
        ui.row(ui.spinner("sm"), ui.text(task.message.value, muted=True, size=13)) if busy else None,
        ui.alert(f"SHA-256 of {digest.value[0]}: {digest.value[1]}", kind="info", title="Hash",
                 on_close=lambda: digest.set(None)) if digest.value else None,
        ui.table(rows, [
            ("name", "Name"),
            {"key": "size", "label": "Size", "align": "right", "format": size},
            {"key": "modified", "label": "Modified", "format": lambda t: time.strftime("%Y-%m-%d %H:%M",
                                                                                     time.localtime(t))},
        ], on_row_click=hash_file, max_height=440, empty="Press Scan to list the files of this folder"),
        ui.text("Click a row to hash the file in a separate process.", muted=True, size=12),
        max_width=1100, padding=6, cls="pg-col", style={"gap": "16px"},
    )


if __name__ == "__main__":  # required for process=True: worker processes re-import this file
    app.run()

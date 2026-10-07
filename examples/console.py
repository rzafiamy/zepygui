"""A log console that stays smooth with 100,000+ lines: streaming, filtering, commands, export."""
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # run without installing

from pygui import App, Log, State, ui

app = App("Console", width=1100, height=760, accent="#0ea5e9")

log = Log(max_lines=200_000)
query = State("")
follow = State(True)
job = State(None)  # the Task currently writing to the log
command = State(f"{sys.executable} -c \"import this\"")

LEVELS = ["INFO"] * 12 + ["DEBUG"] * 4 + ["WARN"] * 2 + ["ERROR"]
SERVICES = ["api", "auth", "billing", "search", "worker", "scheduler"]


def simulate(n, task):
    """Write n realistic log lines as fast as possible, reporting progress."""
    for i in range(n):
        if i % 1000 == 0:
            task.check()  # stop here if Cancel was pressed
            task.report(i / n, f"{i:,} / {n:,} lines")
        level = random.choice(LEVELS)
        log.append(f"{time.strftime('%H:%M:%S')}.{i % 1000:03d} {level:<5} [{random.choice(SERVICES)}] "
                   f"request {i:06d} took {random.randint(1, 900)} ms")
    return n


def start_simulation():
    job.set(ui.task(simulate, 70_000, on_done=lambda total: ui.toast(f"{total:,} lines written", "success")))


def run_command():
    if command.value.strip():
        log.append(f"$ {command.value}")
        job.set(ui.run_command(command.value, shell=True, log=log,
                               on_done=lambda code: log.append(f"[exit {code}]"),
                               on_error=lambda exc: log.append(f"[{exc}]")))


def export():
    path = ui.save_file("Export log", "console.log", types=["log", "txt"])
    if path:
        ui.task(log.save, path, on_done=lambda _: ui.toast(f"Saved {os.path.basename(path)}", "success"))


@app.page("/", title="Console")
def home():
    task = job.value
    busy = task is not None and task.running
    progress = task.progress.value if task is not None else None
    return ui.container(
        ui.row(
            ui.column(ui.h2("Console"), ui.text(f"Keeps the last {log.max_lines:,} lines", muted=True), gap=1),
            ui.spacer(),
            ui.button("Write 70,000 lines", start_simulation, icon="play", disabled=busy),
            ui.button("Cancel", task.cancel if busy else None, variant="outline", icon="x", disabled=not busy),
            ui.icon_button("download", export, tooltip="Export"),
            ui.icon_button("trash", log.clear, tooltip="Clear"),
        ),
        ui.progress((progress or 0) * 100, label=task.message.value, show_value=True) if busy and progress else None,
        ui.row(
            ui.input(query, placeholder="Filter lines…", icon="search", clearable=True, debounce=150,
                     style={"flex": 1}),
            ui.switch("Follow", follow),
        ),
        ui.log_view(log, height=480, filter=query, follow=follow.value, numbers=True),
        ui.row(
            ui.input(command, icon="terminal", on_enter=lambda _: run_command(), style={"flex": 1}),
            ui.button("Run", run_command, variant="secondary", disabled=busy),
        ),
        max_width=1100, padding=6, cls="pg-col", style={"gap": "14px"},
    )


app.run()

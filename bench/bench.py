"""Performance benchmarks for the ZePyGUI runtime (headless, no window).

    python3 bench/bench.py            # all scenarios
    python3 bench/bench.py render     # only scenarios whose name contains "render"

Each scenario prints one line: name, measured value, and what it means.
Numbers are wall-clock on this machine; compare runs, not machines.
"""
import json
import os
import sys
import threading
import time
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from zepygui import App, Log, State, ui  # noqa: E402
from zepygui.app import Renderer, Session  # noqa: E402

SCENARIOS = []


def scenario(fn):
    SCENARIOS.append(fn)
    return fn


class Sink:
    """A window that counts messages without parsing them (log messages are parsed)."""

    def __init__(self):
        self.renders = 0
        self.bytes = 0
        self.last = None
        self.log_messages = 0
        self.log_lines = 0
        self.event = threading.Event()

    def __call__(self, text):
        self.bytes += len(text)
        if text.startswith('{"type":"render"'):
            self.renders += 1
            self.last = text
            self.event.set()
        elif text.startswith('{"type":"log"'):
            m = json.loads(text)
            self.log_messages += 1
            self.log_lines = m["start"] + len(m["lines"]) if m["reset"] else self.log_lines + len(m["lines"])


def best_of(fn, n=5):
    times = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t)
    return min(times)


def render_once(app, path="/"):
    s = Session(app, "bench", path, "dark")
    try:
        r = Renderer(s)
        t0 = time.perf_counter()
        tree, _ = r.build()
        t1 = time.perf_counter()
        text = json.dumps({"type": "render", "tree": tree, "ack": 0}, separators=(",", ":"), default=str)
        t2 = time.perf_counter()
        return t1 - t0, t2 - t1, len(text)
    finally:
        s.close()


def files(n):
    return [{"id": i, "name": f"file_{i:05d}.txt", "size": i * 1031 % 99991, "kind": ("doc", "img", "bin")[i % 3],
             "modified": "2026-10-07 12:00"} for i in range(n)]


def report(name, value, unit, note=""):
    print(f"{name:<38} {value:>10.2f} {unit:<6} {note}")


# -- rendering -----------------------------------------------------------------------
def _table_app(n, fmt):
    app = App("bench")
    data = files(n)
    cols = ["name", {"key": "size", "align": "right", "format": (lambda v: f"{v:,} B") if fmt else None},
            {"key": "kind", "format": (lambda v: ui.badge(v)) if fmt else None}, "modified"]

    @app.page("/")
    def home():
        return ui.container(ui.h1("Files"), ui.table(data, cols, on_row_click=lambda r: None, virtual=False))
    return app


@scenario
def render_table_5k():
    app = _table_app(5000, fmt=True)
    build, enc, size = min((render_once(app) for _ in range(3)), key=lambda t: t[0] + t[1])
    report("render table 5k rows (build)", build * 1000, "ms")
    report("render table 5k rows (json)", enc * 1000, "ms", f"payload {size / 1e6:.2f} MB")


@scenario
def render_list_5k():
    app = App("bench")
    data = files(5000)

    @app.page("/")
    def home():
        return ui.column(*[ui.row(ui.icon("file"), ui.text(f["name"]), ui.spacer(), ui.badge(f["kind"]),
                                  ui.icon_button("trash", lambda f=f: None), key=f["id"]) for f in data])
    build, enc, size = min((render_once(app) for _ in range(3)), key=lambda t: t[0] + t[1])
    report("render keyed list 5k rows (build)", build * 1000, "ms")
    report("render keyed list 5k rows (json)", enc * 1000, "ms", f"payload {size / 1e6:.2f} MB")


# -- scheduling ----------------------------------------------------------------------
@scenario
def state_flood_from_thread():
    """A background thread updating progress as fast as it can (e.g. while hashing files)."""
    app = App("bench")
    progress = State(0)

    @app.page("/")
    def home():
        return ui.column(ui.progress(progress.value % 100), ui.text(f"{progress.value} items"))

    sink = Sink()
    s = Session(app, "flood", "/", "dark")
    s.attach(sink)
    sink.event.wait(2)
    n = 50_000
    t = time.perf_counter()
    for i in range(n):
        progress.set(i + 1)
    produced = time.perf_counter() - t
    # wait until the window shows the final value
    deadline = time.time() + 30
    while time.time() < deadline and f'"{n} items"' not in (sink.last or ""):
        time.sleep(0.005)
    settled = time.perf_counter() - t
    peak_queue = s.queue.qsize()
    s.close()
    report("state flood 50k sets: producer time", produced * 1000, "ms")
    report("state flood 50k sets: until UI settled", settled * 1000, "ms", f"{sink.renders} renders")
    del peak_queue


@scenario
def event_throughput():
    app = App("bench")
    n_state = State(0)

    @app.page("/")
    def home():
        return ui.button(f"{n_state.value}", lambda: n_state.set(n_state.value + 1))

    sink = Sink()
    s = Session(app, "events", "/", "dark")
    s.attach(sink)
    sink.event.wait(2)
    hid = json.loads(sink.last)["tree"]["c"][0]["e"]["click"][0]["h"]
    n = 5000
    t = time.perf_counter()
    for i in range(n):
        s.queue.put(("event", hid, {}, i + 1))
    deadline = time.time() + 30
    while time.time() < deadline and f'"ack":{n}' not in (sink.last or ""):
        time.sleep(0.002)
    dt = time.perf_counter() - t
    s.close()
    report("5k click events processed", dt * 1000, "ms", f"{sink.renders} renders")


@scenario
def blocking_handler_latency():
    """A slow sync handler (file copy, subprocess) delays every later event of the window."""
    app = App("bench")
    clicks = State(0)

    def slow():
        time.sleep(0.5)

    @app.page("/")
    def home():
        return ui.column(ui.button("slow", slow), ui.button(f"{clicks.value}", lambda: clicks.set(clicks.value + 1)))

    sink = Sink()
    s = Session(app, "block", "/", "dark")
    s.attach(sink)
    sink.event.wait(2)
    tree = json.loads(sink.last)["tree"]
    slow_h, fast_h = (c["e"]["click"][0]["h"] for c in tree["c"][0]["c"])
    s.queue.put(("event", slow_h, {}, 1))
    t = time.perf_counter()
    s.queue.put(("event", fast_h, {}, 2))
    deadline = time.time() + 5
    while time.time() < deadline and '"ack":2' not in (sink.last or ""):
        time.sleep(0.002)
    dt = time.perf_counter() - t
    s.close()
    report("click latency behind a 500ms handler", dt * 1000, "ms")


@scenario
def render_memory():
    """Peak Python allocation while rendering the 5k-row list, and what the window keeps."""
    app = App("bench")
    data = files(5000)

    @app.page("/")
    def home():
        return ui.column(*[ui.row(ui.icon("file"), ui.text(f["name"]), ui.spacer(), ui.badge(f["kind"]),
                                  ui.icon_button("trash", lambda f=f: None), key=f["id"]) for f in data])
    s = Session(app, "mem", "/", "dark")
    tracemalloc.start()
    r = Renderer(s)
    tree, _ = r.build()
    text = json.dumps({"type": "render", "tree": tree, "ack": 0}, separators=(",", ":"))
    del tree, text
    s.handlers = r.handlers
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    s.close()
    report("render 5k list: peak allocation", peak / 1e6, "MB")
    report("render 5k list: retained (handlers)", current / 1e6, "MB")


def _table_virtual_app(n):
    app = App("bench")
    data = files(n)
    cols = ["name", {"key": "size", "align": "right", "format": lambda v: f"{v:,} B"},
            {"key": "kind", "format": lambda v: ui.badge(v)}, "modified"]

    @app.page("/")
    def home():
        return ui.container(ui.h1("Files"), ui.table(data, cols, on_row_click=lambda r: None, max_height=600))
    return app


@scenario
def render_virtual_table_100k():
    app = _table_virtual_app(100_000)
    build, enc, size = min((render_once(app) for _ in range(3)), key=lambda t: t[0] + t[1])
    report("virtual table 100k rows (build)", build * 1000, "ms")
    report("virtual table 100k rows (json)", enc * 1000, "ms", f"payload {size / 1e3:.0f} KB")
    sink = Sink()
    s = Session(app, "vt", "/", "dark")
    s.attach(sink)
    sink.event.wait(2)
    tree = json.loads(sink.last)["tree"]

    def find_scroll(n):
        if isinstance(n, dict):
            if "scroll" in n.get("e", {}):
                return n["e"]["scroll"][0]["h"]
            for c in n.get("c", []):
                h = find_scroll(c)
                if h:
                    return h
    hid = find_scroll(tree)
    times = []
    for i in range(1, 21):
        sink.event.clear()
        t = time.perf_counter()
        s.queue.put(("event", hid, {"scrollTop": i * 36 * 2500}, i))
        sink.event.wait(2)
        times.append(time.perf_counter() - t)
    s.close()
    report("virtual table: scroll to new rows", sorted(times)[len(times) // 2] * 1000, "ms", "median, event → render")


@scenario
def log_70k_lines():
    """The console case: a producer thread writes 70,000 log lines while a window shows them."""
    app = App("bench")
    log = Log(max_lines=100_000)

    @app.page("/")
    def home():
        return ui.log_view(log, height=480)

    sink = Sink()
    s = Session(app, "log", "/", "dark")
    s.attach(sink)
    sink.event.wait(2)
    n = 70_000
    t = time.perf_counter()
    for i in range(n):
        log.append(f"2026-10-07 12:00:{i % 60:02d} INFO worker[{i % 8}] processed item {i} in {i % 97} ms")
    produced = time.perf_counter() - t
    deadline = time.time() + 30
    while time.time() < deadline and sink.log_lines < n:
        time.sleep(0.002)
    delivered = time.perf_counter() - t
    renders = sink.renders
    s.close()
    report("log 70k lines: producer time", produced * 1000, "ms", f"{n / produced:,.0f} lines/s")
    report("log 70k lines: all delivered to window", delivered * 1000, "ms",
           f"{sink.log_messages} messages, {renders} renders, {sink.bytes / 1e6:.1f} MB sent")
    tracemalloc.start()
    held = Log(max_lines=100_000)
    held.extend(f"2026-10-07 12:00:{i % 60:02d} INFO worker[{i % 8}] processed item {i} in {i % 97} ms"
                for i in range(n))
    current, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report("log 70k lines: Python memory held", current / 1e6, "MB", "lines + ring buffer")


@scenario
def task_keeps_window_responsive():
    """Same slow work as blocking_handler_latency, started with ui.task instead."""
    app = App("bench")
    clicks = State(0)

    def slow():
        ui.task(time.sleep, 0.5)

    @app.page("/")
    def home():
        return ui.column(ui.button("slow", slow), ui.button(f"{clicks.value}", lambda: clicks.set(clicks.value + 1)))

    sink = Sink()
    s = Session(app, "task", "/", "dark")
    s.attach(sink)
    sink.event.wait(2)
    tree = json.loads(sink.last)["tree"]
    slow_h, fast_h = (c["e"]["click"][0]["h"] for c in tree["c"][0]["c"])
    s.queue.put(("event", slow_h, {}, 1))
    t = time.perf_counter()
    s.queue.put(("event", fast_h, {}, 2))
    deadline = time.time() + 5
    while time.time() < deadline and '"ack":2' not in (sink.last or ""):
        time.sleep(0.001)
    dt = time.perf_counter() - t
    s.close()
    report("click latency while ui.task works", dt * 1000, "ms")


@scenario
def background_tasks():
    """Many short background jobs (e.g. stat-ing files)."""
    done = threading.Semaphore(0)
    n = 2000

    def job():
        done.release()

    t = time.perf_counter()
    for _ in range(n):
        ui.background(job)
    for _ in range(n):
        done.acquire()
    dt = time.perf_counter() - t
    report("2k ui.background jobs", dt * 1000, "ms", f"peak threads {threading.active_count()}")


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    print(f"python {sys.version.split()[0]} · {sys.platform}")
    for fn in SCENARIOS:
        if only in fn.__name__:
            fn()

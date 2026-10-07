"""Runs one scenario in a real native window and prints ``RESULT <json>``. Used by test_native.py."""
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from zepygui import App, Log, State, rules, ui  # noqa: E402

scenario = sys.argv[1]
app = App(f"Native {scenario}", width=640, height=480)
results = {}
reports = []
got_report = threading.Event()


@app.expose
def report(value):
    reports.append(value)
    got_report.set()


def ask(js_expr, timeout=6.0):
    """Evaluate ``js_expr`` in the window and return its value."""
    got_report.clear()
    ui.run_js(f"zepygui.call('report', {js_expr})")
    if not got_report.wait(timeout):
        raise TimeoutError(js_expr)
    return reports[-1]


def js(code, settle=0.6):
    ui.run_js(code)
    time.sleep(settle)


def png(path):
    raw = b"".join(b"\x00" + b"\x63\x66\xf1\xff" * 4 for _ in range(4))

    def chunk(kind, data):
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!IIBBBBB", 4, 4, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


text = State("")
count = State(0)
items = State(["a", "b", "c"])
log = Log(max_lines=100_000)
rows = [{"id": i, "name": f"file_{i:06d}"} for i in range(100_000)]
saved = State([])
banner = State(False)

if scenario == "assets":
    folder = tempfile.mkdtemp()
    png(os.path.join(folder, "dot.png"))
    app.static("/assets", folder)

app.layout(lambda content: ui.shell(content, sidebar=ui.sidebar(
    ui.nav_item("Home", "/", icon="home"), ui.nav_item("Two", "/two", icon="star"), title="T")))


@app.page("/")
def home():
    return ui.column(
        ui.h1(f"Home {count.value}"),
        ui.input(text, id="field"),
        ui.text(f"echo:{text.value}", id="echo"),
        ui.button("inc", lambda: count.set(count.value + 1), id="inc"),
        ui.div(*[ui.span(i, key=i, cls="item") for i in items.value], id="list"),
        ui.image("assets/dot.png", width=8, height=8, id="img") if scenario == "assets" else None,
        ui.alert("Streaming…") if banner.value else None,  # a sibling that comes and goes above the log
        ui.log_view(log, height=200, numbers=True, cls="t-log") if scenario == "log" else None,
        ui.table(rows, ["name"], max_height=200, cls="t-table") if scenario == "virtual" else None,
        signup() if scenario == "form" else None,
    )


def signup():
    form = ui.use_form(email=("", [rules.required(), rules.email()]))
    return ui.form(ui.input(form.email, label="Email", cls="t-email"), ui.button("Save", submit=True, cls="t-save"),
                   ui.text(f"saved={len(saved.value)}", cls="t-saved"),
                   on_submit=form.submit(lambda v: saved.append(v["email"])))


@app.page("/two", title="Two")
def two():
    return ui.h1("Second page")


@app.on_shutdown
def on_shutdown():
    results["shutdown_hook_ran"] = True


def drive():
    try:
        deadline = time.time() + 20
        while time.time() < deadline:  # wait for the first render instead of guessing a delay
            try:
                if ask("!!document.querySelector('h1')", timeout=1.0):
                    break
            except TimeoutError:
                pass
        time.sleep(0.3)
        if scenario == "close":
            results["title"] = ask("document.querySelector('h1').textContent")
        elif scenario == "assets":
            results["natural_width"] = ask("document.getElementById('img').naturalWidth")
        elif scenario == "nav":
            js("document.querySelector('a[href=\"/two\"]').click()")
            results["after"] = ask("[document.querySelector('h1').textContent, location.hash, document.title,"
                                   " document.querySelector('.pg-nav-item.active').textContent]")
        elif scenario == "typing":
            js("const i=document.getElementById('field'); i.focus(); let s='';"
               "for (const ch of 'Hello world') { s+=ch; i.value=s; i.dispatchEvent(new Event('input')); }", 1.0)
            results["typed"] = ask("[document.getElementById('field').value,"
                                   " document.getElementById('echo').textContent]")
            results["state"] = text.value
            text.set("")  # a change made by Python must still reach a focused input
            time.sleep(0.6)
            results["cleared"] = ask("document.getElementById('field').value")
        elif scenario == "reuse":
            js("document.getElementById('field')._mark = 1; document.querySelector('.item')._mark = 'a';", 0.2)
            js("document.getElementById('inc').click()")
            items.set(["c", "a", "b"])
            time.sleep(0.6)
            results["after"] = ask("[document.querySelector('h1').textContent,"
                                   " document.getElementById('field')._mark === 1,"
                                   " [...document.querySelectorAll('.item')].map(e => e.textContent),"
                                   " [...document.querySelectorAll('.item')].find(e => e.textContent === 'a')._mark]")
        elif scenario == "log":
            def produce():
                for i in range(70_000):
                    log.append(f"line {i}")
                    if i in (20_000, 50_000):
                        banner.set(not banner.value)
            ui.task(produce).wait(20)
            time.sleep(0.8)
            results["view"] = ask("(() => { const v = document.querySelector('.t-log');"
                                  " const r = v.querySelectorAll('.pg-log-rows > div');"
                                  " return [r.length, r[r.length - 1].dataset.n, r[r.length - 1].textContent,"
                                  " Math.round(v.scrollHeight / 18)]; })()")
        elif scenario == "virtual":
            results["before"] = ask("document.querySelectorAll('.t-table tbody tr:not(.pg-vspacer)').length")
            js("const w = document.querySelector('.t-table'); w.scrollTop = 36 * 50000;"
               " w.dispatchEvent(new Event('scroll'));", 0.8)
            results["after"] = ask("(() => { const w = document.querySelector('.t-table');"
                                   " const r = [...w.querySelectorAll('tbody tr:not(.pg-vspacer)')];"
                                   " const top = w.getBoundingClientRect().top + 50;"
                                   " const seen = r.find(tr => tr.getBoundingClientRect().bottom > top);"
                                   " return [r.length, seen ? seen.textContent : null]; })()")
        elif scenario == "form":
            js("document.querySelector('.t-save').click()")
            results["empty"] = ask("[...document.querySelectorAll('.pg-error-text')].map(e => e.textContent)")
            js("const i = document.querySelector('.t-email input'); i.value = 'ada@example';"
               " i.dispatchEvent(new Event('input'));")
            results["typing"] = ask("[...document.querySelectorAll('.pg-error-text')].map(e => e.textContent)")
            js("const i = document.querySelector('.t-email input'); i.value = 'ada@example.com';"
               " i.dispatchEvent(new Event('input'));")
            js("document.querySelector('.t-save').click()")
            results["valid"] = ask("[document.querySelectorAll('.pg-error-text').length,"
                                   " document.querySelector('.t-saved').textContent]")
            results["saved"] = saved.value
        elif scenario == "sockets":
            out = subprocess.run(["lsof", "-nP", "-a", "-p", str(os.getpid()), "-i"], capture_output=True,
                                 text=True).stdout
            results["sockets"] = [line for line in out.splitlines()[1:] if line.strip()]
            results["rendered"] = ask("document.querySelector('h1').textContent")
    except Exception as exc:  # report instead of hanging the window
        results["error"] = repr(exc)
    finally:
        time.sleep(0.3)
        app.quit()


app.on_startup(lambda: threading.Thread(target=drive, daemon=True).start())
app.run()
results["run_returned"] = True
print("RESULT " + json.dumps(results))

"""Security (REQ-SEC), fallback transport (REQ-FBK), desktop helpers (REQ-DSK), dev tools (REQ-DEV),
packaging (REQ-PKG)."""
import ast
import http.client
import inspect
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import LiveServer, find, handler_id, tag, text_of, ws_connect, ws_next, ws_recv, ws_send

from zepygui import App, ui
from zepygui import desktop
from zepygui.app import Session
from zepygui.reloader import _snapshot

ROOT = Path(__file__).resolve().parent.parent


def get(port, path, cookie=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers={"Cookie": cookie} if cookie else {})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp, body


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = App("t")
        self.app.page("/")(lambda: ui.text("home"))
        self.live = LiveServer(self.app)

    def tearDown(self):
        self.live.close()

    def test_pages_and_websocket_require_the_token(self):
        """covers: REQ-SEC-001"""
        self.assertEqual(get(self.live.port, "/")[0].status, 403)
        self.assertEqual(get(self.live.port, "/other")[0].status, 403)
        self.assertEqual(get(self.live.port, "/?_pgt=wrong")[0].status, 403)
        sock, status = ws_connect(self.live.port, "sid=x&path=/")
        sock.close()
        self.assertEqual(status, 403)
        self.assertEqual(get(self.live.port, "/_pg/client.js")[0].status, 200)
        self.assertEqual(get(self.live.port, "/", self.live.cookie)[0].status, 200)

    def test_valid_token_sets_a_strict_cookie_and_strips_itself(self):
        """covers: REQ-SEC-002"""
        resp, _ = get(self.live.port, f"/settings?_pgt={self.app.token}&tab=2")
        cookie = resp.getheader("Set-Cookie")
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.getheader("Location"), "/settings?tab=2")
        for part in (f"pg_t_{self.live.port}={self.app.token}", "HttpOnly", "SameSite=Strict"):
            self.assertIn(part, cookie)

    def test_static_files_cannot_escape_their_directory(self):
        """covers: REQ-SEC-003"""
        base = Path(tempfile.mkdtemp())
        (base / "public").mkdir()
        (base / "public" / "ok.txt").write_text("fine")
        (base / "secret.txt").write_text("SECRET")
        self.app.static("/assets", base / "public")
        self.assertEqual(get(self.live.port, "/assets/ok.txt", self.live.cookie)[1], b"fine")
        for path in ("/assets/../secret.txt", "/assets/%2e%2e/secret.txt", "/_pg/../app.py"):
            resp, body = get(self.live.port, path, self.live.cookie)
            self.assertNotIn(b"SECRET", body)
            self.assertNotEqual(resp.status, 200, path)

    def test_oversized_websocket_messages_close_the_connection(self):
        """covers: REQ-SEC-006"""
        sock, status = ws_connect(self.live.port, "sid=big&path=/", self.live.cookie)
        self.assertEqual(status, 101)
        ws_send(sock, "", declared_length=33 * 1024 * 1024)
        sock.settimeout(3)
        closed = False
        try:
            while True:
                op, _ = ws_recv(sock)
                if op == 0x8:
                    closed = True
                    break
        except (ConnectionError, OSError):
            closed = True
        sock.close()
        self.assertTrue(closed)

    def test_a_new_window_gets_exactly_one_first_render(self):
        """covers: REQ-RND-008"""
        sock, _ = ws_connect(self.live.port, "sid=once&path=/&theme=light", self.live.cookie)
        sock.settimeout(0.8)
        kinds = []
        try:
            while True:
                op, payload = ws_recv(sock)
                if op == 0x1:
                    kinds.append(json.loads(payload)["type"])
        except (OSError, ConnectionError):
            pass
        sock.close()
        self.assertEqual(kinds.count("render"), 1, kinds)

    def test_reconnecting_window_resumes_its_session(self):
        """covers: REQ-FBK-005"""
        @self.app.page("/count")
        def count():
            n = ui.use_state(0)
            return ui.button(str(n.value), lambda: n.set(n.value + 1))

        sock, _ = ws_connect(self.live.port, "sid=resume1&path=/count", self.live.cookie)
        tree = ws_next(sock, "render")["tree"]
        ws_send(sock, json.dumps({"type": "event", "h": handler_id(find(tree, tag("button")), "click"), "d": {}, "s": 1}))
        self.assertEqual(text_of(ws_next(sock, "render")["tree"]), "1")
        sock.close()
        time.sleep(0.2)
        sock, _ = ws_connect(self.live.port, "sid=resume1&path=/count", self.live.cookie)
        self.assertEqual(text_of(ws_next(sock, "render")["tree"]), "1")
        sock.close()


class SecurityUnitTests(unittest.TestCase):
    def test_markdown_escapes_html_and_neutralises_script_urls(self):
        """covers: REQ-SEC-004"""
        out = ui._markdown_to_html("<script>alert(1)</script> [a](javascript:alert(1)) [b](VBScript:x) "
                                   "![i](data:text/html;base64,xx) [ok](https://example.com)")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("javascript:", out.lower())
        self.assertNotIn("vbscript:", out.lower())
        self.assertNotIn("data:", out)
        self.assertIn('href="https://example.com"', out)

    def test_open_url_accepts_only_web_and_mail_links(self):
        """covers: REQ-SEC-007"""
        app = App("t")
        session = Session(app, "u")
        with mock.patch("zepygui.app.webbrowser.open") as opener:
            for url in ("javascript:alert(1)", "file:///etc/passwd", "https://ok.example", "mailto:a@b.c"):
                app._dispatch(session, {"type": "open_url", "url": url})
            time.sleep(0.2)
        self.assertEqual(sorted(c.args[0] for c in opener.call_args_list), ["https://ok.example", "mailto:a@b.c"])
        session.close()

    def test_server_binds_loopback_by_default(self):
        """covers: REQ-FBK-003"""
        self.assertEqual(inspect.signature(App.run).parameters["host"].default, "127.0.0.1")


class DesktopTests(unittest.TestCase):
    def test_applescript_strings_are_escaped(self):
        """covers: REQ-DSK-002"""
        self.assertEqual(desktop._as('say "hi" \\ bye'), '"say \\"hi\\" \\\\ bye"')

    def test_powershell_strings_are_escaped(self):
        """covers: REQ-DSK-003"""
        self.assertEqual(desktop._ps_str("it's"), "'it''s'")


class DevToolTests(unittest.TestCase):
    def test_reloader_ignores_hidden_and_generated_directories(self):
        """covers: REQ-DEV-002"""
        root = Path(tempfile.mkdtemp())
        for rel in ("app.py", "style.css", "pkg/mod.py", ".git/x.py", "__pycache__/a.py", "venv/b.py",
                    "node_modules/c.js", "notes.bin"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("x")
        found = sorted(os.path.relpath(p, root) for p in _snapshot(root))
        self.assertEqual(found, ["app.py", os.path.join("pkg", "mod.py"), "style.css"])

    def test_cli_creates_a_runnable_app_and_refuses_to_overwrite(self):
        """covers: REQ-DEV-004"""
        from zepygui.__main__ import main
        target = Path(tempfile.mkdtemp()) / "my-tool"
        with mock.patch("builtins.print"):
            main(["new", str(target)])
        source = (target / "app.py").read_text()
        ast.parse(source)
        self.assertIn('App("My Tool"', source)
        with self.assertRaises(SystemExit):
            main(["new", str(target)])


class PackagingTests(unittest.TestCase):
    STDLIB = {"__future__", "asyncio", "base64", "builtins", "ctypes", "functools", "hashlib", "html", "http",
              "collections", "concurrent", "contextvars", "itertools", "multiprocessing", "types", "inspect", "json", "math", "mimetypes", "os", "pathlib", "platform", "queue", "re", "secrets",
              "shutil", "signal", "socket", "struct", "subprocess", "sys", "tempfile", "textwrap", "threading",
              "time", "traceback", "urllib", "weakref", "webbrowser"}

    def test_package_imports_only_the_standard_library(self):
        """covers: REQ-PKG-001"""
        if hasattr(sys, "stdlib_module_names"):
            self.STDLIB = set(sys.stdlib_module_names)
        for path in (ROOT / "zepygui").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module]
                for name in names:
                    self.assertIn(name.split(".")[0], self.STDLIB, f"{path.name} imports {name}")

    def test_static_assets_are_package_data(self):
        """covers: REQ-PKG-003"""
        config = (ROOT / "pyproject.toml").read_text()
        self.assertIn('"zepygui.static" = ["*.js", "*.css"]', config)
        for name in ("client.js", "style.css"):
            self.assertTrue((ROOT / "zepygui" / "static" / name).is_file())


if __name__ == "__main__":
    unittest.main()

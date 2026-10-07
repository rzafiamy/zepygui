"""Shared test utilities: a fake window, a render harness and a minimal WebSocket client."""
import base64
import json
import os
import queue
import socket
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from zepygui.app import Session  # noqa: E402


class FakeWindow:
    """Captures the messages a Session sends to its window."""

    def __init__(self):
        self.messages = queue.Queue()

    def __call__(self, text):
        self.messages.put(json.loads(text))

    def next(self, kind, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                m = self.messages.get(timeout=max(0.01, deadline - time.time()))
            except queue.Empty:
                break
            if m["type"] == kind:
                return m
        raise AssertionError(f"no {kind!r} message received")

    def drain(self, kind, wait=0.3):
        """All messages of ``kind`` arriving within ``wait`` seconds."""
        found, deadline = [], time.time() + wait
        while time.time() < deadline:
            try:
                m = self.messages.get(timeout=max(0.01, deadline - time.time()))
            except queue.Empty:
                break
            if m["type"] == kind:
                found.append(m)
        return found


def find(node, pred):
    if isinstance(node, dict):
        if pred(node):
            return node
        for c in node.get("c", []):
            hit = find(c, pred)
            if hit:
                return hit
    return None


def find_all(node, pred, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        if pred(node):
            out.append(node)
        for c in node.get("c", []):
            find_all(c, pred, out)
    return out


def tag(name):
    return lambda n: n.get("t") == name


def has_class(cls):
    return lambda n: cls in (n.get("a", {}).get("class") or "").split()


def text_of(node):
    if isinstance(node, str):
        return node
    return "".join(text_of(c) for c in node.get("c", []))


def handler_id(node, event):
    return node["e"][event][0]["h"]


class Harness:
    """One window session attached to a FakeWindow, with its first render captured."""

    def __init__(self, app, path="/", theme="dark"):
        self.app = app
        self.win = FakeWindow()
        self.session = Session(app, f"test-{id(self)}", path, theme)
        app.sessions[self.session.id] = self.session
        self.session.attach(self.win)
        self.tree = self.win.next("render")["tree"]

    def event(self, hid, data=None, seq=0, expect_render=True):
        self.session.queue.put(("event", hid, data or {}, seq))
        if expect_render:
            self.tree = self.win.next("render")["tree"]
        return self.tree

    def click(self, pred):
        return self.event(handler_id(find(self.tree, pred), "click"))

    def close(self):
        self.session.close()


# -- minimal WebSocket client ---------------------------------------------------------
def ws_connect(port, query, cookie=None):
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    lines = [f"GET /_pg/ws?{query} HTTP/1.1", f"Host: 127.0.0.1:{port}", "Upgrade: websocket",
             "Connection: Upgrade", f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
    if cookie:
        lines.append(f"Cookie: {cookie}")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = sock.recv(1)
        if not chunk:
            break
        head += chunk
    status = int(head.split(b" ", 2)[1]) if head else 0
    return sock, status


def ws_send(sock, text, declared_length=None):
    payload = text.encode()
    n = len(payload) if declared_length is None else declared_length
    mask = os.urandom(4)
    if n < 126:
        head = struct.pack("!BB", 0x81, 0x80 | n)
    elif n < 65536:
        head = struct.pack("!BBH", 0x81, 0x80 | 126, n)
    else:
        head = struct.pack("!BBQ", 0x81, 0x80 | 127, n)
    body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(head + mask + body)


def _read_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data += chunk
    return data


def ws_recv(sock):
    """Next frame as (opcode, payload_text). Raises ConnectionError on EOF."""
    b1, b2 = _read_exact(sock, 2)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack("!H", _read_exact(sock, 2))[0]
    elif n == 127:
        n = struct.unpack("!Q", _read_exact(sock, 8))[0]
    return b1 & 0x0F, _read_exact(sock, n).decode("utf-8", "replace")


def ws_next(sock, kind, timeout=3.0):
    sock.settimeout(timeout)
    while True:
        op, text = ws_recv(sock)
        if op == 0x1:
            m = json.loads(text)
            if m.get("type") == kind:
                return m


class LiveServer:
    """A real ZePyGUI HTTP/WebSocket server on loopback, for transport and security tests."""

    def __init__(self, app, token="secret-token"):
        from zepygui.server import make_server
        self.app = app
        app.token = token
        app._running = True
        self.server = make_server(app, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    @property
    def cookie(self):
        return f"pg_t_{self.port}={self.app.token}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.app._shutdown_hooks()

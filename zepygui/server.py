"""Minimal HTTP + WebSocket (RFC 6455) server built only on the standard library."""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import re
import secrets
import socket
import struct
import sys
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

STATIC_DIR = Path(__file__).parent / "static"
_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_MESSAGE = 32 * 1024 * 1024


class WebSocket:
    def __init__(self, rfile, sock):
        self.rfile = rfile
        self.sock = sock
        self.lock = threading.Lock()
        self.closed = False

    def _read(self, n):
        data = self.rfile.read(n) if n else b""
        if len(data) < n:
            raise ConnectionError("socket closed")
        return data

    def recv(self):
        """Next text message, or None once the connection is closed."""
        message, opcode = bytearray(), None
        try:
            while True:
                b1, b2 = self._read(2)
                fin, op, n = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
                if n == 126:
                    n = struct.unpack("!H", self._read(2))[0]
                elif n == 127:
                    n = struct.unpack("!Q", self._read(8))[0]
                if n + len(message) > _MAX_MESSAGE:
                    raise ConnectionError("message too large")
                mask = self._read(4) if b2 & 0x80 else None
                data = self._read(n)
                if mask and n:
                    key = (mask * (n // 4 + 1))[:n]
                    data = (int.from_bytes(data, "big") ^ int.from_bytes(key, "big")).to_bytes(n, "big")
                if op == 0x8:
                    self._send_frame(0x8, b"")
                    break
                if op == 0x9:
                    self._send_frame(0xA, data)
                    continue
                if op == 0xA:
                    continue
                if op in (0x1, 0x2):
                    message, opcode = bytearray(data), op
                elif op == 0x0:
                    message += data
                if fin:
                    return message.decode("utf-8", "replace") if opcode == 0x1 else bytes(message)
        except (ConnectionError, OSError, ValueError):
            pass
        self.closed = True
        return None

    def _send_frame(self, op, payload):
        n = len(payload)
        if n < 126:
            head = struct.pack("!BB", 0x80 | op, n)
        elif n < 65536:
            head = struct.pack("!BBH", 0x80 | op, 126, n)
        else:
            head = struct.pack("!BBQ", 0x80 | op, 127, n)
        with self.lock:
            self.sock.sendall(head + payload)

    def send(self, text):
        if self.closed:
            return False
        try:
            self._send_frame(0x1, text.encode("utf-8"))
            return True
        except OSError:
            self.closed = True
            return False

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self._send_frame(0x8, b"")
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # A window closing mid-request is routine for a desktop app, not an error worth a traceback.
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def make_server(app, host, port):
    handler = type("ZePyGUIHandler", (_Handler,), {"app": app})
    return Server((host, port), handler)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ZePyGUI"
    app = None

    def log_message(self, fmt, *args):
        if self.app.debug:
            super().log_message(fmt, *args)

    # -- helpers ---------------------------------------------------------------
    def _cookie_name(self):
        return f"pg_t_{self.server.server_address[1]}"

    def _authed(self):
        token = self.app.token
        if not token:
            return True
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(self._cookie_name())
        return morsel is not None and secrets.compare_digest(morsel.value, token)

    def _send(self, status, body=b"", ctype="text/html; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # -- routing ---------------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def _route(self, path, body=b""):
        """True when an app route answered the request."""
        for prefix, fn in self.app._http.items():
            if path == prefix or path.startswith(prefix + "/"):
                if not self._authed():
                    self._send(403, "Forbidden", "text/plain")
                else:
                    status, ctype, data = fn(self.command, path[len(prefix):], body)
                    self._send(status, data, ctype)
                return True
        return False

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > _MAX_MESSAGE:
            self.close_connection = True
            return self._send(413, "Too large", "text/plain")
        body = self.rfile.read(length)
        if not self._route(unquote(urlsplit(self.path).path), body):
            self._send(404, "Not found", "text/plain")

    def do_GET(self):
        url = urlsplit(self.path)
        path = unquote(url.path)
        if self._route(path):
            return None
        if path == "/_pg/ws":
            return self._websocket(url)
        if path == "/_pg/file":
            return self._local_file(url)
        if path.startswith("/_pg/"):
            return self._static(STATIC_DIR, path[len("/_pg/"):])
        for prefix, directory in self.app._statics.items():
            if path.startswith(prefix + "/"):
                if not self._authed():
                    return self._send(403, "Forbidden")
                return self._static(Path(directory), path[len(prefix) + 1:])
        if path == "/favicon.ico" and not self.app.icon:
            return self._send(204)
        return self._index(url)

    def _static(self, root, rel):
        root = root.resolve()
        target = (root / rel).resolve()
        if root not in target.parents or not target.is_file():
            return self._send(404, "Not found", "text/plain")
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def _local_file(self, url):
        """A file of the user's disk, for ``fs.file_url`` (thumbnails, previews, media).

        Only for the app's own window (cookie-authenticated), streamed in chunks and with
        byte ranges so videos can seek."""
        if not self._authed():
            return self._send(403, "Forbidden", "text/plain")
        target = (parse_qs(url.query).get("p") or [""])[0]
        try:
            st = os.stat(target)
        except (OSError, ValueError):
            return self._send(404, "Not found", "text/plain")
        if not os.path.isfile(target):
            return self._send(404, "Not found", "text/plain")
        size = st.st_size
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
        if m and size:
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            elif m.group(2):
                start = max(0, size - int(m.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                return self.end_headers()
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        self.send_response(206 if m else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1 if size else 0))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "private, max-age=60")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "sandbox")  # an HTML file on disk must not run as the app
        if m:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD" or not size:
            return
        try:
            with open(target, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(left, 1 << 18))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (OSError, ConnectionError):
            self.close_connection = True

    def _index(self, url):
        query = parse_qs(url.query)
        token = self.app.token
        if token and query.get("_pgt", [None])[0] == token:
            rest = {k: v for k, v in query.items() if k != "_pgt"}
            location = url.path + ("?" + urlencode(rest, doseq=True) if rest else "")
            cookie = f"{self._cookie_name()}={token}; Path=/; HttpOnly; SameSite=Strict"
            return self._send(302, "", headers={"Location": location, "Set-Cookie": cookie})
        if not self._authed():
            return self._send(403, _FORBIDDEN)
        self._send(200, self.app._custom_page() if self.app._custom_page else self.app._index_html())

    def _websocket(self, url):
        if not self._authed():
            return self._send(403, "Forbidden", "text/plain")
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or "websocket" not in self.headers.get("Upgrade", "").lower():
            return self._send(400, "Expected a WebSocket upgrade", "text/plain")
        accept = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.wfile.flush()
        self.close_connection = True
        query = parse_qs(url.query)
        ws = WebSocket(self.rfile, self.connection)
        try:
            self.app._serve_socket(
                ws,
                sid=(query.get("sid") or [secrets.token_hex(8)])[0][:64],
                path=(query.get("path") or ["/"])[0],
                theme=(query.get("theme") or [None])[0],
            )
        finally:
            ws.close()


_FORBIDDEN = """<!doctype html><meta charset="utf-8"><title>ZePyGUI</title>
<body style="font:15px system-ui;display:grid;place-items:center;height:100vh;margin:0;background:#0b0d12;color:#a3a9b8">
<div style="text-align:center"><h2 style="color:#e8eaf0;margin:0 0 8px">This app is private</h2>
<p>Open it from the window launched by its Python script.</p></div></body>"""

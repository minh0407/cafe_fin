"""Private Docker relay: fixed public market GET only; never app data or secrets."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cafe_fin.records.market_http import DeadlineSocket, MarketError, download_direct

MAX_BYTES = 2 * 1024 * 1024
ERRORS = frozenset({
    "BLOCKED", "RATE_LIMITED", "NETWORK_ERROR", "HTTP_ERROR", "REDIRECT_BLOCKED",
    "UNSAFE_ADDRESS", "SOURCE_CHANGED", "HTML_TOO_LARGE", "WRONG_CONTENT_TYPE",
    "ENCODING_UNSUPPORTED", "INVALID_URL",
})


class Relay(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address=("0.0.0.0", 8080), fetch=download_direct, header_timeout=10):
        self.fetch = fetch
        self.header_timeout = header_timeout
        self.fetch_lock = threading.Lock()
        self.clients = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.clients.acquire(blocking=False):
            self.close_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.clients.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.clients.release()

    def handle_error(self, request, client_address):
        # Request/exception representations never enter Docker logs.
        pass


class RequestSocket(DeadlineSocket):
    def makefile(self, mode, buffering=-1):
        if mode != "rb":
            raise ValueError("Relay only creates a bounded input stream.")
        return super().makefile(mode)


class Handler(BaseHTTPRequestHandler):
    server_version = "CafeFinMarket"
    sys_version = ""

    def setup(self):
        # Absolute deadline also bounds slowly dripped incoming request headers.
        self.request = RequestSocket(self.request, time.monotonic() + self.server.header_timeout)
        super().setup()

    def log_message(self, format, *args):
        pass

    def reply(self, status, body, content_type="application/json", *, code=None, retry=None):
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        if code:
            self.send_header("X-Cafe-Fin-Market-Error", code)
        if retry:
            self.send_header("Retry-After", str(retry))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def error(self, status, code, retry=None):
        self.reply(status, json.dumps({"error": code}).encode(), code=code, retry=retry)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, b'{"status":"ok"}')
            return
        if self.path != "/source":
            self.error(404, "NOT_FOUND")
            return
        if (self.headers.get_all("Host") != ["market-source:8080"]
                or self.headers.get_all("X-Cafe-Fin-Market-Relay") != ["1"]
                or self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Length", "0") != "0"):
            self.error(403, "RELAY_REQUEST_REJECTED")
            return
        if os.environ.get("CAFE_FIN_MARKET_NETWORK", "1") != "1":
            self.error(503, "NETWORK_ERROR")
            return
        if not self.server.fetch_lock.acquire(blocking=False):
            self.error(429, "RATE_LIMITED", retry=5)
            return
        try:
            html = self.server.fetch()
            if not isinstance(html, str):
                raise MarketError("SOURCE_CHANGED", "Nguồn không đúng định dạng.")
            body = html.encode("utf-8")
            if len(body) > MAX_BYTES:
                raise MarketError("HTML_TOO_LARGE", "Nguồn vượt giới hạn.")
            self.reply(200, body, "text/html; charset=utf-8")
        except MarketError as exc:
            code = exc.code if exc.code in ERRORS else "SOURCE_CHANGED"
            retry = None
            if isinstance(getattr(exc, "retry_at", None), datetime) and exc.retry_at.tzinfo:
                retry = max(5, min(366 * 86400, int((exc.retry_at - datetime.now(timezone.utc)).total_seconds())))
            self.error(429 if code == "RATE_LIMITED" else 403 if code == "BLOCKED" else 502, code, retry)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            self.error(502, "NETWORK_ERROR")
        finally:
            self.server.fetch_lock.release()

    def do_HEAD(self):
        if self.path == "/health":
            self.reply(200, b'{"status":"ok"}')
        else:
            self.error(405, "METHOD_NOT_ALLOWED")

    def do_POST(self):
        self.error(405, "METHOD_NOT_ALLOWED")

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST
    do_CONNECT = do_POST
    do_OPTIONS = do_POST


if __name__ == "__main__":
    Relay().serve_forever(poll_interval=0.25)

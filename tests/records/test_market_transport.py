"""No WAN: synthetic responses, socketpair slow peer, bounded fake DNS."""

import io
import socket
import threading
import time
from datetime import datetime, timezone
from http.client import HTTPResponse

import pytest
from cafe_fin.records import market_http as http


class Response:
    def __init__(self, status=200, headers=None, body=b"<html></html>"):
        self.status = status
        self.headers = {"Content-Type": "text/html", **(headers or {})}
        self.body = io.BytesIO(body)

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, limit):
        return self.body.read(limit)


class Connection:
    sock = None

    def __init__(self, response):
        self.response, self.closed, self.headers = response, False, None

    def request(self, method, path, headers):
        assert method == "GET"
        self.headers = headers

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    "status,headers,body,code",
    [
        (403, {}, b"secret challenge", "BLOCKED"),
        (302, {"Location": "http://127.0.0.1"}, b"", "REDIRECT_BLOCKED"),
        (429, {"Retry-After": "900"}, b"", "RATE_LIMITED"),
        (500, {}, b"server raw private", "HTTP_ERROR"),
        (200, {"Content-Type": "application/javascript"}, b"x", "SOURCE_CHANGED"),
        (200, {"Content-Encoding": "gzip"}, b"x", "SOURCE_CHANGED"),
        (200, {"Content-Length": str(http.MAX_HTML_BYTES + 1)}, b"x", "SOURCE_CHANGED"),
        (200, {}, b"\xff", "SOURCE_CHANGED"),
        (200, {}, b"x" * (http.MAX_HTML_BYTES + 1), "SOURCE_CHANGED"),
    ],
)
def test_transport_rejects_response_without_leaking_body(status, headers, body, code):
    conn = Connection(Response(status, headers, body))
    with pytest.raises(http.MarketError) as error:
        http._download(conn, "/bang-gia-ca-phe/", time.monotonic() + 2)
    assert error.value.code == code
    assert "private" not in error.value.detail
    assert conn.closed
    if code == "RATE_LIMITED":
        assert error.value.retry_at > datetime.now(timezone.utc)


def test_user_agent_body_limit_and_identity():
    conn = Connection(Response(body=b"a" * http.MAX_HTML_BYTES))
    assert len(http._download(conn, "/", time.monotonic() + 2)) == http.MAX_HTML_BYTES
    assert conn.headers["User-Agent"].startswith("CafeFin-")
    assert conn.headers["Accept-Encoding"] == "identity"
    assert conn.closed


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1"])
def test_dns_private_addresses_rejected(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )
    with pytest.raises(http.MarketError) as error:
        http.resolve(http.SOURCE_HOST, 443, time.monotonic() + 1)
    assert error.value.code == "UNSAFE_ADDRESS"


def test_dns_timeout_does_not_spawn_unbounded_helpers(monkeypatch):
    release, finished = threading.Event(), threading.Event()
    calls = []

    def lookup(*a, **kw):
        calls.append(1)
        try:
            release.wait(2)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        finally:
            finished.set()

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    try:
        with pytest.raises(http.MarketError):
            http.resolve(http.SOURCE_HOST, 443, time.monotonic() + 0.05)
        with pytest.raises(http.MarketError, match="đang bận"):
            http.resolve(http.SOURCE_HOST, 443, time.monotonic() + 0.05)
        assert len(calls) == 1
    finally:
        release.set()
        assert finished.wait(2)


def test_slow_header_drip_respects_total_deadline():
    reader, writer = socket.socketpair()
    deadline = time.monotonic() + 0.15

    class SlowConnection(Connection):
        def __init__(self):
            self.sock = http.DeadlineSocket(reader, deadline)

        def request(self, *a, **kw):
            pass

        def getresponse(self):
            response = HTTPResponse(self.sock)
            response.begin()
            return response

        def close(self):
            reader.close()

    def drip():
        try:
            for byte in b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html/>":
                writer.sendall(bytes([byte]))
                time.sleep(0.025)
        except OSError:
            pass
        finally:
            writer.close()

    worker = threading.Thread(target=drip, daemon=True)
    worker.start()
    started = time.monotonic()
    with pytest.raises(http.MarketError) as error:
        http._download(SlowConnection(), "/", deadline)
    assert error.value.code == "NETWORK_ERROR"
    assert time.monotonic() - started < 0.5
    worker.join(1)


def test_relay_url_fixed_and_explicit_header(monkeypatch):
    monkeypatch.setenv("CAFE_FIN_MARKET_RELAY_URL", "http://127.0.0.1/source")
    with pytest.raises(http.MarketError) as error:
        http.download_html()
    assert error.value.code == "UNSAFE_ADDRESS"
    conn = Connection(Response())
    http._download(conn, "/source", time.monotonic() + 1, relay=True)
    assert conn.headers["X-Cafe-Fin-Market-Relay"] == "1"


def test_pinned_tls_connect_keeps_original_hostname(monkeypatch):
    calls = []

    class Raw:
        def settimeout(self, value):
            assert value > 0

        def close(self):
            pass

    class Context:
        def wrap_socket(self, raw, server_hostname):
            calls.append(server_hostname)
            return raw

    def connect(address, timeout):
        calls.append(address)
        assert timeout > 0
        return Raw()

    monkeypatch.setattr(socket, "create_connection", connect)
    conn = http.PinnedHTTPS(http.SOURCE_HOST, "8.8.8.8", time.monotonic() + 1)
    conn._context = Context()
    conn.connect()
    assert calls == [("8.8.8.8", 443), http.SOURCE_HOST]

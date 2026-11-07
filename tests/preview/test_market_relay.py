"""Real loopback sockets and synthetic provider; no WAN or user data."""

import http.client
import importlib.util
import json
import socket
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cafe_fin.records.market_http import MarketError

spec = importlib.util.spec_from_file_location(
    "cafe_fin_market_relay_test", Path(__file__).resolve().parents[2] / "scripts/market_relay.py"
)
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)
HEADERS = {"Host": "market-source:8080", "X-Cafe-Fin-Market-Relay": "1"}


@contextmanager
def serve(monkeypatch, fetch, **kwargs):
    monkeypatch.setenv("CAFE_FIN_MARKET_NETWORK", "1")
    server = relay.Relay(("127.0.0.1", 0), fetch=fetch, **kwargs)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()


def call(server, method="GET", path="/source", headers=None, body=None):
    client = http.client.HTTPConnection(*server.server_address, timeout=2)
    try:
        client.request(method, path, headers=HEADERS if headers is None else headers, body=body)
        response = client.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        client.close()


def test_fixed_route_headers_methods_and_health_make_no_accidental_fetch(monkeypatch):
    calls = []

    def fetch():
        calls.append(True)
        return "<html>Giá tổng hợp</html>"

    with serve(monkeypatch, fetch) as server:
        assert call(server, path="/health", headers={})[0] == 200
        assert call(server, "HEAD", "/health", headers={})[0] == 200
        for method in ("POST", "PUT", "DELETE", "CONNECT", "OPTIONS"):
            assert call(server, method)[0] == 405
        for path in ("/source?url=https://example.com", "/other", "http://example.com/source"):
            assert call(server, path=path)[0] == 404
        for headers in ({}, {**HEADERS, "Host": "127.0.0.1"},
                        {**HEADERS, "X-Cafe-Fin-Market-Relay": "0"}):
            assert call(server, headers=headers)[0] == 403
        assert call(server, body=b"not-a-get-body")[0] == 403
        assert calls == []
        status, headers, body = call(server)
        assert status == 200 and body.decode() == "<html>Giá tổng hợp</html>"
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert not any(key.lower().startswith("access-control-") for key in headers)
        assert calls == [True]


@pytest.mark.parametrize("code,status", [("BLOCKED", 403), ("RATE_LIMITED", 429),
                                        ("UNSAFE_ADDRESS", 502), ("UNKNOWN_CODE", 502)])
def test_only_sanitized_errors_and_bounded_retry_escape(monkeypatch, code, status):
    def fetch():
        raise MarketError(code, "synthetic-private-detail", datetime.now(timezone.utc) + timedelta(minutes=6))

    with serve(monkeypatch, fetch) as server:
        actual, headers, body = call(server)
        expected = code if code != "UNKNOWN_CODE" else "SOURCE_CHANGED"
        assert actual == status and json.loads(body) == {"error": expected}
        assert headers["X-Cafe-Fin-Market-Error"] == expected
        assert 5 <= int(headers["Retry-After"]) <= 366 * 86400
        assert b"synthetic-private-detail" not in body


def test_disabled_gate_and_oversized_or_nontext_source(monkeypatch):
    calls = []

    def fetch():
        calls.append(True)
        return "x" * (relay.MAX_BYTES + 1)

    with serve(monkeypatch, fetch) as server:
        monkeypatch.setenv("CAFE_FIN_MARKET_NETWORK", "0")
        assert call(server)[0] == 503 and calls == []
        monkeypatch.setenv("CAFE_FIN_MARKET_NETWORK", "1")
        assert call(server)[1]["X-Cafe-Fin-Market-Error"] == "HTML_TOO_LARGE"
        server.fetch = lambda: b"unsupported"
        assert call(server)[1]["X-Cafe-Fin-Market-Error"] == "SOURCE_CHANGED"


def test_one_fetch_does_not_block_health_and_parallel_fetch_is_rejected(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    result = []

    def fetch():
        entered.set()
        assert release.wait(2)
        return "<html>synthetic</html>"

    with serve(monkeypatch, fetch) as server:
        thread = threading.Thread(target=lambda: result.append(call(server)), daemon=True)
        thread.start()
        try:
            assert entered.wait(1)
            assert call(server)[0] == 429
            assert call(server, path="/health", headers={})[0] == 200
        finally:
            release.set()
            thread.join(2)
        assert not thread.is_alive() and result[0][0] == 200


def test_absolute_header_deadline_closes_a_slow_drip_client(monkeypatch):
    calls = []
    with serve(monkeypatch, lambda: calls.append(True) or "never", header_timeout=0.15) as server:
        client = socket.create_connection(server.server_address, timeout=1)
        started = time.monotonic()
        try:
            for byte in b"GET /source HTTP/1.1\r\nHost: market-source:8080\r\n":
                try:
                    client.sendall(bytes([byte]))
                except OSError:
                    break
                time.sleep(0.02)
            try:
                assert client.recv(1024) == b""
            except (ConnectionAbortedError, ConnectionResetError):
                # Windows may report an aborted connection instead of EOF.
                pass
            assert time.monotonic() - started < 1
            assert calls == []
        finally:
            client.close()

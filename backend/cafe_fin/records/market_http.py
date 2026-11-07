"""Fixed-source, bounded public HTTPS transport. No redirect or executable content."""

import io
import ipaddress
import os
import queue
import socket
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPConnection, HTTPException, HTTPSConnection

SOURCE_URL = "https://banggianongsan.com/bang-gia-ca-phe/"
SOURCE_HOST = "banggianongsan.com"
RELAY_URL = "http://market-source:8080/source"
MAX_HTML_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 8
_resolver_slot = threading.BoundedSemaphore(1)


class MarketError(ValueError):
    def __init__(self, code, detail, retry_at=None):
        super().__init__(detail)
        self.code, self.detail, self.retry_at = code, detail, retry_at


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise MarketError("NETWORK_ERROR", "Nguồn phản hồi quá thời gian chờ.")
    return value


def resolve(host, port, deadline, *, public=True):
    # One bounded daemon is solely an OS DNS transport helper; it never owns DB,
    # runtime or callbacks. A stuck system resolver cannot accumulate threads.
    if not _resolver_slot.acquire(blocking=False):
        raise MarketError("NETWORK_ERROR", "Bộ phân giải tên miền đang bận.")
    result = queue.Queue(maxsize=1)

    def lookup():
        try:
            result.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except OSError:
            result.put(None)
        finally:
            _resolver_slot.release()

    threading.Thread(target=lookup, name="cafe-fin-market-dns", daemon=True).start()
    try:
        values = result.get(timeout=min(2, remaining(deadline)))
    except queue.Empty:
        raise MarketError("NETWORK_ERROR", "Phân giải tên miền quá thời gian chờ.") from None
    addresses = list(dict.fromkeys(value[4][0] for value in values or []))
    if not addresses:
        raise MarketError("NETWORK_ERROR", "Không phân giải được tên miền nguồn.")
    if public and any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise MarketError("UNSAFE_ADDRESS", "Nguồn phân giải tới địa chỉ không công khai.")
    remaining(deadline)
    return addresses


class PinnedHTTPS(HTTPSConnection):
    def __init__(self, host, address, deadline):
        super().__init__(host, timeout=remaining(deadline), context=ssl.create_default_context())
        self.address, self.deadline = address, deadline

    def connect(self):
        raw = socket.create_connection((self.address, 443), timeout=remaining(self.deadline))
        try:
            raw.settimeout(remaining(self.deadline))
            self.sock = DeadlineSocket(
                self._context.wrap_socket(raw, server_hostname=self.host), self.deadline
            )
        except BaseException:
            raw.close()
            raise


class PinnedRelay(HTTPConnection):
    def __init__(self, address, deadline):
        super().__init__("market-source", 8080, timeout=remaining(deadline))
        self.address, self.deadline = address, deadline

    def connect(self):
        self.sock = DeadlineSocket(
            socket.create_connection((self.address, 8080), remaining(self.deadline)), self.deadline
        )


class DeadlineRaw(io.RawIOBase):
    def __init__(self, raw, sock, deadline):
        self.raw, self.sock, self.deadline = raw, sock, deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(remaining(self.deadline))
        return self.raw.readinto(buffer)

    def close(self):
        self.raw.close()
        super().close()


class DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def __getattr__(self, key):
        return getattr(self.sock, key)

    def sendall(self, data):
        self.sock.settimeout(remaining(self.deadline))
        return self.sock.sendall(data)

    def makefile(self, mode):
        return io.BufferedReader(
            DeadlineRaw(self.sock.makefile(mode, buffering=0), self.sock, self.deadline)
        )


def retry_time(value, now):
    try:
        return now + timedelta(seconds=max(300, min(int(value), 366 * 86400)))
    except (ValueError, TypeError, OverflowError):
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                raise ValueError()
            return max(now + timedelta(minutes=5), parsed)
        except (ValueError, TypeError, OverflowError):
            return now + timedelta(minutes=15)


def _download(connection, path, deadline, *, relay=False):
    try:
        connection.request(
            "GET",
            path,
            headers={
                "User-Agent": "CafeFin-MarketPrice/1.0",
                "Accept": "text/html",
                "Accept-Encoding": "identity",
                "Connection": "close",
                **({"X-Cafe-Fin-Market-Relay": "1"} if relay else {}),
            },
        )
        if connection.sock:
            connection.sock.settimeout(remaining(deadline))
        response = connection.getresponse()
        if response.status == 429:
            raise MarketError(
                "RATE_LIMITED",
                "Nguồn yêu cầu giảm tần suất.",
                retry_time(response.getheader("Retry-After"), datetime.now(timezone.utc)),
            )
        if response.status in (401, 403):
            raise MarketError("BLOCKED", "Nguồn chặn truy cập; chưa lấy được giá.")
        if 300 <= response.status < 400:
            raise MarketError("REDIRECT_BLOCKED", "Nguồn chuyển hướng; không tự đi theo.")
        if response.status != 200:
            code = response.getheader("X-Cafe-Fin-Market-Error") if relay else None
            allowed = {
                "BLOCKED",
                "RATE_LIMITED",
                "NETWORK_ERROR",
                "HTTP_ERROR",
                "REDIRECT_BLOCKED",
                "UNSAFE_ADDRESS",
                "SOURCE_CHANGED",
            }
            raise MarketError(
                code if code in allowed else "HTTP_ERROR", "Không tải được HTML từ nguồn giá."
            )
        if response.getheader("Content-Type", "").split(";")[0].strip().lower() != "text/html":
            raise MarketError("SOURCE_CHANGED", "Nguồn không trả HTML.")
        if response.getheader("Content-Encoding", "identity").lower() not in ("", "identity"):
            raise MarketError("SOURCE_CHANGED", "Nguồn trả dữ liệu nén ngoài hợp đồng tải.")
        size = response.getheader("Content-Length")
        if size and (not size.isdigit() or int(size) > MAX_HTML_BYTES):
            raise MarketError("SOURCE_CHANGED", "Trang vượt giới hạn 2 MiB.")
        chunks, total = [], 0
        while True:
            timeout = remaining(deadline)
            if connection.sock:
                connection.sock.settimeout(timeout)
            data = response.read1(min(65536, MAX_HTML_BYTES + 1 - total))
            if not data:
                break
            total += len(data)
            if total > MAX_HTML_BYTES:
                raise MarketError("SOURCE_CHANGED", "Trang vượt giới hạn 2 MiB.")
            chunks.append(data)
        remaining(deadline)
        try:
            return b"".join(chunks).decode("utf-8-sig")
        except UnicodeDecodeError:
            raise MarketError("SOURCE_CHANGED", "Nguồn không phải HTML UTF-8.") from None
    except (OSError, TimeoutError, HTTPException):
        raise MarketError("NETWORK_ERROR", "Không tải được nguồn qua kết nối hợp lệ.") from None
    finally:
        connection.close()


def download_direct() -> str:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    addresses = resolve(SOURCE_HOST, 443, deadline)
    return _download(
        PinnedHTTPS(SOURCE_HOST, addresses[0], deadline), "/bang-gia-ca-phe/", deadline
    )


def download_html() -> str:
    relay = os.getenv("CAFE_FIN_MARKET_RELAY_URL", "")
    if not relay:
        return download_direct()
    if relay != RELAY_URL:
        raise MarketError("UNSAFE_ADDRESS", "Cấu hình relay nguồn giá không hợp lệ.")
    deadline = time.monotonic() + TIMEOUT_SECONDS
    addresses = resolve("market-source", 8080, deadline, public=False)
    return _download(PinnedRelay(addresses[0], deadline), "/source", deadline, relay=True)

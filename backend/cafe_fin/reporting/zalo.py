"""Official OA GMF outbound adapter. No personal-account emulation or webhook."""

import json
import re
import socket
import ssl
import time
import uuid
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from cafe_fin.core.errors import CoreError


class SecretStore(Protocol):
    """Foundation adapter must atomically replace one OS-protected credential value."""

    available: bool

    def has(self, key: str) -> bool: ...
    def get(self, key: str) -> dict | None: ...
    def put(self, key: str, value: dict) -> None: ...


class MissingSecrets:
    available = False

    def has(self, key):
        return False

    def get(self, key):
        return None

    def put(self, key, value):
        raise CoreError("SECRET_STORE_UNAVAILABLE", "Kho bí mật Windows chưa được kết nối.", 503)


@dataclass
class DeliveryError(Exception):
    code: str
    unknown: bool = False

    def __str__(self):
        return self.code


class Transport(Protocol):
    def refresh(self, credential: dict) -> dict: ...
    def verify(self, token: str, oa_id: str, group_id: str) -> None: ...
    def send_text(self, token: str, group_id: str, text: str) -> str: ...
    def upload(self, token: str, content: bytes, filename: str) -> str: ...
    def send_file(self, token: str, group_id: str, upload_token: str) -> str: ...
    def reconcile(self, token: str, group_id: str, text: str) -> str | None: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward credentials across redirects, even to another HTTPS URL.
        return None


class OfficialGMF:
    BASE = "https://openapi.zalo.me"
    TOKEN = "https://oauth.zaloapp.com/v4/oa/access_token"

    def __init__(self, *, upload_verified=False):
        # File-message API is documented. Upload capability must be confirmed for
        # the real OA/app before enabling this separate optional operation.
        self.upload_verified = upload_verified
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _request(self, url, *, token=None, body=None, headers=None, uncertain=False):
        if not (url.startswith(self.BASE + "/") or url == self.TOKEN):
            raise DeliveryError("ZALO_ENDPOINT_INVALID")
        values = {"Accept": "application/json", **(headers or {})}
        if token:
            values["access_token"] = token
        request = Request(
            url, data=body, headers=values, method="POST" if body is not None else "GET"
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise DeliveryError("ZALO_RESPONSE_INVALID", unknown=uncertain)
            result = json.loads(raw)
        except DeliveryError:
            raise
        except HTTPError:
            # An HTTP gateway status cannot prove a send was not accepted.
            raise DeliveryError("ZALO_HTTP_ERROR", unknown=uncertain) from None
        except (URLError, TimeoutError, socket.timeout, OSError, ssl.SSLError):
            raise DeliveryError("ZALO_NETWORK_ERROR", unknown=uncertain) from None
        except (ValueError, TypeError):
            raise DeliveryError("ZALO_RESPONSE_INVALID", unknown=uncertain) from None
        if not isinstance(result, dict):
            raise DeliveryError("ZALO_RESPONSE_INVALID", unknown=uncertain)
        if "error" in result and type(result["error"]) is not int:
            raise DeliveryError("ZALO_RESPONSE_INVALID", unknown=uncertain)
        if "error" in result and result["error"] != 0:
            # Never persist/echo provider error.message, token or raw response.
            raise DeliveryError("ZALO_API_REJECTED")
        return result

    def refresh(self, credential):
        result = self._request(
            self.TOKEN,
            body=urlencode(
                {
                    "app_id": credential["app_id"],
                    "refresh_token": credential["refresh_token"],
                    "grant_type": "refresh_token",
                }
            ).encode(),
            uncertain=True,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "secret_key": credential["app_secret"],
            },
        )
        if not all(
            isinstance(result.get(x), str) and result[x] for x in ("access_token", "refresh_token")
        ):
            raise DeliveryError("ZALO_REFRESH_INVALID", unknown=True)
        try:
            seconds = int(result["expires_in"])
            if not 60 < seconds <= 7 * 86400:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise DeliveryError("ZALO_REFRESH_INVALID", unknown=True) from None
        return {
            **credential,
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
            "expires_at": int(time.time()) + seconds,
            "refresh_state": "READY",
        }

    def verify(self, token, oa_id, group_id):
        oa = self._request(self.BASE + "/v2.0/oa/getoa", token=token)
        info = oa.get("data", {})
        if not isinstance(info, dict):
            raise DeliveryError("ZALO_RESPONSE_INVALID")
        if str(info.get("oaid", info.get("oa_id", ""))) != oa_id:
            raise DeliveryError("ZALO_OA_MISMATCH")
        group = self._request(
            self.BASE + "/v3.0/oa/group/getgroup?" + urlencode({"group_id": group_id}), token=token
        )
        data = group.get("data", {})
        if not isinstance(data, dict) or not isinstance(data.get("group_info"), dict):
            raise DeliveryError("ZALO_RESPONSE_INVALID")
        info = data["group_info"]
        if info.get("group_id") != group_id or info.get("status") != "enabled":
            raise DeliveryError("ZALO_GROUP_UNAVAILABLE")

    def _send(self, token, group_id, message):
        result = self._request(
            self.BASE + "/v3.0/oa/group/message",
            token=token,
            body=json.dumps(
                {"recipient": {"group_id": group_id}, "message": message}, ensure_ascii=False
            ).encode(),
            headers={"Content-Type": "application/json"},
            uncertain=True,
        )
        data = result.get("data", {})
        if not isinstance(data, dict):
            raise DeliveryError("ZALO_RESPONSE_INVALID", unknown=True)
        message_id = data.get("message_id")
        if (
            result.get("error") != 0
            or data.get("group_id") != group_id
            or not isinstance(message_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", message_id)
        ):
            raise DeliveryError("ZALO_RECEIPT_INVALID", unknown=True)
        return message_id

    def send_text(self, token, group_id, text):
        return self._send(token, group_id, {"text": text})

    def upload(self, token, content, filename):
        if not self.upload_verified:
            raise DeliveryError("ZALO_UPLOAD_CAPABILITY_UNVERIFIED")
        if len(content) > 5 * 1024 * 1024 or not re.fullmatch(
            r"CafeFin-summary\.(pdf|xlsx|txt)", filename
        ):
            raise DeliveryError("ZALO_ATTACHMENT_INVALID")
        boundary = "CafeFin" + uuid.uuid4().hex
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode()
        body += content + f"\r\n--{boundary}--\r\n".encode()
        result = self._request(
            self.BASE + "/v2.0/oa/upload/file",
            token=token,
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        value = result.get("data", {}).get("token")
        if not isinstance(value, str) or not value:
            raise DeliveryError("ZALO_UPLOAD_INVALID")
        return value

    def send_file(self, token, group_id, upload_token):
        return self._send(
            token, group_id, {"attachment": {"type": "file", "payload": {"token": upload_token}}}
        )

    def reconcile(self, token, group_id, text):
        # Matching text/time alone is not conclusive (same totals can be resent by
        # another sender). This adapter deliberately does not manufacture a receipt.
        # UNKNOWN stays blocked pending a stronger receipt/correlation capability.
        self._request(
            self.BASE
            + "/v3.0/oa/group/conversation?"
            + urlencode({"group_id": group_id, "offset": 0, "count": 100}),
            token=token,
        )
        return None


def access_token(service, config):
    key = service.secret_key(config)
    try:
        credential = service.secrets.get(key)
    except Exception:
        raise DeliveryError("ZALO_UNCONFIGURED") from None
    if not credential:
        raise DeliveryError("ZALO_UNCONFIGURED")
    if credential.get("refresh_state") in {"REFRESHING", "REAUTH_REQUIRED"}:
        raise DeliveryError("ZALO_REAUTH_REQUIRED")
    if credential.get("access_token") and credential.get("expires_at", 0) > time.time() + 120:
        return credential["access_token"]
    # Refresh token is single-use. Persist intent before network; crash/timeout
    # cannot silently reuse a token whose rotation might already have happened.
    try:
        service.secrets.put(key, {**credential, "refresh_state": "REFRESHING"})
    except Exception:
        raise DeliveryError("ZALO_UNCONFIGURED") from None
    try:
        replacement = service.transport.refresh(credential)
        service.secrets.put(key, replacement)
        return replacement["access_token"]
    except BaseException:
        try:
            service.secrets.put(key, {**credential, "refresh_state": "REAUTH_REQUIRED"})
        except Exception:
            # The durable REFRESHING marker still prevents unsafe token reuse.
            pass
        raise

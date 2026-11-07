"""Bounded official Telegram Bot API client. Never expose endpoint/error contents."""

import json
import re
import socket
import ssl
import uuid
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from cafe_fin.core.errors import CoreError

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_TEXT_UNITS = 4096
MAX_RETRY_AFTER = 3600
MAX_ID = 2**52 - 1
PROVIDER = "telegram"


class SecretStore(Protocol):
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
    retry_after: int | None = None

    def __str__(self):
        return self.code


@dataclass(frozen=True)
class MessageReceipt:
    chat_id: str
    message_id: int


def positive_id(value):
    return type(value) is int and 0 < value <= MAX_ID


def valid_chat(value):
    return (
        isinstance(value, str)
        and bool(re.fullmatch(r"-[1-9][0-9]{0,15}", value))
        and -MAX_ID <= int(value) < 0
    )


def token_bot_id(token):
    if not isinstance(token, str) or not re.fullmatch(
        r"[1-9][0-9]{0,15}:[A-Za-z0-9_-]{30,256}", token
    ):
        raise DeliveryError("TELEGRAM_TOKEN_INVALID")
    identity = token.split(":", 1)[0]
    if not positive_id(int(identity)):
        raise DeliveryError("TELEGRAM_TOKEN_INVALID")
    return identity


def truncate_text(text):
    if not isinstance(text, str) or not text:
        raise DeliveryError("TELEGRAM_TEXT_INVALID")
    try:
        size = len(text.encode("utf-16-le")) // 2
    except UnicodeError:
        raise DeliveryError("TELEGRAM_TEXT_INVALID") from None
    if size <= MAX_TEXT_UNITS:
        return text
    units, output = 0, []
    for char in text:
        width = 2 if ord(char) > 0xFFFF else 1
        if units + width > MAX_TEXT_UNITS - 1:
            break
        output.append(char)
        units += width
    return "".join(output) + "…"


def receipt_valid(receipt, chat_id):
    return (
        isinstance(receipt, MessageReceipt)
        and receipt.chat_id == chat_id
        and valid_chat(chat_id)
        and positive_id(receipt.message_id)
    )


def stored_receipt(message_id, receipt_chat_id, chat_id):
    return (
        valid_chat(chat_id)
        and receipt_chat_id == chat_id
        and isinstance(message_id, str)
        and bool(re.fullmatch(r"[1-9][0-9]{0,15}", message_id))
        and positive_id(int(message_id))
    )


class Transport(Protocol):
    def verify(self, token: str, chat_id: str, bot_id: str, *, documents: bool = False) -> str: ...
    def send_text(self, token: str, chat_id: str, text: str, bot_id: str) -> MessageReceipt: ...
    def send_document(
        self, token: str, chat_id: str, content: bytes, filename: str, bot_id: str
    ) -> MessageReceipt: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OfficialTelegram:
    BASE = "https://api.telegram.org"
    METHODS = frozenset({"getMe", "getChat", "getChatMember", "sendMessage", "sendDocument"})

    def __init__(self):
        self.opener = build_opener(
            ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context())
        )

    def _request(self, method, token, parameters, *, document=None, uncertain=False):
        if method not in self.METHODS:
            raise DeliveryError("TELEGRAM_ENDPOINT_INVALID")
        token_bot_id(token)
        headers = {"Accept": "application/json"}
        if document is None:
            body = json.dumps(parameters, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            content, filename = document
            boundary = "CafeFin" + uuid.uuid4().hex
            chunks = []
            for name, value in parameters.items():
                chunks.append(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
                )
            media = (
                "application/pdf"
                if filename.endswith(".pdf")
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            chunks += [
                f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{filename}"\r\nContent-Type: {media}\r\n\r\n'.encode(),
                content,
                f"\r\n--{boundary}--\r\n".encode(),
            ]
            body = b"".join(chunks)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        request = Request(
            f"{self.BASE}/bot{token}/{method}", data=body, headers=headers, method="POST"
        )
        status = 200
        try:
            try:
                with self.opener.open(request, timeout=20) as response:
                    status = getattr(response, "status", 200)
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
            except HTTPError as exc:
                status = exc.code
                try:
                    raw = exc.read(MAX_RESPONSE_BYTES + 1)
                finally:
                    exc.close()
            if 300 <= status < 400:
                raise DeliveryError("TELEGRAM_REDIRECT", unknown=uncertain)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise DeliveryError("TELEGRAM_RESPONSE_INVALID", unknown=uncertain)
            result = json.loads(raw)
            if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                raise DeliveryError("TELEGRAM_RESPONSE_INVALID", unknown=uncertain)
            if result["ok"] is False:
                code = result.get("error_code")
                if type(code) is not int or not 400 <= code < 500 or status not in {200, code}:
                    raise DeliveryError("TELEGRAM_HTTP_ERROR", unknown=uncertain)
                if code == 429:
                    parameters = result.get("parameters")
                    delay = parameters.get("retry_after") if isinstance(parameters, dict) else None
                    if delay is None:
                        delay = 60
                    if type(delay) is not int or not 1 <= delay <= MAX_RETRY_AFTER:
                        # Never shorten a server-mandated delay. Out-of-policy
                        # delays require review rather than an early retry.
                        raise DeliveryError("TELEGRAM_RETRY_REVIEW_REQUIRED")
                    raise DeliveryError("TELEGRAM_RATE_LIMITED", retry_after=delay)
                raise DeliveryError(
                    {401: "TELEGRAM_UNAUTHORIZED", 403: "TELEGRAM_FORBIDDEN"}.get(
                        code, "TELEGRAM_API_REJECTED"
                    )
                )
            if status != 200 or not isinstance(result.get("result"), dict):
                raise DeliveryError(
                    "TELEGRAM_HTTP_ERROR" if status != 200 else "TELEGRAM_RESPONSE_INVALID",
                    unknown=uncertain,
                )
            return result["result"]
        except DeliveryError:
            raise
        except (URLError, TimeoutError, socket.timeout, OSError, ssl.SSLError):
            raise DeliveryError("TELEGRAM_NETWORK_ERROR", unknown=uncertain) from None
        except (ValueError, TypeError, RecursionError):
            raise DeliveryError("TELEGRAM_RESPONSE_INVALID", unknown=uncertain) from None

    def verify(self, token, chat_id, bot_id, *, documents=False):
        if not valid_chat(chat_id) or token_bot_id(token) != bot_id:
            raise DeliveryError("TELEGRAM_CONFIG_CHANGED")
        bot = self._request("getMe", token, {})
        if (
            not positive_id(bot.get("id"))
            or bot.get("is_bot") is not True
            or str(bot["id"]) != bot_id
        ):
            raise DeliveryError("TELEGRAM_BOT_MISMATCH")
        chat = self._request("getChat", token, {"chat_id": chat_id})
        if (
            type(chat.get("id")) is not int
            or str(chat["id"]) != chat_id
            or chat.get("type") not in {"group", "supergroup"}
            or chat.get("is_direct_messages") is True
        ):
            raise DeliveryError("TELEGRAM_CHAT_INVALID")
        member = self._request("getChatMember", token, {"chat_id": chat_id, "user_id": bot["id"]})
        user = member.get("user")
        if (
            not isinstance(user, dict)
            or type(user.get("id")) is not int
            or str(user["id"]) != bot_id
            or user.get("is_bot") is not True
        ):
            raise DeliveryError("TELEGRAM_MEMBERSHIP_DENIED")
        status = member.get("status")
        if status in {"creator", "administrator"}:
            if member.get("is_anonymous") is True:
                # Anonymous admin sends may report sender_chat/fake from. This
                # client requires a positively correlated bot sender receipt.
                raise DeliveryError("TELEGRAM_MEMBERSHIP_DENIED")
            return bot_id
        if status == "restricted" and member.get("is_member") is True:
            permissions = member
        elif status == "member":
            permissions = chat.get("permissions", {})
        else:
            raise DeliveryError("TELEGRAM_MEMBERSHIP_DENIED")
        if (
            not isinstance(permissions, dict)
            or permissions.get("can_send_messages") is not True
            or (documents and permissions.get("can_send_documents") is not True)
        ):
            raise DeliveryError("TELEGRAM_SEND_DENIED")
        return bot_id

    def _receipt(self, result, chat_id, bot_id, *, document=False):
        chat, user = result.get("chat"), result.get("from")
        if (
            not isinstance(chat, dict)
            or type(chat.get("id")) is not int
            or str(chat["id"]) != chat_id
            or chat.get("type") not in {"group", "supergroup"}
            or not positive_id(result.get("message_id"))
            or not isinstance(user, dict)
            or user.get("is_bot") is not True
            or type(user.get("id")) is not int
            or str(user["id"]) != bot_id
        ):
            raise DeliveryError("TELEGRAM_RECEIPT_INVALID", unknown=True)
        if document:
            info = result.get("document")
            if not isinstance(info, dict) or any(
                not isinstance(info.get(key), str) or not 1 <= len(info[key]) <= 2048
                for key in ("file_id", "file_unique_id")
            ):
                raise DeliveryError("TELEGRAM_RECEIPT_INVALID", unknown=True)
        return MessageReceipt(chat_id, result["message_id"])

    def send_text(self, token, chat_id, text, bot_id):
        if not valid_chat(chat_id) or token_bot_id(token) != bot_id:
            raise DeliveryError("TELEGRAM_CONFIG_CHANGED")
        if truncate_text(text) != text:
            raise DeliveryError("TELEGRAM_TEXT_INVALID")
        result = self._request(
            "sendMessage",
            token,
            {"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}},
            uncertain=True,
        )
        return self._receipt(result, chat_id, bot_id)

    def send_document(self, token, chat_id, content, filename, bot_id):
        if not valid_chat(chat_id) or token_bot_id(token) != bot_id:
            raise DeliveryError("TELEGRAM_CONFIG_CHANGED")
        if (
            not isinstance(content, bytes)
            or not 0 < len(content) <= MAX_DOCUMENT_BYTES
            or not isinstance(filename, str)
            or not re.fullmatch(r"CafeFin-summary\.(pdf|xlsx)", filename)
        ):
            raise DeliveryError("TELEGRAM_ATTACHMENT_INVALID")
        result = self._request(
            "sendDocument",
            token,
            {"chat_id": chat_id},
            document=(content, filename),
            uncertain=True,
        )
        return self._receipt(result, chat_id, bot_id, document=True)


def access_token(service, config):
    try:
        credential = service.secrets.get(service.secret_key(config))
        token = credential.get("bot_token") if isinstance(credential, dict) else None
        if token_bot_id(token) != config.get("bot_id"):
            raise DeliveryError("TELEGRAM_UNCONFIGURED")
        return token
    except Exception:
        raise DeliveryError("TELEGRAM_UNCONFIGURED") from None

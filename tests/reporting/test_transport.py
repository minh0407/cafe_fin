"""Offline contract tests; all credentials, provider responses and files are synthetic."""

import io
import json
import socket
import ssl
import traceback
from email import policy
from email.parser import BytesParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request

import pytest
from cafe_fin.reporting.telegram import (
    MAX_DOCUMENT_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_RETRY_AFTER,
    MAX_TEXT_UNITS,
    DeliveryError,
    OfficialTelegram,
    truncate_text,
)

TOKEN = "123456:" + "A" * 35
BOT_ID = "123456"
CHAT_ID = "-1001234567890"
SECRET = "SYNTHETIC-provider-secret-do-not-echo"


class Response(io.BytesIO):
    status = 200

    def __init__(self, content):
        super().__init__(content)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests, self.timeouts, self.opened = [], [], []

    def open(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        assert self.responses, "Unexpected additional network request"
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        response = Response(result if isinstance(result, bytes) else json.dumps(result).encode())
        self.opened.append(response)
        return response


def adapter_for(*responses):
    adapter = OfficialTelegram()
    adapter.opener = Opener(*responses)
    return adapter


def successful(result):
    return {"ok": True, "result": result}


def bot():
    return {"id": int(BOT_ID), "is_bot": True, "first_name": "Synthetic CafeFin"}


def chat():
    return {
        "id": int(CHAT_ID),
        "type": "supergroup",
        "permissions": {"can_send_messages": True, "can_send_documents": True},
    }


def member():
    return {"status": "member", "user": bot()}


def message(*, document=False):
    result = {"message_id": 23, "chat": chat(), "from": bot(), "date": 1794000000}
    if document:
        result["document"] = {"file_id": "synthetic-file-1", "file_unique_id": "unique-file-1"}
    else:
        result["text"] = "Tổng hợp"
    return result


def send(adapter, *, document=False):
    if document:
        return adapter.send_document(
            TOKEN, CHAT_ID, b"synthetic summary", "CafeFin-summary.pdf", BOT_ID
        )
    return adapter.send_text(TOKEN, CHAT_ID, "Tổng hợp", BOT_ID)


def rejection(code, *, retry_after=None):
    result = {"ok": False, "error_code": code, "description": SECRET + TOKEN}
    if retry_after is not None:
        result["parameters"] = {"retry_after": retry_after}
    return result


def http_error(status, body=None):
    content = SECRET.encode() if body is None else json.dumps(body).encode()
    return HTTPError(
        "https://api.telegram.org/bot" + TOKEN + "/sendMessage",
        status,
        SECRET,
        {"Location": "https://example.invalid/" + SECRET},
        io.BytesIO(content),
    )


def assert_safe(error):
    rendered = str(error) + repr(error) + "".join(traceback.format_exception(error))
    for sensitive in (TOKEN, SECRET, "https://api.telegram.org", "example.invalid"):
        assert sensitive not in rendered
    assert error.code.startswith("TELEGRAM_")


def assert_request(request, method):
    endpoint = urlsplit(request.full_url)
    assert endpoint.scheme == "https" and endpoint.netloc == "api.telegram.org"
    assert endpoint.path == "/bot" + TOKEN + "/" + method
    assert not endpoint.query and not endpoint.fragment
    assert request.get_method() == "POST"
    assert TOKEN not in repr(dict(request.header_items()))


def test_verify_only_reads_bot_group_and_self_membership_with_finite_timeout():
    adapter = adapter_for(successful(bot()), successful(chat()), successful(member()))
    assert adapter.verify(TOKEN, CHAT_ID, BOT_ID, documents=True) == BOT_ID
    assert len(adapter.opener.requests) == 3
    for request, method in zip(
        adapter.opener.requests, ("getMe", "getChat", "getChatMember"), strict=True
    ):
        assert_request(request, method)
        assert request.get_header("Content-type").startswith("application/json")
    bodies = [json.loads(request.data) for request in adapter.opener.requests]
    assert bodies[0] == {}
    assert str(bodies[1]["chat_id"]) == CHAT_ID
    assert str(bodies[2]["chat_id"]) == CHAT_ID
    assert type(bodies[2]["user_id"]) is int and bodies[2]["user_id"] == int(BOT_ID)
    assert all(0 < timeout <= 60 for timeout in adapter.opener.timeouts)


@pytest.mark.parametrize("status", ["member", "administrator", "restricted"])
@pytest.mark.parametrize("documents", [False, True])
def test_verify_accepts_minimal_rights_without_promoting_bot(status, documents):
    group, membership = chat(), member()
    membership["status"] = status
    if status == "administrator":
        group.pop("permissions")
        membership.update(can_promote_members=False, can_delete_messages=False)
    if status == "restricted":
        group["permissions"] = {"can_send_messages": False, "can_send_documents": False}
        membership.update(is_member=True, can_send_messages=True, can_send_documents=documents)
    if not documents and status == "member":
        group["permissions"].pop("can_send_documents")
    adapter = adapter_for(successful(bot()), successful(group), successful(membership))
    assert adapter.verify(TOKEN, CHAT_ID, BOT_ID, documents=documents) == BOT_ID


@pytest.mark.parametrize("documents", [False, True])
def test_anonymous_admin_is_denied_before_any_send(documents):
    membership = {**member(), "status": "administrator", "is_anonymous": True}
    adapter = adapter_for(successful(bot()), successful(chat()), successful(membership))
    with pytest.raises(DeliveryError, match="TELEGRAM_MEMBERSHIP_DENIED") as failure:
        adapter.verify(TOKEN, CHAT_ID, BOT_ID, documents=documents)
    assert failure.value.unknown is False
    assert len(adapter.opener.requests) == 3
    assert all("/send" not in request.full_url for request in adapter.opener.requests)


@pytest.mark.parametrize("status", ["left", "kicked", "unknown", None, True])
def test_verify_rejects_unsendable_membership(status):
    adapter = adapter_for(
        successful(bot()), successful(chat()), successful({**member(), "status": status})
    )
    with pytest.raises(DeliveryError) as failure:
        adapter.verify(TOKEN, CHAT_ID, BOT_ID)
    assert failure.value.unknown is False
    assert_safe(failure.value)


@pytest.mark.parametrize("is_member", [False, None, 1, "true"])
def test_restricted_bot_requires_explicit_membership(is_member):
    membership = {
        **member(),
        "status": "restricted",
        "is_member": is_member,
        "can_send_messages": True,
        "can_send_documents": True,
    }
    adapter = adapter_for(successful(bot()), successful(chat()), successful(membership))
    with pytest.raises(DeliveryError):
        adapter.verify(TOKEN, CHAT_ID, BOT_ID)


@pytest.mark.parametrize("status", ["member", "restricted"])
@pytest.mark.parametrize(
    "documents,permission", [(False, "can_send_messages"), (True, "can_send_documents")]
)
@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_verify_requires_explicit_boolean_send_rights(status, documents, permission, value):
    group, membership = chat(), member()
    membership["status"] = status
    if status == "restricted":
        membership.update(is_member=True, can_send_messages=True, can_send_documents=True)
        membership[permission] = value
    else:
        group["permissions"][permission] = value
    adapter = adapter_for(successful(bot()), successful(group), successful(membership))
    with pytest.raises(DeliveryError):
        adapter.verify(TOKEN, CHAT_ID, BOT_ID, documents=documents)


@pytest.mark.parametrize(
    "stage,field,value",
    [
        (0, "id", 999),
        (0, "id", BOT_ID),
        (0, "id", True),
        (0, "is_bot", False),
        (0, "is_bot", 1),
        (1, "id", -999),
        (1, "id", CHAT_ID),
        (1, "type", "private"),
        (1, "type", "channel"),
        (1, "is_direct_messages", True),
        (2, "user", {"id": 999, "is_bot": True}),
        (2, "user", {"id": int(BOT_ID), "is_bot": False}),
        (2, "user", {"id": BOT_ID, "is_bot": True}),
    ],
)
def test_verify_rejects_wrong_bot_or_group(stage, field, value):
    results = [bot(), chat(), member()]
    results[stage][field] = value
    adapter = adapter_for(*(successful(result) for result in results))
    with pytest.raises(DeliveryError) as failure:
        adapter.verify(TOKEN, CHAT_ID, BOT_ID)
    assert len(adapter.opener.requests) <= stage + 1
    assert failure.value.unknown is False
    assert_safe(failure.value)


@pytest.mark.parametrize("chat_type", ["group", "supergroup"])
def test_plain_text_send_preserves_payload_and_receipt(chat_type):
    receipt = message()
    receipt["chat"]["type"] = chat_type
    adapter = adapter_for(successful(receipt))
    text = "Tổng hợp <b>nguyên văn</b> & https://example.invalid"
    result = adapter.send_text(TOKEN, CHAT_ID, text, BOT_ID)
    assert result.chat_id == CHAT_ID
    assert type(result.message_id) is int and result.message_id == 23
    request = adapter.opener.requests[0]
    assert_request(request, "sendMessage")
    assert json.loads(request.data) == {
        "chat_id": CHAT_ID,
        "text": text,
        "link_preview_options": {"is_disabled": True},
    }


@pytest.mark.parametrize("document", [False, True])
@pytest.mark.parametrize(
    "field,value",
    [
        ("message_id", True),
        ("message_id", "23"),
        ("message_id", 0),
        ("message_id", -1),
        ("message_id", 23.0),
        ("message_id", None),
        ("chat", {"id": -999, "type": "group"}),
        ("chat", {"id": CHAT_ID, "type": "group"}),
        ("chat", {"id": int(CHAT_ID), "type": "channel"}),
        ("chat", {"id": int(CHAT_ID), "type": "private"}),
        ("from", {"id": 999, "is_bot": True}),
        ("from", {"id": int(BOT_ID), "is_bot": False}),
        ("from", {"id": BOT_ID, "is_bot": True}),
        ("from", None),
    ],
)
def test_receipt_requires_matching_typed_bot_chat_and_message(document, field, value):
    receipt = message(document=document)
    receipt[field] = value
    adapter = adapter_for(successful(receipt))
    with pytest.raises(DeliveryError) as failure:
        send(adapter, document=document)
    assert failure.value.unknown is True
    assert_safe(failure.value)


@pytest.mark.parametrize("filename", ["CafeFin-summary.pdf", "CafeFin-summary.xlsx"])
def test_document_is_one_multipart_send_with_canonical_filename(filename):
    content = b"synthetic file bytes\x00\xff"
    adapter = adapter_for(successful(message(document=True)))
    receipt = adapter.send_document(TOKEN, CHAT_ID, content, filename, BOT_ID)
    assert receipt.chat_id == CHAT_ID and receipt.message_id == 23
    assert len(adapter.opener.requests) == 1
    request = adapter.opener.requests[0]
    assert_request(request, "sendDocument")
    content_type = request.get_header("Content-type")
    assert content_type.startswith("multipart/form-data; boundary=")
    mime = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + request.data
    )
    parts = {
        part.get_param("name", header="content-disposition"): part for part in mime.iter_parts()
    }
    assert set(parts) == {"chat_id", "document"}
    assert parts["chat_id"].get_payload(decode=True).decode() == CHAT_ID
    assert parts["document"].get_filename() == filename
    assert parts["document"].get_payload(decode=True) == content


@pytest.mark.parametrize(
    "field,value",
    [
        ("file_id", ""),
        ("file_id", None),
        ("file_id", True),
        ("file_unique_id", ""),
        ("file_unique_id", 123),
    ],
)
def test_document_needs_actual_file_identifiers(field, value):
    receipt = message(document=True)
    receipt["document"][field] = value
    adapter = adapter_for(successful(receipt))
    with pytest.raises(DeliveryError) as failure:
        send(adapter, document=True)
    assert failure.value.unknown is True


def test_document_response_without_document_is_unknown():
    adapter = adapter_for(successful(message()))
    with pytest.raises(DeliveryError) as failure:
        send(adapter, document=True)
    assert failure.value.unknown is True


@pytest.mark.parametrize("document", [False, True])
@pytest.mark.parametrize(
    "response",
    [
        b"not-json " + SECRET.encode(),
        b"[]",
        b"null",
        {},
        {"ok": 1, "result": {}},
        {"ok": "true", "result": {}},
        {"ok": True},
        {"ok": True, "result": []},
        {"ok": False},
        {"ok": False, "error_code": "400"},
        {"ok": False, "error_code": True},
        {"ok": False, "error_code": 200},
    ],
)
def test_nonconclusive_response_never_claims_sent_or_failed(document, response):
    adapter = adapter_for(response)
    with pytest.raises(DeliveryError) as failure:
        send(adapter, document=document)
    assert failure.value.unknown is True
    assert_safe(failure.value)


@pytest.mark.parametrize("document", [False, True])
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 429])
@pytest.mark.parametrize("via_http_error", [False, True])
def test_explicit_4xx_rejection_is_failed_with_safe_code(document, status, via_http_error):
    body = rejection(status, retry_after=27 if status == 429 else None)
    adapter = adapter_for(http_error(status, body) if via_http_error else body)
    with pytest.raises(DeliveryError) as failure:
        send(adapter, document=document)
    assert failure.value.unknown is False
    assert failure.value.retry_after == (27 if status == 429 else None)
    assert_safe(failure.value)


def test_unauthorized_forbidden_and_rate_limit_have_distinct_codes():
    codes = []
    for status in (400, 401, 403, 429):
        with pytest.raises(DeliveryError) as failure:
            send(adapter_for(rejection(status)))
        codes.append(failure.value.code)
    assert len(set(codes)) == 4


@pytest.mark.parametrize(
    "delay", [1, MAX_RETRY_AFTER, MAX_RETRY_AFTER + 1, 10**100, -1, 0, True, "30", 1.5]
)
def test_retry_delay_is_exact_or_requires_review_without_early_retry(delay):
    with pytest.raises(DeliveryError) as failure:
        send(adapter_for(rejection(429, retry_after=delay)))
    error = failure.value
    assert error.unknown is False
    if type(delay) is int and 1 <= delay <= MAX_RETRY_AFTER:
        assert error.code == "TELEGRAM_RATE_LIMITED"
        assert error.retry_after == delay
    else:
        assert error.code == "TELEGRAM_RETRY_REVIEW_REQUIRED"
        assert error.retry_after is None
    assert_safe(error)


def test_missing_retry_delay_uses_bounded_fallback():
    with pytest.raises(DeliveryError) as failure:
        send(adapter_for(rejection(429)))
    assert failure.value.unknown is False
    assert type(failure.value.retry_after) is int
    assert 1 <= failure.value.retry_after <= MAX_RETRY_AFTER


@pytest.mark.parametrize("document", [False, True])
@pytest.mark.parametrize(
    "kind",
    [
        "url",
        "timeout",
        "socket",
        "tls",
        "os",
        "redirect",
        "http500",
        "api500",
        "conflicting_status",
    ],
)
def test_uncertain_post_errors_stay_unknown_and_redacted(document, kind):
    errors = {
        "url": URLError(SECRET + TOKEN),
        "timeout": TimeoutError(SECRET + TOKEN),
        "socket": socket.timeout(SECRET + TOKEN),
        "tls": ssl.SSLError(SECRET + TOKEN),
        "os": OSError(SECRET + TOKEN),
        "redirect": http_error(302),
        "http500": http_error(500),
        "api500": rejection(500),
        "conflicting_status": http_error(500, rejection(400)),
    }
    with pytest.raises(DeliveryError) as failure:
        send(adapter_for(errors[kind]), document=document)
    assert failure.value.unknown is True
    assert_safe(failure.value)


@pytest.mark.parametrize("document", [False, True])
def test_response_reads_are_bounded_before_json_parsing(document):
    adapter = adapter_for(b" " * (MAX_RESPONSE_BYTES + 1) + SECRET.encode())
    with pytest.raises(DeliveryError) as failure:
        send(adapter, document=document)
    assert failure.value.unknown is True
    assert adapter.opener.opened[0].read_sizes == [MAX_RESPONSE_BYTES + 1]
    assert_safe(failure.value)


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
def test_http_status_alone_cannot_prove_provider_rejected_a_send(status):
    with pytest.raises(DeliveryError) as failure:
        send(adapter_for(http_error(status)))
    assert failure.value.unknown is True
    assert_safe(failure.value)


def test_error_response_body_is_bounded_too():
    body = Response(b" " * (MAX_RESPONSE_BYTES + 1))
    response = HTTPError("https://api.telegram.org/bot" + TOKEN, 400, SECRET, {}, body)
    with pytest.raises(DeliveryError) as failure:
        send(adapter_for(response))
    assert body.read_sizes == [MAX_RESPONSE_BYTES + 1]
    assert failure.value.unknown is True


def test_exact_response_limit_can_return_matching_receipt():
    raw = json.dumps(successful(message())).encode()
    adapter = adapter_for(raw + b" " * (MAX_RESPONSE_BYTES - len(raw)))
    assert send(adapter).message_id == 23


def test_group_migration_rejection_does_not_redirect_or_send_to_new_group():
    response = rejection(400)
    response["parameters"] = {"migrate_to_chat_id": -1009999999999}
    adapter = adapter_for(response)
    with pytest.raises(DeliveryError) as failure:
        send(adapter)
    assert failure.value.unknown is False
    assert len(adapter.opener.requests) == 1
    assert json.loads(adapter.opener.requests[0].data)["chat_id"] == CHAT_ID


@pytest.mark.parametrize(
    "text",
    ["", "a" * (MAX_TEXT_UNITS + 1), "😀" * (MAX_TEXT_UNITS // 2 + 1), "bad\ud800", "bad\udfff"],
)
def test_invalid_text_rejected_before_network_without_silent_truncation(text):
    adapter = adapter_for()
    with pytest.raises(DeliveryError) as failure:
        adapter.send_text(TOKEN, CHAT_ID, text, BOT_ID)
    assert failure.value.unknown is False
    assert adapter.opener.requests == []


@pytest.mark.parametrize("text", ["a" * MAX_TEXT_UNITS, "😀" * (MAX_TEXT_UNITS // 2)])
def test_exact_utf16_limit_is_sent_unchanged(text):
    adapter = adapter_for(successful(message()))
    adapter.send_text(TOKEN, CHAT_ID, text, BOT_ID)
    assert json.loads(adapter.opener.requests[0].data)["text"] == text


@pytest.mark.parametrize("text", ["a" * 5000, "😀" * 3000, "a" * 4094 + "😀" * 3])
def test_pre_pin_truncation_is_utf16_safe_and_deterministic(text):
    trimmed = truncate_text(text)
    assert trimmed.endswith("…")
    assert len(trimmed.encode("utf-16-le")) // 2 <= MAX_TEXT_UNITS
    assert text.startswith(trimmed[:-1])
    assert truncate_text(trimmed) == trimmed
    adapter = adapter_for(successful(message()))
    adapter.send_text(TOKEN, CHAT_ID, trimmed, BOT_ID)
    assert json.loads(adapter.opener.requests[0].data)["text"] == trimmed


@pytest.mark.parametrize(
    "filename",
    [
        "CafeFin-summary.txt",
        "../CafeFin-summary.pdf",
        "C:/private/summary.pdf",
        "https://example.invalid/file.pdf",
        "CafeFin-summary.pdf\r\nInjected: value",
        "CafeFin-summary.PDF",
    ],
)
def test_noncanonical_filename_is_rejected_before_network(filename):
    adapter = adapter_for()
    with pytest.raises(DeliveryError) as failure:
        adapter.send_document(TOKEN, CHAT_ID, b"summary", filename, BOT_ID)
    assert failure.value.unknown is False
    assert adapter.opener.requests == []


@pytest.mark.parametrize(
    "content", [b"", "https://example.invalid/file.pdf", bytearray(b"summary"), None]
)
def test_document_only_accepts_nonempty_bytes(content):
    adapter = adapter_for()
    with pytest.raises(DeliveryError):
        adapter.send_document(TOKEN, CHAT_ID, content, "CafeFin-summary.pdf", BOT_ID)
    assert adapter.opener.requests == []


def test_five_mib_document_limit_is_enforced_before_network():
    adapter = adapter_for(successful(message(document=True)))
    with pytest.raises(DeliveryError) as failure:
        adapter.send_document(
            TOKEN, CHAT_ID, b"x" * (MAX_DOCUMENT_BYTES + 1), "CafeFin-summary.pdf", BOT_ID
        )
    assert failure.value.unknown is False
    assert adapter.opener.requests == []
    adapter.send_document(TOKEN, CHAT_ID, b"x" * MAX_DOCUMENT_BYTES, "CafeFin-summary.pdf", BOT_ID)
    assert len(adapter.opener.requests) == 1


@pytest.mark.parametrize(
    "token",
    [
        "",
        "123456:short",
        "0123456:" + "A" * 35,
        "0:" + "A" * 35,
        "-1:" + "A" * 35,
        "4503599627370496:" + "A" * 35,
        "123456:" + "A" * 257,
        "123456:" + "A" * 35 + "/getMe",
        TOKEN + "?x=1",
        TOKEN + "\r\nX: value",
    ],
)
def test_invalid_bot_token_never_reaches_network(token):
    adapter = adapter_for()
    with pytest.raises(DeliveryError):
        adapter.send_text(token, CHAT_ID, "Tổng hợp", BOT_ID)
    assert adapter.opener.requests == []


@pytest.mark.parametrize("token_length", [30, 256])
@pytest.mark.parametrize("identity", ["1", str(2**52 - 1)])
def test_canonical_token_and_chat_id_boundaries_are_supported(token_length, identity):
    token = identity + ":" + "_" * token_length
    group_id = str(-(2**52 - 1))
    receipt = message()
    receipt["from"]["id"] = int(identity)
    receipt["chat"]["id"] = int(group_id)
    adapter = adapter_for(successful(receipt))
    result = adapter.send_text(token, group_id, "Tổng hợp", identity)
    assert result.chat_id == group_id and result.message_id == 23


@pytest.mark.parametrize(
    "chat_id",
    [
        "",
        "12345",
        "0",
        "-0",
        "-01",
        " -123",
        "-123 ",
        "@publicgroup",
        "-4503599627370496",
        -123,
        True,
    ],
)
def test_noncanonical_or_non_group_chat_never_reaches_network(chat_id):
    adapter = adapter_for()
    with pytest.raises(DeliveryError):
        adapter.send_text(TOKEN, chat_id, "Tổng hợp", BOT_ID)
    assert adapter.opener.requests == []


@pytest.mark.parametrize("operation", ["verify", "send_text", "send_document"])
def test_expected_bot_must_match_token_before_network(operation):
    adapter = adapter_for()
    with pytest.raises(DeliveryError):
        if operation == "verify":
            adapter.verify(TOKEN, CHAT_ID, "999")
        elif operation == "send_text":
            adapter.send_text(TOKEN, CHAT_ID, "Tổng hợp", "999")
        else:
            adapter.send_document(TOKEN, CHAT_ID, b"summary", "CafeFin-summary.pdf", "999")
    assert adapter.opener.requests == []


@pytest.mark.parametrize(
    "method",
    [
        "getUpdates",
        "getFile",
        "setWebhook",
        "getChat?token=x",
        "../sendMessage",
        "https://example.invalid/sendMessage",
        "sendMessage\r\n",
    ],
)
def test_arbitrary_methods_are_rejected_by_allowlist_before_network(method):
    adapter = adapter_for()
    with pytest.raises(DeliveryError) as failure:
        adapter._request(method, TOKEN, {}, uncertain=True)
    assert failure.value.unknown is False
    assert adapter.opener.requests == []


def test_default_opener_verifies_tls_and_refuses_redirects():
    adapter = OfficialTelegram()
    https = next(
        handler for handler in adapter.opener.handlers if isinstance(handler, HTTPSHandler)
    )
    assert https._context.verify_mode == ssl.CERT_REQUIRED
    assert https._context.check_hostname is True
    redirect = next(
        handler for handler in adapter.opener.handlers if isinstance(handler, HTTPRedirectHandler)
    )
    request = Request("https://api.telegram.org/bot" + TOKEN + "/sendMessage", data=b"{}")
    assert (
        redirect.redirect_request(request, None, 302, SECRET, {}, "https://example.invalid") is None
    )


def test_no_oauth_upload_phase_or_history_guessing_operation():
    adapter = OfficialTelegram()
    for name in ("refresh", "upload", "send_file", "reconcile"):
        assert not hasattr(adapter, name)

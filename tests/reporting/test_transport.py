import io
import json
from urllib.error import HTTPError, URLError

import pytest
from cafe_fin.reporting.zalo import DeliveryError, OfficialGMF


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return Response(json.dumps(result).encode())


def test_official_text_request_receipt_group_match_and_oauth_rotation():
    adapter = OfficialGMF()
    adapter.opener = Opener(
        {"access_token": "rotated", "refresh_token": "new-refresh", "expires_in": "90000"},
        {"error": 0, "data": {"oaid": "oa"}},
        {"error": 0, "data": {"group_info": {"group_id": "group", "status": "enabled"}}},
        {"error": 0, "data": {"message_id": "msg-1", "group_id": "group"}},
    )
    replacement = adapter.refresh({"app_id": "123", "app_secret": "secret", "refresh_token": "old"})
    assert replacement["refresh_token"] == "new-refresh"
    request = adapter.opener.requests[0]
    assert request.full_url == "https://oauth.zaloapp.com/v4/oa/access_token"
    assert b"grant_type=refresh_token" in request.data
    adapter.verify("token", "oa", "group")
    assert adapter.send_text("token", "group", "Tổng hợp") == "msg-1"
    sent = json.loads(adapter.opener.requests[-1].data)
    assert sent == {"recipient": {"group_id": "group"}, "message": {"text": "Tổng hợp"}}
    assert "token" not in adapter.opener.requests[-1].full_url


@pytest.mark.parametrize(
    "response,unknown",
    [
        ({"error": 0, "data": {"message_id": "msg", "group_id": "wrong"}}, True),
        ({"error": -1, "message": "SECRET must not be echoed"}, False),
        ({"data": {"message_id": "msg", "group_id": "group"}}, True),
        (URLError("SECRET network failure"), True),
        (HTTPError("https://openapi.zalo.me", 500, "SECRET", {}, None), True),
    ],
)
def test_official_send_never_claims_success_without_matching_receipt(response, unknown):
    adapter = OfficialGMF()
    adapter.opener = Opener(response)
    with pytest.raises(DeliveryError) as failure:
        adapter.send_text("secret-token", "group", "Tổng hợp")
    assert failure.value.unknown is unknown
    assert "SECRET" not in str(failure.value) and "secret-token" not in str(failure.value)


def test_file_upload_capability_disabled_until_verified_and_no_guess_receipt():
    adapter = OfficialGMF()
    with pytest.raises(DeliveryError, match="ZALO_UPLOAD_CAPABILITY_UNVERIFIED"):
        adapter.upload("token", b"summary", "CafeFin-summary.pdf")
    adapter.opener = Opener({"error": 0, "data": [{"message": "same text", "message_id": "maybe"}]})
    assert adapter.reconcile("token", "group", "same text") is None

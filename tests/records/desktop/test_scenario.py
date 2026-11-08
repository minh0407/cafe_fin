"""Run the canonical request-only scenario against the default integrated registry."""

import json
import secrets
from datetime import datetime, timedelta

import pytest
from cafe_fin.core.api import create_app
from cafe_fin.core.db import REQUESTS
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.records.desktop.scenario import exercise


class SourceAPI:
    def __init__(self, client, headers, secret_values):
        self.client, self.headers = client, headers
        self.secret_values = secret_values

    def request(self, method, path, *, data=None, params=None):
        return self.client.request(
            method, "/api/v1/records/" + path, headers=self.headers, json=data, params=params
        )


@pytest.fixture
def integrated_api(tmp_path, monkeypatch):
    from cafe_fin.records import market_http

    monkeypatch.setenv("CAFE_FIN_MARKET_NETWORK", "0")
    monkeypatch.setattr(
        market_http,
        "download_html",
        lambda: pytest.fail("The scenario must not access a market network source."),
    )
    runtime = Runtime(tmp_path / "Cafe Fin desktop fixture", initialize=True)
    password = secrets.token_urlsafe(24)
    session = runtime.auth.setup("desktop-fixture-admin", password)
    token, port = secrets.token_urlsafe(32), 49381
    app = create_app(runtime, token, port=port)
    headers = {"X-App-Session": token, "Authorization": "Bearer " + session["access_token"]}
    try:
        with TestClient(app, base_url=f"http://127.0.0.1:{port}") as client:
            yield SourceAPI(client, headers, (password, token, session["access_token"])), runtime
    finally:
        runtime.close()


@pytest.mark.parametrize("occurred_on", ["2026-11-08", "2026-01-01"])
def test_canonical_desktop_scenario_integrated_source_http_and_persistent_receipts(
    integrated_api, occurred_on
):
    api, runtime = integrated_api
    result = exercise(api, occurred_on=occurred_on, request_prefix="desktop-source")
    assert result["expected_balances"] == result["observed_balances"]
    assert result["observed_balances"]["raw"]["closing_kg"] == "70.001"
    assert result["observed_balances"]["processed"]["closing_kg"] == "19.111"
    assert all(check["status"] == "PASS" for check in result["checks"])
    names = {check["name"] for check in result["checks"]}
    assert {
        "decrease_receipt",
        "delete_receipt",
        "cancel_receipt",
        "backdate_issue",
        "restore_issue_would_overspend",
        "same_key_different_payload",
        "stale_version",
    } <= names
    actual_utc = datetime.fromisoformat(result["occurred_at_utc"].replace("Z", "+00:00"))
    assert (actual_utc + timedelta(hours=7)).date().isoformat() == occurred_on
    assert actual_utc.date().isoformat() < occurred_on
    raw_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "access_token" not in raw_json and "Authorization" not in raw_json
    assert not any(value in raw_json for value in api.secret_values)
    assert result["market"]["status"] == "NETWORK_DISABLED"
    with runtime.reader() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
        assert (
            conn.execute(
                select(REQUESTS).where(REQUESTS.c.request_key.like("desktop-source:reject-%"))
            ).all()
            == []
        )
        for request_key in ("desktop-source:receipt-create", "desktop-source:receipt-post"):
            assert (
                len(
                    conn.execute(
                        select(REQUESTS).where(REQUESTS.c.request_key == request_key)
                    ).all()
                )
                == 1
            )


def test_scenario_refuses_nonempty_records_root_before_creating_more_data(integrated_api):
    api, _ = integrated_api
    response = api.request(
        "POST",
        "parties",
        data={"code": "EXISTING", "name": "Dữ liệu tổng hợp có sẵn", "request_key": "existing"},
    )
    assert response.status_code == 200
    with pytest.raises(AssertionError, match="fresh, empty"):
        exercise(api, occurred_on="2026-11-08")
    assert api.request("GET", "parties").json()["total"] == 1
    assert api.request("GET", "entries").json()["total"] == 0


@pytest.mark.parametrize(
    "occurred_on,prefix", [("2026-11-8", "records-desktop"), ("2026-11-08", "bad/prefix")]
)
def test_scenario_rejects_invalid_parameters_without_http(occurred_on, prefix):
    class NoRequests:
        def request(self, *args, **kwargs):
            pytest.fail("Invalid scenario parameters must be rejected before HTTP.")

    with pytest.raises(ValueError):
        exercise(NoRequests(), occurred_on=occurred_on, request_prefix=prefix)

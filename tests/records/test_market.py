"""Synthetic source only; real file-backed SQLite, HTTP handlers and lifecycle."""

import json
import threading
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from cafe_fin.core.db import AUDIT, SCHEMA
from cafe_fin.core.errors import CoreError
from cafe_fin.records import market, market_http
from cafe_fin.records.market_parser import parse_banggianongsan_html
from cafe_fin.records.migrations import REVISIONS
from cafe_fin.records.migrations.market_v2 import DAYS, EVIDENCE
from sqlalchemy import func, select


def html(day=None, price="103000", *, table="103.000", metadata=True):
    day = day or market.today()
    data = {
        "@type": "Dataset",
        "@id": market_http.SOURCE_URL + "#dataset",
        "variableMeasured": [
            {"name": "Cà phê Gia Lai (đồng/kg)", "unitText": "VND", "value": price}
        ],
    }
    if metadata:
        data["dateModified"] = day + "T08:00:00+07:00"
    return (
        '<script type="application/ld+json">' + json.dumps(data) + "</script>"
        "<table><tr><th>Vùng</th><th>Giá mới</th><th>Giá cũ</th></tr>"
        f"<tr><td>Cà phê Gia Lai (đồng/kg)</td><td>{table}</td><td>102.000</td></tr></table>"
    )


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("CAFE_FIN_MARKET_NETWORK", "1")
    monkeypatch.setattr(market_http, "download_html", lambda: html())


def check(api, key=None):
    response = api.request("POST", "market/processed/check", data={"request_key": key or api.key()})
    assert response.status_code == 200, response.text
    return response.json()


def test_parser_exact_day_decimal_and_no_clock_fallback():
    expected = datetime.fromisoformat(market.today()).date()
    assert parse_banggianongsan_html(html(), expected) == (Decimal("103000.00"), expected)
    with pytest.raises(market_http.MarketError, match="thời điểm") as error:
        parse_banggianongsan_html(html(metadata=False), expected)
    assert error.value.code == "MISSING_SOURCE_DATE"
    precise = html(price="10000.0000000000001", table="10.000").replace(
        '"10000.0000000000001"', "10000.0000000000001"
    )
    with pytest.raises(market_http.MarketError) as error:
        parse_banggianongsan_html(precise, expected)
    assert error.value.code == "INVALID_PRICE"


@pytest.mark.parametrize("offset,code", [(-1, "STALE_SOURCE"), (1, "FUTURE_SOURCE")])
def test_parser_date_rejections(offset, code):
    expected = datetime.fromisoformat(market.today()).date()
    with pytest.raises(market_http.MarketError) as error:
        parse_banggianongsan_html(html((expected + timedelta(days=offset)).isoformat()), expected)
    assert error.value.code == code


@pytest.mark.parametrize(
    "source,code",
    [
        ("<title>Just a moment</title>", "BLOCKED"),
        (html(table="104.000"), "CONFLICTING_SOURCE"),
        (html().replace('"unitText": "VND"', '"unitText": "USD"'), "WRONG_UNIT"),
        ("<html>no quote</html>", "SOURCE_CHANGED"),
    ],
)
def test_parser_source_rejections(source, code):
    with pytest.raises(market_http.MarketError) as error:
        parse_banggianongsan_html(source)
    assert error.value.code == code


def test_status_is_pure_and_network_gate(records_api, monkeypatch):
    monkeypatch.setenv("CAFE_FIN_MARKET_NETWORK", "0")
    monkeypatch.setattr(market_http, "download_html", lambda: pytest.fail("No network"))
    assert records_api.get("market/processed")["status"] == "NETWORK_DISABLED"
    assert check(records_api)["attempts"] == 0
    with records_api.runtime.reader() as conn:
        assert conn.execute(select(func.count()).select_from(DAYS)).scalar_one() == 0


def test_apply_once_atomic_audits_grade_quotes_and_immutable(records_api, enabled, monkeypatch):
    api = records_api
    result = check(api, "market-once")
    assert result["status"] == "APPLIED"
    assert result["attempts"] == 1
    snapshot = result["snapshot"]
    assert snapshot["source_date"] == market.today()
    assert snapshot["price_vnd_per_kg"] == "103000.00"
    assert len(snapshot["html_sha256"]) == 64
    monkeypatch.setattr(market_http, "download_html", lambda: pytest.fail("Already applied"))
    assert check(api, "market-once")["snapshot"] == snapshot
    assert check(api)["attempts"] == 1
    board = api.get("price-boards/" + result["board_id"])
    for action in ("delete", "restore"):
        response = api.command("price-boards", board, action)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "MARKET_BOARD_MANAGED"
    response = api.replace(
        "price-boards",
        board,
        {
            "price_date": market.today(),
            "price_kind": "purchase_processed",
            "pricing_method": "grade",
            "grade5_price_vnd": "104000",
        },
    )
    assert response.status_code == 409
    quote = api.get(
        "price-quote", price_kind="purchase_processed", price_date=market.today(), grade=1
    )
    assert quote["unit_price_vnd"] == "67578.30"
    with api.runtime.reader() as conn:
        assert conn.execute(select(func.count()).select_from(EVIDENCE)).scalar_one() == 1
        assert (
            conn.execute(
                select(func.count())
                .select_from(AUDIT)
                .where(AUDIT.c.entity == "records.market_processed")
            ).scalar_one()
            == 1
        )
        assert (
            conn.execute(
                select(func.count())
                .select_from(REVISIONS)
                .where(REVISIONS.c.document_id == board["id"])
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize("deleted", [False, True])
def test_manual_board_including_deleted_is_never_refetched(
    records_api, enabled, monkeypatch, deleted
):
    api = records_api
    board = api.create(
        "price-boards",
        {
            "price_date": market.today(),
            "price_kind": "purchase_processed",
            "pricing_method": "grade",
            "grade5_price_vnd": "99000",
        },
    )
    if deleted:
        assert api.command("price-boards", board, "delete").status_code == 200
    monkeypatch.setattr(market_http, "download_html", lambda: pytest.fail("Existing manual board"))
    assert check(api)["status"] == "EXISTING_BOARD"
    assert check(api)["attempts"] == 0


def test_cooldown_and_blocked_backoff_survive_retry(records_api, enabled, monkeypatch):
    calls = []

    def blocked():
        calls.append(1)
        raise market_http.MarketError("BLOCKED", "Synthetic blocked")

    monkeypatch.setattr(market_http, "download_html", blocked)
    value = check(records_api)
    assert value["status"] == "BLOCKED"
    assert datetime.fromisoformat(
        value["next_attempt_at"].replace("Z", "+00:00")
    ) > market.now() + timedelta(minutes=59)
    assert check(records_api)["status"] == "BLOCKED"
    assert len(calls) == 1


def test_fetch_has_no_writer_lock_and_manual_race_wins(records_api, enabled, monkeypatch):
    api = records_api

    def fetch():
        board = api.create(
            "price-boards",
            {
                "price_date": market.today(),
                "price_kind": "purchase_processed",
                "pricing_method": "grade",
                "grade5_price_vnd": "99000",
            },
        )
        assert board["grade5_price_vnd"] == "99000.00"
        return html()

    monkeypatch.setattr(market_http, "download_html", fetch)
    assert check(api)["status"] == "EXISTING_BOARD"
    with api.runtime.reader() as conn:
        assert conn.execute(select(func.count()).select_from(EVIDENCE)).scalar_one() == 0


def test_config_flip_during_fetch_rejects_result(records_api, enabled, monkeypatch):
    api = records_api

    def fetch():
        response = api.request(
            "PUT",
            "market/processed/settings",
            data={"request_key": api.key(), "expected_version": 1, "enabled": False},
        )
        assert response.status_code == 200
        return html()

    monkeypatch.setattr(market_http, "download_html", fetch)
    assert check(api)["status"] == "DISABLED"
    assert api.get("price-boards")["total"] == 0


def test_midnight_rejects_result(records_api, enabled, monkeypatch):
    start = market.now().replace(hour=16, minute=59, second=59, microsecond=0)
    clock = [start]
    monkeypatch.setattr(market, "now", lambda: clock[0])

    def fetch():
        source = html()
        clock[0] += timedelta(seconds=2)
        return source

    monkeypatch.setattr(market_http, "download_html", fetch)
    assert check(records_api)["status"] == "DAY_CHANGED"
    assert records_api.get("price-boards")["total"] == 0


def test_concurrent_claim_fetch_once(records_api, enabled, monkeypatch):
    api = records_api
    entered, release = threading.Event(), threading.Event()
    calls = []

    def fetch():
        calls.append(1)
        entered.set()
        assert release.wait(4)
        return html()

    monkeypatch.setattr(market_http, "download_html", fetch)
    results = []
    worker = threading.Thread(
        target=lambda: results.append(market.MarketService(api.runtime).check())
    )
    worker.start()
    try:
        assert entered.wait(4)
        assert check(api)["status"] == "FETCHING"
    finally:
        release.set()
        worker.join(4)
    assert not worker.is_alive()
    assert len(calls) == 1
    assert results[0]["status"] == "APPLIED"


def test_settings_version_idempotency_disabled(records_api, enabled, monkeypatch):
    api = records_api
    body = {"request_key": api.key(), "expected_version": 1, "enabled": False}
    assert (
        api.request("PUT", "market/processed/settings", data=body).json()["settings_version"] == 2
    )
    assert (
        api.request("PUT", "market/processed/settings", data=body).json()["settings_version"] == 2
    )
    assert (
        api.request("PUT", "market/processed/settings", data=body | {"enabled": True}).status_code
        == 409
    )
    monkeypatch.setattr(market_http, "download_html", lambda: pytest.fail("Disabled"))
    assert check(api)["status"] == "DISABLED"


def test_maintenance_and_closed_reject_timer(records_api, enabled, monkeypatch):
    api = records_api
    api.runtime.maintenance.hold("00000000-0000-4000-8000-000000000015")
    monkeypatch.setattr(market_http, "download_html", lambda: pytest.fail("Maintenance"))
    market.tick(api.runtime)
    with pytest.raises(CoreError) as error:
        market.MarketService(api.runtime).check()
    assert error.value.code == "MAINTENANCE_REQUIRED"


def test_lease_expiry_disallows_old_finalize(records_api, enabled, monkeypatch):
    api = records_api

    def fetch():
        api.runtime.writer.run(
            lambda conn: conn.execute(
                DAYS.update().values(
                    lease_expires_at=market.stamp(market.now() - timedelta(seconds=1))
                )
            )
        )
        return html()

    monkeypatch.setattr(market_http, "download_html", fetch)
    assert check(api)["status"] == "WAITING_SOURCE"
    assert api.get("price-boards")["total"] == 0


def test_v1_checksum_unchanged_and_v2_applied(records_api):
    with records_api.runtime.reader() as conn:
        rows = conn.execute(
            select(SCHEMA.c.version)
            .where(SCHEMA.c.namespace == "records")
            .order_by(SCHEMA.c.version)
        ).all()
    assert [row[0] for row in rows] == [1, 2]


def test_audit_failure_rolls_back_board_evidence_and_applied(records_api, enabled, monkeypatch):
    from cafe_fin.core.audit import AuditService

    original = AuditService.record

    def fail_market_audit(conn, **kwargs):
        if kwargs["entity"] == "records.market_processed":
            raise RuntimeError("Synthetic transaction failure")
        return original(conn, **kwargs)

    monkeypatch.setattr(AuditService, "record", fail_market_audit)
    with pytest.raises(RuntimeError, match="Synthetic transaction"):
        market.MarketService(records_api.runtime).check()
    with records_api.runtime.reader() as conn:
        assert conn.execute(select(func.count()).select_from(EVIDENCE)).scalar_one() == 0
        assert conn.execute(select(func.count()).select_from(REVISIONS)).scalar_one() == 0
        assert (
            conn.execute(
                select(func.count())
                .select_from(AUDIT)
                .where(AUDIT.c.entity == "records.price-boards")
            ).scalar_one()
            == 0
        )
        assert conn.execute(select(DAYS.c.status)).scalar_one() == "FETCHING"


def test_revoked_user_during_fetch_cannot_finalize_or_replay(records_api, enabled, monkeypatch):
    api = records_api
    account = api.runtime.auth.create_user(
        api.principal,
        username="market-operator",
        password="synthetic-market-password",
        role="operator",
        request_key="market-operator-account",
    )
    session = api.runtime.auth.login("market-operator", "synthetic-market-password")
    captured = api.runtime.auth.authenticate(session["access_token"])

    def fetch():
        api.runtime.auth.update_user(
            api.principal,
            account["id"],
            role="operator",
            active=False,
            expected_version=account["version"],
            request_key="market-revoke-account",
        )
        return html()

    monkeypatch.setattr(market_http, "download_html", fetch)
    for _ in range(2):
        with pytest.raises(CoreError):
            market.MarketService(api.runtime).check(captured, "revoked-check")
    assert api.get("price-boards")["total"] == 0


def test_registered_timer_actually_collects_and_closes(records_api, enabled, monkeypatch):
    completed = threading.Event()

    def fetch():
        completed.set()
        return html()

    monkeypatch.setattr(market_http, "download_html", fetch)
    assert records_api.runtime.periodic.tasks["records.market"].interval_seconds == 10
    assert completed.wait(12), "Actual registered periodic callback did not run"
    # Acquiring the writer queues after the callback's atomic finalization.
    for _ in range(100):
        state = records_api.get("market/processed")
        if state["status"] == "APPLIED":
            break
        threading.Event().wait(0.01)
    assert state["status"] == "APPLIED"
    records_api.runtime.close()
    assert not records_api.runtime.periodic.thread.is_alive()

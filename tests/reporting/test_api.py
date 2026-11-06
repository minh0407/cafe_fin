import json

from cafe_fin.core.api import create_app
from cafe_fin.core.db import AUDIT, REQUESTS
from fastapi.testclient import TestClient
from sqlalchemy import select


def test_real_api_module_auth_validation_paging_snapshot_and_admin_boundary(env):
    app = create_app(env.runtime, "synthetic-report-session-0123456789abcdef", port=48961)
    headers = {
        "X-App-Session": "synthetic-report-session-0123456789abcdef",
        "Origin": "http://tauri.localhost",
        "Authorization": "Bearer " + env.auth["access_token"],
    }
    env.runtime.auth.create_user(
        env.actor,
        username="reportoperator",
        password="synthetic-operator-password",
        role="operator",
        request_key="operator",
    )
    with TestClient(app, base_url="http://127.0.0.1:48961") as client:
        assert client.get("/api/v1/reporting/reports", headers=headers).status_code == 200
        payload = {
            "from_on": "2026-11-06",
            "through_on": "2026-11-06",
            "book_ids": ["missing"],
            "request_key": "http-preview",
            "reason": "",
        }
        preview = client.post("/api/v1/reporting/reports/preview", headers=headers, json=payload)
        assert preview.status_code == 200, preview.text
        report = preview.json()
        identity = report["id"]
        assert (
            client.post(
                f"/api/v1/reporting/reports/{identity}/save",
                headers=headers,
                json={"request_key": "save", "expected_version": 9},
            ).status_code
            == 409
        )
        save = client.post(
            f"/api/v1/reporting/reports/{identity}/save",
            headers=headers,
            json={"request_key": "save", "expected_version": 1},
        )
        assert save.status_code == 200 and save.json()["state"] == "SAVED"
        assert (
            client.get("/api/v1/reporting/reports?page_size=501", headers=headers).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/reporting/reports?sort=snapshot_json:asc", headers=headers
            ).status_code
            == 400
        )
        assert client.get(f"/api/v1/reporting/reports/{identity}", headers=headers).json()[
            "short_message"
        ]
        login = client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"username": "reportoperator", "password": "synthetic-operator-password"},
        )
        operator = {**headers, "Authorization": "Bearer " + login.json()["access_token"]}
        assert client.get("/api/v1/reporting/settings", headers=operator).status_code == 403
        credential = {
            "app_id": "app",
            "app_secret": "PRIVATE-CREDENTIAL-sentinel",
            "refresh_token": "PRIVATE-REFRESH-sentinel",
        }
        assert (
            client.put(
                "/api/v1/reporting/credentials", headers=operator, json=credential
            ).status_code
            == 403
        )
        invalid = client.put(
            "/api/v1/reporting/credentials",
            headers=headers,
            json={**credential, "refresh_token": "PRIVATE-REFRESH-sentinel" * 500},
        )
        assert invalid.status_code == 422
        assert "PRIVATE-" not in invalid.text
        with env.runtime.reader() as conn:
            persisted = json.dumps([list(row) for row in conn.execute(select(REQUESTS))])
            persisted += json.dumps([list(row) for row in conn.execute(select(AUDIT))])
        assert "PRIVATE-" not in persisted
        # Generic core job endpoint must not permit bypassing reporting's typed boundary.
        generic = client.post(
            "/api/v1/jobs",
            headers=headers,
            json={"kind": "reporting.dispatch", "payload": {}, "request_key": "bypass"},
        )
        assert (
            generic.status_code == 403
            or generic.json()["error"]["code"] == "MODULE_JOB_ENDPOINT_REQUIRED"
        )

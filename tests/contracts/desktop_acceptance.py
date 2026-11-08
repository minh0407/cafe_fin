"""Run contracts acceptance against a real framed-IPC sidecar, never TestClient.

All operational data and generated evidence must be new paths outside repositories.
Frozen binaries are not assumed to match source based on a caller's assertion.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import queue
import secrets
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

REPOSITORY = Path(__file__).resolve().parents[2]
ORIGIN = "http://tauri.localhost"
DAY = "2026-11-08"


class AcceptanceFailure(RuntimeError):
    """A bounded, non-secret diagnostic suitable for the evidence manifest."""


def require(condition, code):
    if not condition:
        raise AcceptanceFailure(code)


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_file(path):
    with Path(path).open("rb") as source:
        digest = hashlib.file_digest(source, "sha256")
    return digest.hexdigest()


def fresh_paths(data_root, output_dir):
    paths = [Path(value) for value in (data_root, output_dir)]
    for path in paths:
        require(path.is_absolute(), "ABSOLUTE_EXTERNAL_PATH_REQUIRED")
        require(not path.exists(), "FRESH_NONEXISTENT_PATH_REQUIRED")
        require(not str(path).startswith("\\\\"), "LOCAL_PATH_REQUIRED")
        require(path.parent.is_dir(), "EXISTING_PARENT_DIRECTORY_REQUIRED")
        resolved = path.resolve()
        for parent in (resolved, *resolved.parents):
            require(not (parent / ".git").exists(), "PATH_INSIDE_REPOSITORY_DENIED")
            require(
                not (parent / ".cafe-fin-root.json").exists(), "PATH_INSIDE_OPERATIONAL_ROOT_DENIED"
            )
        require(not resolved.is_relative_to(REPOSITORY), "PATH_INSIDE_REPOSITORY_DENIED")
    data_root, output_dir = [path.resolve() for path in paths]
    require(
        not data_root.is_relative_to(output_dir) and not output_dir.is_relative_to(data_root),
        "DATA_AND_OUTPUT_PATHS_MUST_BE_SEPARATE",
    )
    return data_root, output_dir


def source_identity(source_root):
    result = {"root": str(source_root), "files": {}}
    for path in sorted((source_root / "backend").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            result["files"][path.relative_to(source_root).as_posix()] = sha256_file(path)
    result["tree_sha256"] = hashlib.sha256(canonical(result["files"])).hexdigest()
    for command, key in (
        (["rev-parse", "HEAD"], "observed_git_head"),
        (["status", "--porcelain", "--", "backend"], "backend_status"),
    ):
        completed = subprocess.run(
            ["git", "-C", str(source_root), *command],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        result[key] = completed.stdout.strip() if completed.returncode == 0 else "UNAVAILABLE"
    return result


def execution_identity(args):
    executable = (args.binary or args.python).resolve(strict=True)
    mode = "frozen_binary" if args.binary else "source_python"
    result = {
        "mode": mode,
        "executable": str(executable),
        "executable_sha256": sha256_file(executable),
        "source": source_identity(args.source_root),
        "source_match": "NOT_VERIFIED_BY_HARNESS" if args.binary else "EXPLICIT_SOURCE_RUNTIME",
        "clean_windows": "NOT_RUN",
        "gui": "NOT_RUN",
        "visual_layout": "NOT_RUN",
    }
    if args.provenance:
        result["supplied_provenance"] = {
            "path": str(args.provenance.resolve()),
            "sha256": sha256_file(args.provenance),
            "evidence": json.loads(args.provenance.read_text("utf-8")),
            "trust": "EXTERNAL_EVIDENCE_NOT_INDEPENDENTLY_VERIFIED_BY_THIS_HARNESS",
        }
    if not args.binary:
        probe = subprocess.run(
            [
                str(executable),
                "-c",
                "import cafe_fin,json,sys; print(json.dumps({'package':cafe_fin.__file__,"
                "'python':sys.version,'executable':sys.executable}))",
            ],
            env=child_environment(args),
            cwd=args.source_root,
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        require(probe.returncode == 0, "SOURCE_INTERPRETER_PROBE_FAILED")
        origin = json.loads(probe.stdout)
        require(
            Path(origin["package"]).resolve().is_relative_to(args.source_root / "backend"),
            "SOURCE_PACKAGE_ORIGIN_MISMATCH",
        )
        result["interpreter_probe"] = origin
    return result


def child_environment(args):
    environment = dict(os.environ)
    environment["CAFE_FIN_MARKET_NETWORK"] = "0"
    environment["PYTHONIOENCODING"] = "utf-8"
    if args.binary:
        environment["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
        for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            environment.pop(name, None)
    else:
        environment["PYTHONPATH"] = str(args.source_root / "backend")
        environment.pop("PYTHONHOME", None)
    return environment


def validate_handshake(handshake):
    require(
        handshake.get("status") == "ready" and handshake.get("protocol_version") == 1,
        "SIDECAR_BOOT_FAILED",
    )
    parsed = urlsplit(handshake.get("api_base", ""))
    require(
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.port is not None
        and parsed.path == "/api/v1"
        and not parsed.query
        and not parsed.fragment
        and not parsed.username,
        "NON_LOOPBACK_HANDSHAKE_DENIED",
    )
    return handshake["api_base"]


class Sidecar:
    def __init__(self, args, *, initialize, process_log):
        self.args, self.initialize, self.process_log = args, initialize, process_log
        self.token = secrets.token_urlsafe(40)
        self.process = self.client = None
        self.stderr_digest, self.stderr_bytes = hashlib.sha256(), 0

    def __enter__(self):
        executable = self.args.binary or self.args.python
        command = [str(executable)] if self.args.binary else [str(executable), "-m", "cafe_fin"]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.args.source_root,
            env=child_environment(self.args),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.record = {
            "pid": self.process.pid,
            "initialize": self.initialize,
            "executable": str(executable),
            "executable_sha256": sha256_file(executable),
            "startup": "PENDING",
            "shutdown": "PENDING",
        }
        self.process_log.append(self.record)
        frames = queue.Queue(maxsize=1)

        def first_frame():
            frames.put(self.process.stdout.readline(16385))

        def drain_errors():
            while chunk := self.process.stderr.read(4096):
                self.stderr_digest.update(chunk)
                self.stderr_bytes += len(chunk)

        threading.Thread(target=first_frame, daemon=True).start()
        self.stderr_thread = threading.Thread(target=drain_errors, daemon=True)
        self.stderr_thread.start()
        try:
            self.write(
                {
                    "protocol_version": 1,
                    "session_token": self.token,
                    "data_root": str(self.args.data_root),
                    "initialize": self.initialize,
                    "allowed_origin": ORIGIN,
                }
            )
            try:
                frame = frames.get(timeout=self.args.startup_timeout)
            except queue.Empty:
                raise AcceptanceFailure("SIDECAR_STARTUP_TIMEOUT") from None
            require(frame.endswith(b"\n") and len(frame) <= 16384, "INVALID_BOOT_FRAME")
            require(self.token.encode() not in frame, "BOOT_SECRET_ECHO_DENIED")
            base = validate_handshake(json.loads(frame))
            self.client = httpx.Client(
                base_url=base,
                trust_env=False,
                follow_redirects=False,
                timeout=20,
                headers={"X-App-Session": self.token, "Origin": ORIGIN},
            )
            self.record.update(startup="PASS", api_base=base)
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def write(self, value):
        self.process.stdin.write(canonical(value) + b"\n")
        self.process.stdin.flush()

    def request(self, method, path, *, raw=False, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if response.status_code != 200:
            try:
                code = response.json().get("error", {}).get("code", "UNKNOWN")
            except ValueError:
                code = "NON_JSON_ERROR"
            raise AcceptanceFailure(
                f"HTTP_{response.status_code}_{method}_{path.split('?')[0]}_{code}"
            )
        return response if raw else response.json()

    def authenticate(self, password):
        operation = "setup" if self.initialize else "login"
        auth = self.request(
            "POST",
            f"auth/{operation}",
            json={"username": "synthetic-desktop-admin", "password": password},
        )
        self.client.headers["Authorization"] = "Bearer " + auth["access_token"]

    def __exit__(self, exc_type, exc, traceback):
        if self.client:
            self.client.close()
        if self.process:
            try:
                if self.process.poll() is None:
                    self.write({"command": "shutdown"})
                self.process.wait(timeout=self.args.shutdown_timeout)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=10)
                self.record["shutdown"] = "FAIL_FORCED_TERMINATION"
            self.stderr_thread.join(timeout=2)
            self.record.update(
                exit_code=self.process.returncode,
                stderr_bytes=self.stderr_bytes,
                stderr_sha256=self.stderr_digest.hexdigest(),
            )
            if self.record["shutdown"] == "PENDING":
                self.record["shutdown"] = "PASS" if self.process.returncode == 0 else "FAIL"
            for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                pipe.close()
            if exc_type is None:
                require(self.record["shutdown"] == "PASS", "SIDECAR_CLEAN_SHUTDOWN_FAILED")


def no_side_effects(api):
    period = {"from_on": DAY, "through_on": DAY}
    result = {
        "dashboard": api.request("GET", "records/records-dashboard", params=period),
        "stock": api.request("GET", "records/stock-balances", params=period),
        "movements": api.request("GET", "records/stock-movements"),
        "receivables": api.request("GET", "records/receivables", params={"as_of": DAY}),
        "books": api.request("GET", "accounting/books"),
        "resource_counts": {
            resource: api.request("GET", "records/" + resource)["total"]
            for resource in ("entries", "trades", "trade-payments")
        },
    }

    def without_cutoffs(value):
        if isinstance(value, dict):
            return {key: without_cutoffs(item) for key, item in value.items() if key != "cutoff"}
        if isinstance(value, list):
            return [without_cutoffs(item) for item in value]
        return value

    return without_cutoffs(result)


def offline_settings(api):
    market = api.request("GET", "records/market/processed")
    require(market["network_available"] is False, "MARKET_BOOT_NETWORK_GUARD_NOT_EFFECTIVE")
    if market["enabled"]:
        market = api.request(
            "PUT",
            "records/market/processed/settings",
            json={
                "request_key": "desktop-disable-market",
                "expected_version": market["settings_version"],
                "enabled": False,
            },
        )
    reporting = api.request("GET", "reporting/settings")
    require(
        market["enabled"] is False
        and reporting["enabled"] is False
        and reporting["sender_status"] == "UNCONFIGURED"
        and reporting["auto_generate_daily"] is False,
        "BACKGROUND_NETWORK_CONFIGURATION_NOT_DISABLED",
    )
    return {
        "market_enabled": market["enabled"],
        "market_network_available": False,
        "reporting_enabled": reporting["enabled"],
        "sender_status": reporting["sender_status"],
        "evidence_scope": "COLLECTOR_DISABLED_LOOPBACK_HTTP_ONLY; PHYSICAL_WAN_CUT_NOT_TESTED",
    }


def seed_sources(api, payloads):
    result = {}
    for kind in ("purchase", "sale"):
        party = copy.deepcopy(payloads[kind]["counterparty"])
        party.update(
            {
                "request_key": "desktop-party-" + kind,
                "code": "TST1" if kind == "purchase" else "DESKTOP-CUSTOMER",
                "profile_kind": "farm" if kind == "purchase" else "customer_company",
            }
        )
        if kind == "purchase":
            party["farm"] = {"owner_name": "Chủ farm tổng hợp", "plots": [], "surveys": []}
        saved_party = api.request("POST", "records/parties", json=party)
        weighing = {
            "request_key": "desktop-weighing-" + kind,
            "code": "DESKTOP-WEIGH-" + kind.upper(),
            "occurred_on": DAY,
            "party_id": saved_party["id"],
            "lines": [
                {
                    "description": "Cà phê nguồn tổng hợp",
                    "quantity_source": "direct_net",
                    "net_kg": "999.999",
                }
            ],
        }
        saved_weighing = api.request("POST", "records/weighings", json=weighing)
        result[kind] = {
            "party_command": party,
            "party": saved_party,
            "weighing_command": weighing,
            "weighing": saved_weighing,
        }
    return result


def bridge_payload(api, payload, seed):
    payload = copy.deepcopy(payload)
    expected_party = payload["counterparty"]
    party = api.request("GET", "contracts/sources/parties/" + seed["party"]["id"])
    weighing = api.request("GET", "contracts/sources/weighings/" + seed["weighing"]["id"])
    payload["counterparty"] = {
        key: value for key, value in party.items() if key not in ("id", "version")
    }
    require_supplied_fields(expected_party, payload["counterparty"])
    payload["lines"][0].update(
        source_snapshot=weighing["lines"][0],
        source={
            "type": "weighing",
            "id": weighing["id"],
            "version": weighing["version"],
            "line_index": 0,
            "code": weighing["code"],
            "occurred_on": weighing["occurred_on"],
        },
    )
    payload["source_refs"] = [
        {"type": "party", "id": party["id"], "version": party["version"]},
        {"type": "weighing", "id": weighing["id"], "version": weighing["version"]},
    ]
    require(
        payload["lines"][0]["quantity_kg"] != weighing["lines"][0]["net_kg"],
        "QUANTITY_OVERRIDE_FIXTURE_MUST_DIFFER_FROM_SOURCE",
    )
    return payload


def require_supplied_fields(expected, actual):
    """Allow canonical DTO defaults, while retaining every supplied presentation field."""
    if isinstance(expected, dict):
        require(isinstance(actual, dict), "SAVED_INPUT_TYPE_CHANGED")
        for key, value in expected.items():
            require(key in actual, "SAVED_INPUT_FIELD_MISSING_" + key)
            require_supplied_fields(value, actual[key])
    elif isinstance(expected, list):
        require(
            isinstance(actual, list) and len(actual) == len(expected), "SAVED_INPUT_LIST_CHANGED"
        )
        for expected_item, actual_item in zip(expected, actual, strict=True):
            require_supplied_fields(expected_item, actual_item)
    else:
        require(actual == expected, "SAVED_INPUT_VALUE_CHANGED")


def download_version(api, record, output_dir, *, write=False):
    for format, state in record["version"]["files"].items():
        path = (
            f"contracts/{record['contract_id']}/versions/{record['version']['id']}/files/{format}"
        )
        response = api.request("GET", path, raw=True)
        require(state["status"] == "succeeded", "EXPORT_FORMAT_FAILED")
        require(
            hashlib.sha256(response.content).hexdigest()
            == state["sha256"]
            == response.headers.get("x-content-sha256")
            and len(response.content) == state["size"],
            "DOWNLOADED_FILE_HASH_OR_SIZE_MISMATCH",
        )
        destination = output_dir / f"{record['label']}.{format}"
        if write:
            destination.write_bytes(response.content)
        require(destination.read_bytes() == response.content, "OLD_FILE_BYTES_CHANGED")


def check_export(api, payload, label, formats, output_dir, expected_totals):
    preview = api.request("POST", "contracts/preview", json={"data": payload})
    contract = api.request(
        "POST", "contracts", json={"request_key": label + "-save", "data": payload}
    )
    require_supplied_fields(payload["counterparty"], contract["data"]["counterparty"])
    require_supplied_fields(payload["company"], contract["data"]["company"])
    for key, expected in expected_totals.items():
        require(contract["totals"][key] == expected, "EXPECTED_TOTAL_MISMATCH_" + key)
    snapshot = {
        "data": contract["data"],
        "totals": contract["totals"],
        "template": preview["template"],
        "document": preview["document"],
    }
    document_text = "\n".join(preview["document"]["paragraphs"])
    quantity_labels = {
        "direct": "Nhập kg tịnh trực tiếp",
        "direct_net": "Nhập kg tịnh trực tiếp",
        "gross_minus_tare": "Cân đầy trừ cân rỗng",
        "gross_tare": "Cân đầy trừ cân rỗng",
    }
    for line in payload["lines"]:
        if line.get("quantity_source"):
            display_label = quantity_labels.get(line["quantity_source"], line["quantity_source"])
            require(
                "Cách ghi lượng: " + display_label in document_text,
                "QUANTITY_SOURCE_LABEL_MISMATCH",
            )
    for raw_label in quantity_labels:
        require("Cách ghi lượng: " + raw_label not in document_text, "RAW_QUANTITY_ENUM_RENDERED")
    if payload["lines"][0].get("source_snapshot"):
        require(
            "Số cân nguồn (bản chụp): tịnh (kg): 999,999" in document_text
            and "tịnh (kg): 999.999" not in document_text,
            "SOURCE_KG_NOT_LOCALIZED",
        )
    for party in (payload["company"], payload["counterparty"]):
        for field in ("name", "address"):
            require(party[field] in document_text, "RICH_PARTY_FIELD_NOT_RENDERED_" + field)
        for contact in party["contacts"]:
            require(contact["value"] in document_text, "PARTY_CONTACT_NOT_RENDERED")
        for bank in party["bank_details"]:
            require(
                bank["bank_name"] in document_text and bank["account_number"] in document_text,
                "PARTY_BANK_NOT_RENDERED",
            )
    expected_hash = hashlib.sha256(canonical(snapshot)).hexdigest()
    require(preview["snapshot_sha256"] == expected_hash, "PREVIEW_CANONICAL_HASH_MISMATCH")
    command = {
        "request_key": label + "-export",
        "expected_version": contract["version"],
        "formats": formats,
    }
    path = f"contracts/{contract['id']}/exports"
    version = api.request("POST", path, json=command)
    for format, state in version["files"].items():
        require(
            state["status"] == "succeeded",
            "EXPORT_FORMAT_FAILED_" + format + "_" + str(state["error_code"]),
        )
    require(
        version["snapshot"] == snapshot and version["snapshot_sha256"] == expected_hash,
        "EXPORTED_SNAPSHOT_MISMATCH",
    )
    record = {
        "label": label,
        "contract_id": contract["id"],
        "version": version,
        "payload_sha256": hashlib.sha256(canonical(payload)).hexdigest(),
        "expected_snapshot_sha256": expected_hash,
        "artifacts": {
            format: {
                "path": str(output_dir / f"{label}.{format}"),
                "sha256": state["sha256"],
                "size": state["size"],
            }
            for format, state in version["files"].items()
        },
    }
    download_version(api, record, output_dir, write=True)
    physical_before = sorted(
        path.relative_to(api.args.data_root).as_posix()
        for path in (api.args.data_root / "documents").rglob("*")
        if path.is_file()
    )
    require(api.request("POST", path, json=command) == version, "EXPORT_REPLAY_CHANGED_RESULT")
    physical_after = sorted(
        path.relative_to(api.args.data_root).as_posix()
        for path in (api.args.data_root / "documents").rglob("*")
        if path.is_file()
    )
    require(physical_before == physical_after, "EXPORT_REPLAY_CREATED_PHYSICAL_FILE")
    require(
        api.request("GET", f"contracts/{contract['id']}/versions")["total"] == 1,
        "EXPORT_REPLAY_CREATED_VERSION",
    )
    require(
        api.request("GET", f"contracts/{contract['id']}/attachments")["total"] == 0,
        "OPTIONAL_ATTACHMENT_UNEXPECTED",
    )
    return record, contract


def edit_sources_and_draft(api, payload, seed, record, contract):
    for resource in ("party", "weighing"):
        plural = "parties" if resource == "party" else "weighings"
        original = seed[resource]
        require(
            api.request("GET", f"records/{plural}/{original['id']}") == original,
            "CONTRACT_EDIT_MUTATED_SOURCE",
        )
        command = copy.deepcopy(seed[resource + "_command"])
        command.update(
            request_key="desktop-edit-" + resource + payload["kind"],
            expected_version=original["version"],
        )
        if resource == "party":
            command["name"] += " đã sửa nguồn"
        else:
            command["lines"][0]["net_kg"] = "888.888"
        api.request("PUT", f"records/{plural}/{original['id']}", json=command)
    edited = copy.deepcopy(payload)
    edited["terms"]["additional"] += "\nĐiều khoản bản nháp đã sửa sau xuất."
    api.request(
        "PATCH",
        f"contracts/{contract['id']}",
        json={
            "request_key": record["label"] + "-edit",
            "expected_version": contract["version"],
            "data": edited,
        },
    )
    template = next(
        row
        for row in api.request("GET", "contracts/templates")["items"]
        if row["kind"] == payload["kind"]
    )
    api.request(
        "PATCH",
        "contracts/templates/" + template["id"],
        json={
            "request_key": record["label"] + "-template",
            "expected_version": template["version"],
            "title": template["title"],
            "body": template["body"] + "\n\nMẫu sửa sau xuất tổng hợp.",
        },
    )
    require(
        api.request("GET", f"contracts/{contract['id']}/versions/{record['version']['id']}")
        == record["version"],
        "HISTORICAL_SNAPSHOT_CHANGED",
    )


def run(args):
    if __package__:
        from .desktop_fixtures import EXPECTED_PAYLOAD_SHA256, EXPECTED_TOTALS, contract_payloads
    else:
        from desktop_fixtures import EXPECTED_PAYLOAD_SHA256, EXPECTED_TOTALS, contract_payloads

    args.source_root = args.source_root.resolve(strict=True)
    if args.binary:
        args.binary = args.binary.resolve(strict=True)
    else:
        args.python = args.python.resolve(strict=True)
    args.data_root, args.output_dir = fresh_paths(args.data_root, args.output_dir)
    args.output_dir.mkdir()
    report = {
        "status": "FAIL",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "fixture_date": DAY,
        "data_root": str(args.data_root),
        "output_dir": str(args.output_dir),
        "host": {"platform": platform.platform(), "harness_python": sys.version},
        "harness_sha256": sha256_file(Path(__file__)),
        "fixture_source_sha256": sha256_file(Path(__file__).with_name("desktop_fixtures.py")),
        "processes": [],
        "checks": [],
        "contracts": [],
        "limitations": [
            "No GUI or clean-Windows acceptance",
            "No visual-layout PASS",
            "No physical WAN cut or firewall change",
            "No maintenance CLOSED acknowledgement proof",
        ],
    }
    try:
        report["execution"] = execution_identity(args)
        payloads = contract_payloads()
        report["fixture_baselines"] = {
            "payload_sha256": EXPECTED_PAYLOAD_SHA256,
            "totals": EXPECTED_TOTALS,
        }
        for kind, payload in payloads.items():
            require(
                hashlib.sha256(canonical(payload)).hexdigest() == EXPECTED_PAYLOAD_SHA256[kind],
                "FIXTURE_CANONICAL_HASH_MISMATCH",
            )
        password = secrets.token_urlsafe(24)
        with Sidecar(args, initialize=True, process_log=report["processes"]) as api:
            api.authenticate(password)
            report["offline_configuration"] = offline_settings(api)
            manual_before = no_side_effects(api)
            report["manual_public_baseline"] = manual_before
            manual = copy.deepcopy(payloads["purchase"])
            manual["number"] += "-MANUAL"
            manual["lines"][0]["quantity_source"] = "Người dùng ghi nhận kg theo sổ tổng hợp riêng"
            record, _ = check_export(
                api, manual, "manual", ["docx"], args.output_dir, EXPECTED_TOTALS["purchase"]
            )
            report["contracts"].append(record)
            require(no_side_effects(api) == manual_before, "MANUAL_CONTRACT_CREATED_SIDE_EFFECT")
            seeds = seed_sources(api, payloads)
            before = no_side_effects(api)
            for kind in ("purchase", "sale"):
                payload = bridge_payload(api, payloads[kind], seeds[kind])
                record, contract = check_export(
                    api, payload, kind, ["docx", "pdf"], args.output_dir, EXPECTED_TOTALS[kind]
                )
                edit_sources_and_draft(api, payload, seeds[kind], record, contract)
                download_version(api, record, args.output_dir)
                report["contracts"].append(record)
            require(no_side_effects(api) == before, "CONTRACT_STOCK_CASH_OR_ACCOUNTING_SIDE_EFFECT")
            report["public_side_effect_baseline"] = before
            report["checks"].extend(
                [
                    "typed_records_copy_and_quantity_override",
                    "manual_contract_without_source_or_attachment",
                    "canonical_preview_export_snapshot",
                    "docx_pdf_full_download_hashes",
                    "idempotent_version_and_physical_file_replay",
                    "old_snapshot_and_bytes_after_source_draft_template_edits",
                    "public_side_effects_unchanged",
                ]
            )
        with Sidecar(args, initialize=False, process_log=report["processes"]) as api:
            api.authenticate(password)
            offline_settings(api)
            for record in report["contracts"]:
                require(
                    api.request(
                        "GET",
                        f"contracts/{record['contract_id']}/versions/{record['version']['id']}",
                    )
                    == record["version"],
                    "RESTART_VERSION_CHANGED",
                )
                require(
                    api.request("GET", f"contracts/{record['contract_id']}/versions")["total"] == 1,
                    "RESTART_VERSION_COUNT_CHANGED",
                )
                download_version(api, record, args.output_dir)
            require(no_side_effects(api) == before, "RESTART_SIDE_EFFECT_STATE_CHANGED")
        report["checks"].append("clean_process_restart_preserved_versions_and_exact_files")
        require(
            source_identity(args.source_root)["tree_sha256"]
            == report["execution"]["source"]["tree_sha256"],
            "SOURCE_CHANGED_DURING_ACCEPTANCE",
        )
        require(
            all(
                process["executable_sha256"] == report["execution"]["executable_sha256"]
                for process in report["processes"]
            ),
            "EXECUTABLE_CHANGED_DURING_ACCEPTANCE",
        )
        report["status"] = "PASS"
    except Exception as exc:
        report["error"] = str(exc) if isinstance(exc, AcceptanceFailure) else type(exc).__name__
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (args.output_dir / "manifest.json").write_bytes(canonical(report) + b"\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--binary", type=Path, help="Explicit frozen sidecar EXE; never auto-build")
    mode.add_argument(
        "--python", type=Path, help="Explicit source interpreter; source-only evidence"
    )
    parser.add_argument("--source-root", type=Path, default=REPOSITORY)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--provenance", type=Path, help="External verifier JSON, preserved with trust limit"
    )
    parser.add_argument("--startup-timeout", type=int, default=45)
    parser.add_argument("--shutdown-timeout", type=int, default=25)
    args = parser.parse_args(argv)
    try:
        report = run(args)
    except (AcceptanceFailure, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error": str(exc) if isinstance(exc, AcceptanceFailure) else type(exc).__name__,
                }
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": report["status"],
                "mode": report.get("execution", {}).get("mode"),
                "manifest": str(args.output_dir / "manifest.json"),
                "error": report.get("error"),
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

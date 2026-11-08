"""Mini source-kit evidence through real parsers, SQLite and import workers."""

import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest
from cafe_fin.accounting import parsers
from cafe_fin.accounting import schema as s
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from sqlalchemy import select

from .fixtures import MAX_ROWS, SENTINEL, generate_fixture_kit


def _key():
    return str(uuid4())


def _hash(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _jsonl(artifact):
    with Path(artifact["path"]).open(encoding="utf-8") as source:
        return [json.loads(line) for line in source]


@pytest.fixture(scope="module")
def kit(tmp_path_factory):
    return generate_fixture_kit(tmp_path_factory.mktemp("desktop-sources") / "kit")


def _wait(service, actor, batch_id):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        batch = service.get_batch(actor, batch_id)
        state = batch["job"]["state"]
        if state == "COMPLETED" and batch["state"] not in {
            "UPLOADED",
            "PARSING",
            "VALIDATING",
            "COMMITTING",
        }:
            return batch
        assert state not in {"FAILED", "CANCELLED", "RECOVERABLE"}, batch
        time.sleep(0.01)
    pytest.fail("synthetic mini worker did not reach a terminal state")


def _confirm(service, actor, batch):
    service.confirm(
        actor,
        batch["id"],
        {
            "expected_version": batch["version"],
            "staging_revision": batch["revision"],
            "mapping_revision": batch["mapping_revision"],
            "decision_revision": batch["decision_revision"],
            "validation_token": batch["validation_token"],
            "mode": "valid_rows_only",
            "request_key": _key(),
        },
    )
    return _wait(service, actor, batch["id"])


@pytest.mark.parametrize("kind", ["csv", "xlsx", "xlsm"])
def test_each_format_preserves_source_geometry_and_exact_values(kit, kind, tmp_path):
    source = kit["files"][kind]
    path = Path(source["path"])
    manifest = parsers.manifest(path, path.name)
    if kind != "csv":
        assert [(sheet["id"], sheet["name"]) for sheet in manifest["sheets"]] == [
            ("1", "Hướng dẫn"),
            ("2", "Sổ cà phê"),
        ]
        assert manifest["sheets"][1]["max_row"] == 1003
        assert manifest["sheets"][1]["max_column"] == 8
    count = 0
    for row in parsers.iter_rows(path, path.name, source["profile"], temp_dir=tmp_path):
        count += 1
        assert row.source_row == count + 3
        assert row.sheet_id == source["profile"]["sheet_id"]
        if count in (1, 2):
            assert row.values["A"] == "000000000001"
            assert row.values["C"] == "100.01"
        if count == 17:
            assert "\nDòng ghi chú thứ hai" in row.values["F"]
        if count == 25 and kind != "csv":
            assert row.formulas["C"]["cached_value"] == "999999.99"
    assert count == 1000
    assert _hash(path) == source["sha256"]


@pytest.mark.parametrize("kind", ["csv", "xlsx", "xlsm"])
def test_expected_issues_and_partial_repair_scenario_use_real_worker(kit, kind, tmp_path):
    source = kit["files"][kind]
    runtime = Runtime(
        tmp_path / "app", initialize=True, modules=ModuleRegistry((module_manifest(),))
    )
    session = runtime.auth.setup("desktop-synthetic-admin", "synthetic-desktop-password")
    actor = runtime.auth.authenticate(session["access_token"])
    service = AccountingService(runtime)
    runtime.start()
    try:
        book = service.create_book(actor, **kit["book"], request_key=_key())
        with Path(source["path"]).open("rb") as stream:
            stored = runtime.files.put(
                stream,
                category="workbooks",
                original_name=Path(source["path"]).name,
                actor=actor.id,
                request_key=_key(),
                authorize=service.authorize(actor),
            )
        batch = service.create_batch(actor, book["id"], stored.id, source["profile"], _key())
        batch = _wait(service, actor, batch["id"])
        batch = service.mapping(actor, batch["id"], batch["version"], source["mapping"], {}, _key())
        service.validate(actor, batch["id"], batch["version"], _key())
        batch = _wait(service, actor, batch["id"])
        assert batch["counts"]["valid"] == source["expected"]["valid"] == 983
        assert batch["counts"]["invalid"] == 17
        assert batch["counts"]["eligible"] == 963
        with runtime.reader() as connection:
            actual = [
                json.loads(value)
                for value in connection.execute(
                    select(s.issues.c.issue_json).where(s.issues.c.batch_id == batch["id"])
                ).scalars()
            ]
            warning_rows = (
                connection.execute(
                    select(s.stage.c.row_id).where(
                        s.stage.c.batch_id == batch["id"], s.stage.c.duplicate_count > 0
                    )
                )
                .scalars()
                .all()
            )
        expected = _jsonl(source["issue_jsonl"])
        fields = tuple(expected[0])

        def project(issue):
            return tuple(issue[field] for field in fields)

        assert sorted(map(project, actual)) == sorted(map(project, expected))
        assert len(warning_rows) == source["expected"]["duplicate_warning_rows"] == 20
        sheet = source["profile"]["sheet_id"]
        batch = service.decisions(
            actor,
            batch["id"],
            batch["version"],
            [{"row_id": f"{sheet}:5", "decision": "skip"}],
            "keep",
            _key(),
        )
        scenario = source["scenarios"]["skip_first_duplicate"]
        assert batch["counts"]["eligible"] == scenario["first_published"] == 982
        batch = _confirm(service, actor, batch)
        assert service.list_rows(actor, book["id"])["total"] == 982
        assert (
            service.summary(actor, book["id"], "2026-01-01", "2026-01-31")["totals"]["VND"][
                "income"
            ]
            == scenario["first_income"]
        )
        invalid = {
            row["source_row"]: row
            for row in service.staging_page(actor, batch["id"], status="invalid")["items"]
        }
        patches = [
            {
                "row_id": invalid[repair["source_row"]]["row_id"],
                "expected_version": invalid[repair["source_row"]]["revision"],
                "values": repair["values"],
            }
            for repair in _jsonl(source["repair_jsonl"])
        ]
        assert len(patches) == 17
        batch = service.patch_staging(actor, batch["id"], batch["version"], patches, _key())
        service.validate(actor, batch["id"], batch["version"], _key())
        batch = _wait(service, actor, batch["id"])
        batch = _confirm(service, actor, batch)
        assert service.list_rows(actor, book["id"])["total"] == scenario["final_published"] == 999
        assert batch["counts"]["excluded"] == 1
        assert (
            service.summary(actor, book["id"], "2026-01-01", "2026-01-31")["totals"]["VND"][
                "income"
            ]
            == scenario["final_income"]
        )
        assert _hash(source["path"]) == source["sha256"]
    finally:
        runtime.close()


def test_deterministic_sources_and_honest_inert_macro_metadata(kit, tmp_path):
    other = generate_fixture_kit(tmp_path / "other")
    for kind, source in kit["files"].items():
        assert source["sha256"] == other["files"][kind]["sha256"]
        with Path(source["path"]).open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == source["sha256"]
    macro = kit["files"]["xlsm"]["macro_fixture"]
    assert macro["valid_vba_project"] is False and macro["execution_claim"] is False
    with ZipFile(kit["files"]["xlsm"]["path"]) as archive:
        assert archive.read(macro["entry"]) == SENTINEL
        assert all(info.date_time == (2026, 1, 1, 0, 0, 0) for info in archive.infolist())
        assert archive.testzip() is None
    on_disk = json.loads(Path(kit["manifest_path"]).read_text(encoding="utf-8"))
    assert "manifest_artifact" not in on_disk
    assert _hash(kit["manifest_path"]) == kit["manifest_artifact"]["sha256"]


@pytest.mark.parametrize("rows", [0, -1, True, 1.0, MAX_ROWS + 1])
def test_invalid_geometry_does_not_create_root(tmp_path, rows):
    root = tmp_path / "invalid"
    with pytest.raises(ValueError, match="rows"):
        generate_fixture_kit(root, rows)
    assert not root.exists()


def test_existing_root_and_any_git_worktree_are_rejected(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    marker = existing / "preserved.txt"
    marker.write_text("synthetic marker", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh"):
        generate_fixture_kit(existing)
    assert marker.read_text(encoding="utf-8") == "synthetic marker"
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    (fake_repo / ".git").write_text("gitdir: synthetic", encoding="utf-8")
    with pytest.raises(ValueError, match="outside"):
        generate_fixture_kit(fake_repo / "sources")
    with pytest.raises(ValueError, match="outside"):
        generate_fixture_kit(Path(__file__).parent / "must-not-be-created")

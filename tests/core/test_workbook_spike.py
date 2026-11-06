import hashlib
import io
import zipfile

from cafe_fin.core.db import Database, WriteCoordinator
from cafe_fin.core.storage import MIGRATIONS, DataRootService, FileStore
from cafe_fin.core.workbook_spike import WorkbookSpike, preview_workbook, synthetic_workbook


def test_workbook_values_formulas_coordinates_and_bounded_paging():
    content = synthetic_workbook(rows=1200)
    assert content == synthetic_workbook(rows=1200)
    original_hash = hashlib.sha256(content).hexdigest()
    first = preview_workbook(content, page=1, page_size=500)
    assert first["total"] == 1200 and len(first["items"]) == 500
    row = first["items"][0]
    assert row["code"] == "00000001"
    assert row["occurred_on"] == "2026-11-06"
    assert row["amount"] == "92233720368547758.07"
    assert row["formula"] == "=SUM(D2:D3)"
    assert {issue["cell"] for issue in row["issues"]} == {"D2", "E2"}
    assert "Cà phê" in row["description"]
    assert preview_workbook(content, page=3, page_size=500)["items"][0]["source_row"] == 1002
    assert len(preview_workbook(content, page=3, page_size=500)["items"]) == 200
    assert preview_workbook(content, page=4, page_size=500)["items"] == []
    assert hashlib.sha256(content).hexdigest() == original_hash


def test_opaque_macro_and_external_members_are_never_executed_or_resaved(tmp_path):
    content = synthetic_workbook(rows=10, opaque_macro_marker=True)
    root = DataRootService(tmp_path / "Nguồn mẫu macro tổng hợp").initialize()
    db = Database(root.database_path)
    db.migrate(MIGRATIONS)
    writer = WriteCoordinator(db)
    files = FileStore(root, db, writer)
    stored = files.put(
        io.BytesIO(content),
        category="workbooks",
        original_name="synthetic-marker.xlsm",
        actor="synthetic",
        request_key="macro-source",
    )
    assert len(preview_workbook(content, page=1, page_size=5)["items"]) == 5
    with files.read(stored.id) as original:
        unchanged = original.read()
    assert unchanged == content
    with zipfile.ZipFile(io.BytesIO(unchanged)) as archive:
        assert archive.read("xl/vbaProject.bin") == b"CAFE_FIN_SYNTHETIC_NON_EXECUTABLE_MARKER"
        assert "xl/externalLinks/externalLink1.xml" in archive.namelist()
    # This proves opaque container bytes, not a valid executable VBA project or Excel fidelity.
    writer.close()
    db.close()


def test_paged_source_replay_does_not_accumulate_unreferenced_copies(tmp_path):
    root = DataRootService(tmp_path / "workbook-source").initialize()
    db = Database(root.database_path)
    db.migrate(MIGRATIONS)
    writer = WriteCoordinator(db)
    files = FileStore(root, db, writer)
    spike = WorkbookSpike(files)
    first = spike.page(actor="synthetic", page=1, page_size=500)
    second = spike.page(actor="synthetic", page=2, page_size=500)
    assert first["source_file_id"] == second["source_file_id"]
    assert files.reconcile()["orphan_keys"] == []
    writer.close()
    db.close()

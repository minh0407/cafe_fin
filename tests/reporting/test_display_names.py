import copy
import hashlib
import io
import unicodedata

from cafe_fin.core.contracts import CONTRACT_VERSION
from cafe_fin.core.db import canonical_json
from cafe_fin.reporting import exports, models
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.sources import SourceBundle
from openpyxl import load_workbook
from pypdf import PdfReader

from tests.reporting.conftest import TypedSyntheticSource, preview_command


class NamedSource(TypedSyntheticSource):
    label = "Cà phê <b>& =1+1"

    def capture(self, *args):
        bundle = super().capture(*args)
        names = {"product_name": self.label, "warehouse_name": "Kho <b>&"}
        inventory = bundle.inventory.model_copy(
            update={
                "items": tuple(
                    type(item).model_validate({**item.model_dump(), **names})
                    for item in bundle.inventory.items
                ),
                "movement_breakdown": tuple(
                    type(item).model_validate({**item.model_dump(), **names})
                    for item in bundle.inventory.movement_breakdown
                ),
            }
        )
        books = tuple(
            type(book).model_validate(
                {**book.model_dump(), "book_name": "Quỹ <b>& =SUM(1,2)\n\x00\u202eTiền mặt"}
            )
            for book in bundle.books
        )
        return SourceBundle(inventory, books, consistency=bundle.consistency)


def test_v3_frozen_display_names_render_literal_text_all_formats_without_merging_ids(env):
    source = NamedSource()
    service = ReportingService(env.runtime, source=source)
    report = service.preview(env.actor, preview_command("named"))
    snapshot = report["snapshot"]
    assert snapshot["bridge_contract_version"] == CONTRACT_VERSION == 3
    assert snapshot["sources"]["inventory"]["items"][0]["product_name"] == source.label
    groups = {row[0] for row in exports.summary_rows(snapshot) if row[1] == "Cuối kỳ (kg)"}
    assert len(groups) == 3  # equal names keep all distinct ID-based scopes
    assert all("Kho <b>&" in name and source.label in name for name in groups)
    movement_only = copy.deepcopy(snapshot)
    for item in movement_only["sources"]["inventory"]["items"]:
        item.pop("warehouse_name", None)
        item.pop("product_name", None)
    assert {
        row[0] for row in exports.summary_rows(movement_only) if row[1] == "Cuối kỳ (kg)"
    } == groups
    report = service.save(
        env.actor, report["id"], models.Save(request_key="named-save", expected_version=1)
    )
    for format in ("pdf", "xlsx", "txt"):
        item = service.export(
            env.actor, report["id"], models.Export(request_key="named-" + format, format=format)
        )
        with env.runtime.files.read(item["file_id"]) as stream:
            content = stream.read()
        if format == "pdf":
            text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)
            text = " ".join(text.split())
            assert "Kho <b>&" in text and "Cà phê <b>& =1+1" in text
        elif format == "xlsx":
            sheet = load_workbook(io.BytesIO(content)).active
            cells = [cell for row in sheet for cell in row if cell.value]
            assert all(cell.data_type == "s" for cell in cells)
            text = " ".join(str(cell.value) for cell in cells)
            assert source.label in text
        else:
            text = content.decode("utf-8")
            assert source.label in text and len(text) <= 1800
            assert "Tồn tổng: 7.000 kg" in text
        assert "Quỹ <b>& =SUM(1,2) Tiền mặt" in text
        assert source.malicious not in text
        assert not any(
            unicodedata.category(char).startswith("C") for char in text if char not in "\n\t"
        )
    before = service.detail(report["id"])
    source.label = "Tên mới chỉ dùng cho snapshot mới"
    assert service.detail(report["id"])["snapshot"] == before["snapshot"] and source.calls == 1


def test_saved_v2_snapshot_and_stored_export_bytes_are_not_enriched_or_rewritten(env, monkeypatch):
    import cafe_fin.reporting.service as service_module

    source = NamedSource()
    service = ReportingService(env.runtime, source=source)
    build = service_module.build_snapshot

    def old_snapshot(*args):
        snapshot = build(*args)
        snapshot["bridge_contract_version"] = 2
        inventory = snapshot["sources"]["inventory"]
        for item in inventory["items"] + inventory["movement_breakdown"]:
            item.pop("product_name", None)
            item.pop("warehouse_name", None)
        for book in snapshot["sources"]["books"]:
            book.pop("book_name", None)
        snapshot["source_sha256"] = hashlib.sha256(
            canonical_json(snapshot["sources"]).encode()
        ).hexdigest()
        return snapshot

    monkeypatch.setattr(service_module, "build_snapshot", old_snapshot)
    report = service.preview(env.actor, preview_command("legacy-v2"))
    original_snapshot = copy.deepcopy(report["snapshot"])
    report = service.save(
        env.actor, report["id"], models.Save(request_key="old-save", expected_version=1)
    )
    assert "Kho 1 / Loại 1" in {row[0] for row in exports.summary_rows(original_snapshot)}
    assert "Sổ 1:" in exports.short_message(original_snapshot, 1, report["sha256"])
    stored = {}
    for format in ("pdf", "xlsx", "txt"):
        item = service.export(
            env.actor, report["id"], models.Export(request_key="old-" + format, format=format)
        )
        with env.runtime.files.read(item["file_id"]) as stream:
            stored[format] = (item, stream.read())
    source.label = "Tên live không được ghi vào báo cáo cũ"
    monkeypatch.setattr(service_module, "build_snapshot", build)
    monkeypatch.setattr(
        exports, "render", lambda *args: (_ for _ in ()).throw(AssertionError("No rewrite"))
    )
    for format, (item, content) in stored.items():
        assert (
            service.export(
                env.actor, report["id"], models.Export(request_key="old-" + format, format=format)
            )
            == item
        )
        with env.runtime.files.read(item["file_id"]) as stream:
            assert stream.read() == content
    preserved = service.detail(report["id"])
    assert preserved["snapshot"] == original_snapshot and preserved["sha256"] == report["sha256"]
    assert preserved["snapshot"]["bridge_contract_version"] == 2 and source.calls == 1


def test_short_name_labels_flatten_controls_and_keep_1800_cap(env):
    source = NamedSource()
    snapshot = ReportingService(env.runtime, source=source).preview(
        env.actor, preview_command("long-names")
    )["snapshot"]
    for book in snapshot["sources"]["books"]:
        book["book_name"] = "Tên\n\r\t\x00\u202e" + "Sổ rất dài " * 20
    text = exports.short_message(snapshot, 1, "a" * 64)
    assert len(text) <= 1800 and "\r" not in text and "\x00" not in text and "\u202e" not in text
    assert "Sổ 1 (Tên Sổ rất dài" in text
    assert "chưa đủ dữ liệu" in text  # missing mapping stays unavailable, never zero

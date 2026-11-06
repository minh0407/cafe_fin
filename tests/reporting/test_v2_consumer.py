import io

from cafe_fin.reporting import models
from cafe_fin.reporting.service import ReportingService
from conftest import TypedSyntheticSource, preview_command
from openpyxl import load_workbook
from pypdf import PdfReader


def test_real_v2_dto_snapshot_stock_components_cash_subsets_no_double_count(env):
    source = TypedSyntheticSource()
    service = ReportingService(env.runtime, source=source)
    preview = service.preview(env.actor, preview_command("typed-v2"))
    snapshot = preview["snapshot"]
    assert snapshot["bridge_contract_version"] == 2
    assert len(snapshot["production"]) == 3
    assert "PRODUCTION_BREAKDOWN_UNAVAILABLE" not in snapshot["warnings"]
    assert "UNINTERPRETED_MONEY_METRICS" in snapshot["warnings"]
    assert snapshot["hold"] is None  # no QC/hold/approval workflow introduced
    row = service.save(
        env.actor, preview["id"], models.Save(request_key="typed-save", expected_version=1)
    )
    message = service.detail(row["id"])["short_message"]
    assert "Nhập tổng: 16.000 kg" in message and "Mua: 10.000 kg" in message
    assert "Bán: 2.000 kg" in message and "Vào sản xuất: 4.000 kg" in message
    assert "Sản xuất ra: 3.000 kg" in message and "Tồn tổng: 7.000 kg" in message
    assert f"Tổng thu tiền {source.amount}" in message
    assert "Cọc thu (trong thu) 100.00" in message and "Cọc chi (trong chi) 20.00" in message
    assert "Đối trừ không tiền 50.03" in message
    assert "999999.99" not in message and "9876543210.01" not in message
    assert source.malicious not in message
    for format in ("pdf", "xlsx"):
        exported = service.export(
            env.actor, row["id"], models.Export(request_key="typed-" + format, format=format)
        )
        with env.runtime.files.read(exported["file_id"]) as stream:
            content = stream.read()
        if format == "pdf":
            text = "".join(
                page.extract_text() for page in PdfReader(io.BytesIO(content)).pages
            ).replace("\n", "")
        else:
            sheet = load_workbook(io.BytesIO(content)).active
            text = "".join(str(cell.value) for line in sheet for cell in line if cell.value)
        assert source.amount in text
        assert "999999.99" not in text and "9876543210.01" not in text
        assert source.malicious not in text

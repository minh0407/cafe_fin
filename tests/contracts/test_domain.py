"""Synthetic contract domain checks, including real independent local encoders."""

import copy
import io

import pytest
from cafe_fin.contracts.rendering import (
    DEFAULT_TEMPLATES,
    TOKENS,
    build_document,
    money_in_words,
    template_hash,
    totals,
    validate_template,
)
from cafe_fin.contracts.schemas import TEMPLATE_IDS, ContractData
from cafe_fin.core.errors import CoreError
from cafe_fin.core.renderers import DocumentRenderer
from docx import Document
from pydantic import ValidationError
from pypdf import PdfReader


def contract_payload(kind="purchase"):
    return {
        "kind": kind,
        "number": "HĐ-00001",
        "occurred_on": "2026-11-06",
        "place": "Buôn Ma Thuột",
        "template_id": TEMPLATE_IDS[kind],
        "company": {
            "type": "company",
            "name": "Doanh nghiệp thử Cà phê Việt",
            "contacts": [{"kind": "phone", "value": "0000000000"}],
            "bank_details": [{"bank_name": "Ngân hàng tổng hợp", "account_number": "00001"}],
        },
        "counterparty": {"type": "individual", "name": "Đối tác thử Nguyễn Thị Ánh"},
        "lines": [{"description": "Cà phê nhân", "quantity_kg": "1.005", "unit_price": "1"}],
    }


def template(kind="purchase"):
    row = next(row for row in DEFAULT_TEMPLATES if row["kind"] == kind)
    return {"title": row["title"], "body": row["body"]}


@pytest.mark.parametrize(
    "mode,rate,net,tax,grand",
    [
        ("unspecified", None, None, None, None),
        ("none", None, "108.00", "0.00", "108.00"),
        ("exclusive", "8", "108.00", "8.64", "116.64"),
        ("inclusive", "8", "100.00", "8.00", "108.00"),
        ("exclusive", "0", "108.00", "0.00", "108.00"),
        ("inclusive", "100", "54.00", "54.00", "108.00"),
    ],
)
def test_tax_modes(mode, rate, net, tax, grand):
    payload = contract_payload()
    payload["lines"] = [{"description": "Hàng", "quantity_kg": "1", "unit_price": "108"}]
    payload["tax"] = {"mode": mode, **({"rate": rate} if rate is not None else {})}
    result = totals(ContractData.model_validate(payload))
    assert result["subtotal"] == "108.00"
    assert (result["net_amount"], result["tax_amount"], result["grand_total"]) == (net, tax, grand)
    assert (result["amount_in_words"] is None) == (grand is None)


def test_line_half_up_precedes_contract_tax():
    payload = contract_payload()
    payload["lines"] *= 3
    payload["tax"] = {"mode": "exclusive", "rate": "10"}
    result = totals(ContractData.model_validate(payload))
    assert result["line_amounts"] == ["1.01"] * 3
    assert result["subtotal"] == "3.03"
    assert result["tax_amount"] == "0.30"
    assert result["grand_total"] == "3.33"
    assert result["quantity_kg"] == "3.015"


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity_kg", "0"),
        ("quantity_kg", "-1"),
        ("quantity_kg", "0.0001"),
        ("quantity_kg", 1.5),
        ("unit_price", "-1"),
        ("unit_price", "1.001"),
        ("unit_price", "NaN"),
        ("unit_price", "1e3"),
        ("unit_price", "01"),
        ("unit_price", "92233720368547758.08"),
    ],
)
def test_invalid_line_amounts(field, value):
    payload = contract_payload()
    payload["lines"][0][field] = value
    with pytest.raises(ValidationError):
        ContractData.model_validate(payload)


@pytest.mark.parametrize(
    "tax",
    [
        {"mode": "exclusive"},
        {"mode": "inclusive", "rate": "100.01"},
        {"mode": "none", "rate": "0"},
        {"mode": "unspecified", "rate": "8"},
        {"mode": "exclusive", "rate": "8.123"},
        {"mode": "inclusive", "rate": "-1"},
    ],
)
def test_invalid_tax(tax):
    payload = contract_payload()
    payload["tax"] = tax
    with pytest.raises(ValidationError):
        ContractData.model_validate(payload)


@pytest.mark.parametrize(
    "occurred_on", ["2026-02-30", "2026-1-01", "06/11/2026", "2026-11-06T00:00:00"]
)
def test_date_strings(occurred_on):
    payload = contract_payload()
    payload["occurred_on"] = occurred_on
    with pytest.raises(ValidationError):
        ContractData.model_validate(payload)


def test_product_sum_and_tax_overflow_rejected():
    payload = contract_payload()
    payload["lines"][0].update(quantity_kg="100", unit_price="92233720368547758.07")
    with pytest.raises(ValidationError):
        ContractData.model_validate(payload)
    payload["lines"][0]["quantity_kg"] = "1"
    payload["lines"] = [copy.deepcopy(payload["lines"][0]) for _ in range(2)]
    with pytest.raises(ValidationError):
        ContractData.model_validate(payload)
    payload["lines"] = payload["lines"][:1]
    payload["tax"] = {"mode": "exclusive", "rate": "0.01"}
    with pytest.raises(ValidationError):
        ContractData.model_validate(payload)


def test_duplicate_source_ignores_version_but_allows_independent_contracts():
    payload = contract_payload()
    source = {
        "type": "weighing",
        "id": "00000000-0000-4000-8000-000000000001",
        "version": 1,
        "line_index": 0,
    }
    payload["lines"][0]["source"] = source
    first = ContractData.model_validate(payload)
    assert ContractData.model_validate(payload) == first
    duplicate = copy.deepcopy(payload["lines"][0])
    duplicate["source"]["version"] = 2
    payload["lines"].append(duplicate)
    with pytest.raises(ValidationError, match="Một dòng phiếu cân nguồn"):
        ContractData.model_validate(payload)
    duplicate["source"]["line_index"] = 1
    assert len(ContractData.model_validate(payload).lines) == 2


def test_source_snapshot_stays_distinct_from_selected_quantity():
    payload = contract_payload()
    source = {
        "type": "weighing",
        "id": "00000000-0000-4000-8000-000000000001",
        "version": 2,
        "line_index": 0,
        "code": "CÂN-0001",
        "occurred_on": "2026-11-05",
    }
    payload["lines"][0].update(
        source=source, source_snapshot={"net_kg": "500", "note": "Nguồn"}, quantity_kg="250"
    )
    data = ContractData.model_validate(payload)
    computed = totals(data)
    body = "\n".join(build_document(data, computed, template()).paragraphs)
    assert computed["quantity_kg"] == "250.000"
    assert computed["subtotal"] == "250.00"
    assert "Nguồn phiếu cân: CÂN-0001; phiên bản 2; dòng 1; ngày 2026-11-05" in body
    assert "Số cân nguồn (bản chụp): tịnh (kg): 500" in body
    assert payload["lines"][0]["source_snapshot"]["net_kg"] == "500"
    for invalid in ("-1", "0.0001", "bad"):
        payload["lines"][0]["source_snapshot"]["net_kg"] = invalid
        with pytest.raises(ValidationError):
            ContractData.model_validate(payload)


def test_weighing_identity_must_be_uuid():
    payload = contract_payload()
    payload["lines"][0]["source"] = {
        "type": "weighing",
        "id": "not-a-uuid",
        "version": 1,
        "line_index": 0,
    }
    with pytest.raises(ValidationError):
        ContractData.model_validate(payload)


@pytest.mark.parametrize(
    "amount,words",
    [
        ("0.00", "Không đồng"),
        ("0.01", "Không đồng và một phần trăm đồng"),
        ("1.05", "Một đồng và năm phần trăm đồng"),
        ("15", "Mười lăm đồng"),
        ("21", "Hai mươi mốt đồng"),
        ("105", "Một trăm lẻ năm đồng"),
        ("1005", "Một nghìn không trăm lẻ năm đồng"),
        ("1000000001", "Một tỷ không trăm lẻ một đồng"),
        ("-25.50", "Âm hai mươi lăm đồng và năm mươi phần trăm đồng"),
    ],
)
def test_vietnamese_words_exact(amount, words):
    assert money_in_words(amount) == words


@pytest.mark.parametrize("kind", ["purchase", "sale"])
@pytest.mark.parametrize(
    "method,label",
    [
        ("cash", "Tiền mặt"),
        ("bank", "Chuyển khoản"),
        ("mixed", "Kết hợp tiền mặt và chuyển khoản"),
        ("other", "Khác"),
    ],
)
def test_all_structured_payment_and_terms_are_literal_in_both_formats(kind, method, label):
    payload = contract_payload(kind)
    payload["tax"] = {"mode": "none"}
    payload["terms"] = {
        name: f"{name} tiếng Việt\nDòng hai <script>& ký tự"
        for name in (
            "delivery",
            "packaging",
            "quality",
            "deadline",
            "responsibilities",
            "additional",
        )
    }
    payload["payment"] = {
        "method": method,
        "description": "Nội dung trả do người dùng nhập",
        "receiving_account": {
            "bank_name": "Ngân hàng thử",
            "account_number": "00000123",
            "account_holder": "Chủ thử",
        },
        "due_on": "2026-12-01",
        "deposit_amount": "0",
        "recorded_paid_amount": "0",
        "schedule": [{"due_on": "2026-12-02", "amount": "0", "note": "Đợt thử"}],
    }
    data = ContractData.model_validate(payload)
    snapshot = build_document(data, totals(data), template(kind))
    body = "\n".join(snapshot.paragraphs)
    assert not any("{{" + token in body for token in TOKENS)
    assert "Tiền cọc theo điều khoản: 0 VND" in body
    assert "Số đã trả do người dùng ghi nhận: 0 VND" in body
    assert "Đợt 1: 2026-12-02; 0 VND; Đợt thử" in body
    assert (
        body.index("Cà phê nhân")
        < body.index("Tổng khối lượng")
        < body.index("3. THANH TOÁN")
        < body.index("ĐẠI DIỆN BÊN")
    )
    renderer = DocumentRenderer()
    docx = renderer.docx(snapshot)
    pdf = renderer.pdf(snapshot)
    docx_text = "\n".join(p.text for p in Document(io.BytesIO(docx.content)).paragraphs)
    pdf_text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    for text in (docx_text, pdf_text):
        assert label in text
        assert "<script>& ký tự" in text
        assert "00000123" in text
        for name in payload["terms"]:
            assert name + " tiếng Việt" in text
    assert docx.snapshot_sha256 == pdf.snapshot_sha256 == snapshot.sha256


def test_unknown_tax_never_claims_zero_or_total():
    data = ContractData.model_validate(contract_payload())
    body = "\n".join(build_document(data, totals(data), template()).paragraphs)
    assert "Thuế: chưa xác định" in body
    assert "Tổng thanh toán: chưa xác định" in body
    assert "Thuế: không áp dụng" not in body
    assert "Bằng chữ:" not in body


def test_admin_text_flows_to_document_and_template_hash_changes():
    payload = template()
    amended = {**payload, "body": "Lời mở đầu sửa bởi quản trị\n\n" + payload["body"]}
    data = ContractData.model_validate(contract_payload())
    snapshot = build_document(data, totals(data), amended)
    assert snapshot.paragraphs[0] == "Lời mở đầu sửa bởi quản trị"
    assert template_hash(amended) != template_hash(payload)
    assert validate_template(payload) == payload
    for body in (
        payload["body"] + "{{unknown}}",
        payload["body"] + "{{bad",
        payload["body"].replace("{{goods}}", ""),
    ):
        with pytest.raises(CoreError, match="CONTRACT_TEMPLATE_INVALID"):
            validate_template({**payload, "body": body})


def test_stale_or_forged_totals_rejected():
    data = ContractData.model_validate(contract_payload())
    with pytest.raises(CoreError, match="CONTRACT_TOTALS_MISMATCH"):
        build_document(data, {**totals(data), "subtotal": "0.00"}, template())


@pytest.mark.parametrize("location", ["party", "bank", "weight", "reference"])
def test_controls_in_nested_core_inputs_rejected(location):
    payload = contract_payload()
    if location == "party":
        payload["company"]["name"] = "Tên\x00hỏng"
    elif location == "bank":
        payload["payment"] = {
            "receiving_account": {"bank_name": "Tên\x01hỏng", "account_number": "0"}
        }
    elif location == "weight":
        payload["lines"][0]["source_snapshot"] = {"note": "Tên\x02hỏng"}
    else:
        payload["source_refs"] = [{"type": "party", "id": "Tên\x00hỏng", "version": 1}]
    with pytest.raises(ValidationError):
        ContractData.model_validate(payload)


def test_long_unicode_multiple_pages_and_snapshot_independence():
    payload = contract_payload()
    payload["counterparty"]["address"] = "Đắk Lắk ă â đ ê ô ơ ư " * 25
    payload["lines"] = [
        {"description": f"Dòng {n} — Cà phê Đắk Nông", "quantity_kg": "1", "unit_price": "0"}
        for n in range(40)
    ]
    payload["terms"] = {"additional": "Nội dung bổ sung Đắk Lắk. " * 150}
    data = ContractData.model_validate(payload)
    snapshot = build_document(data, totals(data), template())
    original = snapshot.canonical_bytes()
    payload["company"]["name"] = "Đã sửa nguồn"
    pdf = DocumentRenderer().pdf(snapshot)
    reader = PdfReader(io.BytesIO(pdf.content))
    assert len(reader.pages) >= 3
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Dòng 39" in text and "Nội dung bổ sung Đắk Lắk" in text
    assert snapshot.canonical_bytes() == original

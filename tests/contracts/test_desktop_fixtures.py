"""Fixture integrity checks do not substitute for desktop or document visual QA."""

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import pytest
from cafe_fin.contracts.rendering import DEFAULT_TEMPLATES, build_document, totals
from cafe_fin.contracts.schemas import ContractData

from .desktop_fixtures import (
    EXPECTED_DOCUMENT_SHA256,
    EXPECTED_PAYLOAD_SHA256,
    EXPECTED_TOTALS,
    FIXTURE_DATE,
    contract_payloads,
)


def _snapshot(kind, payload):
    data = ContractData.model_validate(payload)
    template = next(item for item in DEFAULT_TEMPLATES if item["kind"] == kind)
    return build_document(data, totals(data), {key: template[key] for key in ("title", "body")})


@pytest.mark.parametrize("kind", ["purchase", "sale"])
def test_payload_is_json_ready_valid_and_frozen_by_literal_hash(kind):
    payload = contract_payloads()[kind]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    assert hashlib.sha256(encoded).hexdigest() == EXPECTED_PAYLOAD_SHA256[kind]
    data = ContractData.model_validate_json(encoded)
    assert data.kind == kind
    assert data.occurred_on == FIXTURE_DATE == "2026-11-08"
    assert str(UUID(data.template_id)) == data.template_id
    for line in data.lines:
        assert str(UUID(line.product_id)) == line.product_id
    assert payload["source_refs"] == []
    assert all("source" not in line for line in payload["lines"])


@pytest.mark.parametrize("kind", ["purchase", "sale"])
def test_totals_match_independent_literal_expectations(kind):
    data = ContractData.model_validate(contract_payloads()[kind])
    actual = totals(data)
    for key, expected in EXPECTED_TOTALS[kind].items():
        assert actual[key] == expected
    assert actual["rounding_policy"] == "line_half_up_0.01_vnd_then_contract_tax_half_up_0.01_vnd"


@pytest.mark.parametrize("kind", ["purchase", "sale"])
def test_literal_expected_numbers_cross_checked_with_decimal_equations(kind):
    # Independent Decimal arithmetic checks the reviewed expectations. This does
    # not ask the product to calculate its own expected answers at assertion time.
    payload = contract_payloads()[kind]
    expected = EXPECTED_TOTALS[kind]
    lines = [
        (Decimal(line["quantity_kg"]) * Decimal(line["unit_price"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        for line in payload["lines"]
    ]
    assert [str(amount) for amount in lines] == expected["line_amounts"]
    assert sum(Decimal(line["quantity_kg"]) for line in payload["lines"]) == Decimal(
        expected["quantity_kg"]
    )
    subtotal = sum(lines)
    assert subtotal == Decimal(expected["subtotal"])
    if kind == "purchase":
        tax = (subtotal * Decimal("0.08")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert tax == Decimal("1901759.04")
        assert subtotal + tax == Decimal("25673747.07")
    else:
        assert subtotal / Decimal("1.08") == Decimal("17325000.00")
        assert subtotal - Decimal("17325000.00") == Decimal("1386000.00")


def test_payload_calls_and_sides_do_not_share_mutable_data():
    first = contract_payloads()
    pristine = contract_payloads()
    first["purchase"]["company"]["bank_details"][0]["account_number"] = "CHANGED"
    first["purchase"]["lines"][0]["quantity_kg"] = "999"
    first["sale"]["payment"]["schedule"].append({"due_on": "2026-11-08", "amount": "0"})
    assert first["sale"]["company"] == pristine["sale"]["company"]
    assert contract_payloads() == pristine


def test_net_only_and_full_weights_are_intentionally_distinct():
    for payload in contract_payloads().values():
        first, full = payload["lines"][:2]
        assert "gross_kg" not in first and "tare_kg" not in first
        assert first["quantity_source"] == "direct"
        assert first["net_kg"] == first["quantity_kg"]
        assert full["quantity_source"] == "gross_minus_tare"
        assert Decimal(full["gross_kg"]) - Decimal(full["tare_kg"]) == Decimal(full["net_kg"])


@pytest.mark.parametrize("kind", ["purchase", "sale"])
def test_base_default_document_snapshot_hash_and_literal_terms(kind):
    payload = contract_payloads()[kind]
    snapshot = _snapshot(kind, payload)
    assert snapshot.sha256 == EXPECTED_DOCUMENT_SHA256[kind]
    text = "\n\n".join(snapshot.paragraphs)
    assert "{{" not in text and "}}" not in text
    assert payload["company"]["name"] in text
    assert payload["counterparty"]["name"] in text
    assert payload["terms"]["additional"] in text
    for name, term in payload["terms"].items():
        assert term in text, name
    assert payload["payment"]["description"] in text
    assert payload["payment"]["receiving_account"]["account_number"] in text
    assert "<script>" in text and "&" in text
    assert "Cách ghi lượng: Nhập kg tịnh trực tiếp" in text
    assert "Cách ghi lượng: Cân đầy trừ cân rỗng" in text
    assert "Cách ghi lượng: direct" not in text
    assert "Cách ghi lượng: gross_minus_tare" not in text
    assert text.index(payload["terms"]["additional"]) < text.index("ĐẠI DIỆN BÊN")


def test_farm_profile_uses_supported_party_and_freeform_contract_fields():
    purchase = contract_payloads()["purchase"]
    assert purchase["counterparty"]["type"] == "farm"
    assert "Farm AB01; mã vùng VÙNG-THỬ-01; lô trồng LÔ-THỬ-02" in purchase["terms"]["additional"]
    assert "farm_code" not in purchase["counterparty"]
    assert "area_code" not in purchase["counterparty"]


@pytest.mark.parametrize("kind", ["purchase", "sale"])
def test_deposit_paid_and_schedule_have_separate_meanings(kind):
    payload = contract_payloads()[kind]
    payment = payload["payment"]
    assert payment["method"] == ("mixed" if kind == "purchase" else "bank")
    assert payment["deposit_amount"] != payment["recorded_paid_amount"]
    assert sum(Decimal(item["amount"]) for item in payment["schedule"]) == Decimal(
        EXPECTED_TOTALS[kind]["grand_total"]
    )
    data = ContractData.model_validate(payload)
    changed = contract_payloads()[kind]
    changed["payment"]["deposit_amount"] = "123.45"
    changed["payment"]["recorded_paid_amount"] = "678.90"
    assert totals(ContractData.model_validate(changed)) == totals(data)
    assert _snapshot(kind, changed).sha256 != EXPECTED_DOCUMENT_SHA256[kind]


def test_long_sale_has_final_line_and_long_clause_before_signatures():
    sale = contract_payloads()["sale"]
    assert len(sale["lines"]) == 18
    text = "\n\n".join(_snapshot("sale", sale).paragraphs)
    assert "Lô hàng thử 18" in text
    assert "KẾT THÚC ĐIỀU KHOẢN DÀI" in text
    assert text.index("KẾT THÚC ĐIỀU KHOẢN DÀI") < text.index("ĐẠI DIỆN BÊN BÁN")

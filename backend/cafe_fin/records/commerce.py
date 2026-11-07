"""Trade identities and shipment limits, evaluated inside the records writer."""

import json
import re
from collections import defaultdict

from sqlalchemy import func

from cafe_fin.core.amounts import kg_string, money_string, parse_kg, parse_money
from cafe_fin.core.errors import CoreError


def normalize(conn, kind, data, old, ref, quantity, deleted=None):
    # Local import keeps the original records service/read bridge dependency stable.
    from .service import get_record, invalid

    def money(value, field, *, positive=False):
        try:
            amount = parse_money(value)
        except CoreError as exc:
            invalid(field, exc.message, exc.code)
        if amount < 0 or (positive and amount == 0):
            invalid(field, "Số tiền phải dương." if positive else "Số tiền không được âm.")
        return money_string(amount)

    if kind == "parties":
        profile = data.setdefault("profile_kind", "general")
        data.setdefault("business_license", None)
        data.setdefault("farm", None)
        if profile == "farm":
            data["code"] = data["code"].strip().upper()
        elif not re.fullmatch(r"\S(?:.*\S)?", data["code"]):
            invalid("code", "Mã hồ sơ không được rỗng hoặc có khoảng trắng ở hai đầu.")
        if old and old.get("profile_kind") == "farm":
            if data["code"] != old["code"] or profile != "farm":
                invalid(
                    "code", "Mã và loại hồ sơ Farm bất biến sau khi tạo.", "FARM_CODE_IMMUTABLE"
                )
        if profile == "farm":
            if not re.fullmatch(r"[A-Z0-9]{4}", data["code"]):
                invalid("code", "Mã Farm phải gồm đúng 4 chữ hoa hoặc chữ số.")
        elif data["farm"] is not None:
            invalid("farm", "Chỉ hồ sơ Farm có thông tin Farm.")
        if data["farm"]:
            for index, plot in enumerate(data["farm"]["plots"]):
                if plot["area_ha"] is not None:
                    plot["area_ha"] = kg_string(
                        quantity(plot["area_ha"], f"farm.plots.{index}.area_ha", positive=False)
                    )
            for index, survey in enumerate(data["farm"]["surveys"]):
                if survey["ripeness_pct"] is not None:
                    field = f"farm.surveys.{index}.ripeness_pct"
                    amount = quantity(survey["ripeness_pct"], field, positive=False)
                    if amount > 100000:
                        invalid(field, "Tỷ lệ chín phải từ 0 đến 100 phần trăm.")
                    survey["ripeness_pct"] = kg_string(amount)
    if kind == "trades":
        ref(data.get("weighing_id"), "weighings", "weighing_id")
        if data["direction"] == "outbound":
            if data["party_id"] is None:
                invalid("party_id", "Đơn đầu ra cần công ty khách hàng.")
            customer = get_record(conn, "parties", data["party_id"])[0]
            if not deleted and data["status"] == "recorded":
                require_customer(customer)
        for index, line in enumerate(data["lines"]):
            prefix = f"lines.{index}"
            ref(line["product_id"], "products", prefix + ".product_id")
            ref(line["farm_id"], "parties", prefix + ".farm_id")
            if data["direction"] == "inbound":
                if line["farm_id"] is None:
                    invalid(prefix + ".farm_id", "Dòng đầu vào cần Farm.")
                farm = get_record(conn, "parties", line["farm_id"])[0]
                if farm.get("profile_kind") != "farm":
                    invalid(prefix + ".farm_id", "Đối tác được chọn phải là Farm.")
            elif line["product_id"] is None:
                invalid(prefix + ".product_id", "Dòng đầu ra cần hàng hóa.")
            line["quantity_kg"] = kg_string(quantity(line["quantity_kg"], prefix + ".quantity_kg"))
            if line["unit_price_vnd"] is not None:
                line["unit_price_vnd"] = money(line["unit_price_vnd"], prefix + ".unit_price_vnd")
    if kind in {"entries", "trade-payments"}:
        data.setdefault("trade_id", None)
        ref(data["trade_id"], "trades", "trade_id")
    if kind == "trade-payments":
        data["amount_vnd"] = money(data["amount_vnd"], "amount_vnd", positive=True)
        if data["party_id"] is None:
            invalid("party_id", "Ghi thu/chi cần đối tác thực tế.")


def require_customer(customer):
    from .service import invalid

    if (
        customer.get("profile_kind") != "customer_company"
        or not customer.get("name", "").strip()
        or not (customer.get("tax_code") or "").strip()
        or not ((customer.get("representative") or {}).get("name") or "").strip()
    ):
        invalid(
            "party_id",
            "Đầu ra cần công ty có tên, người liên hệ/đại diện và MST.",
            "CUSTOMER_INCOMPLETE",
        )


def linked_records(conn, kind, trade_id):
    from .migrations import REVISIONS as R
    from .service import current_query

    query = current_query(kind).where(func.json_extract(R.c.data_json, "$.trade_id") == trade_id)
    return [json.loads(row.data_json) for row in conn.execute(query).mappings()]


def guard(conn, kind, old, result):
    """The candidate revision is already visible; any failure rolls it all back."""
    from .migrations import REFERENCES as F
    from .service import current_query, decimal_total, get_record

    trade_ids = set()
    if kind == "trades":
        trade_ids.add(result["id"])
    elif kind in {"entries", "trade-payments"}:
        trade_ids.update(d.get("trade_id") for d in (old or {}, result))
    elif kind == "parties":
        current = current_query("trades").subquery()
        query = (
            current.select()
            .join(F, (F.c.document_id == current.c.id) & (F.c.version == current.c.version))
            .where(F.c.target_id == result["id"])
        )
        trade_ids.update(row.id for row in conn.execute(query).mappings())

    def conflict(message, trade_id, **details):
        raise CoreError("TRADE_CONFLICT", message, 409, details={"trade_id": trade_id, **details})

    for trade_id in sorted(trade_ids - {None}):
        trade = get_record(conn, "trades", trade_id)[0]
        entries = [
            d
            for d in linked_records(conn, "entries", trade_id)
            if not d["deleted_at"] and d["status"] != "cancelled"
        ]
        payments = [
            d for d in linked_records(conn, "trade-payments", trade_id) if not d["deleted_at"]
        ]
        if trade["deleted_at"] or trade["status"] == "cancelled":
            if entries or payments:
                conflict("Đơn đã xóa/hủy còn phiếu kho hoặc thu/chi hiệu lực.", trade_id)
            continue
        if kind == "trades" and old and (entries or payments):
            if any(old[field] != trade[field] for field in ("direction", "party_id")):
                conflict("Không đổi chiều/đối tác của đơn có chứng từ hiệu lực.", trade_id)
            previous_farms = {line["farm_id"] for line in old["lines"] if line["farm_id"]}
            current_farms = {line["farm_id"] for line in trade["lines"] if line["farm_id"]}
            if previous_farms != current_farms:
                conflict("Không đổi Farm của đơn có chứng từ hiệu lực.", trade_id)
        if trade["direction"] == "outbound":
            require_customer(get_record(conn, "parties", trade["party_id"])[0])
        farms = {line["farm_id"] for line in trade["lines"] if line["farm_id"]}
        for farm_id in farms:
            if get_record(conn, "parties", farm_id)[0].get("profile_kind") != "farm":
                conflict("Farm của đơn không còn đúng loại hồ sơ.", trade_id)
        caps, shipped = defaultdict(int), defaultdict(int)
        for line in trade["lines"]:
            caps[line["product_id"]] += parse_kg(line["quantity_kg"])
        for entry in entries:
            required = "receipt" if trade["direction"] == "inbound" else "issue"
            if entry["entry_type"] != required:
                conflict("Loại phiếu kho không đúng chiều đơn.", trade_id, entry_id=entry["id"])
            if trade["direction"] == "outbound" and entry["party_id"] != trade["party_id"]:
                conflict("Phiếu xuất phải cùng công ty với đơn.", trade_id, entry_id=entry["id"])
            if (
                trade["direction"] == "inbound"
                and entry["party_id"] is not None
                and entry["party_id"] not in farms
            ):
                conflict(
                    "Đối tác phiếu nhập phải là Farm thuộc đơn hoặc để trống khi gộp Farm.",
                    trade_id,
                    entry_id=entry["id"],
                )
            if entry["status"] == "posted":
                for line in entry["lines"]:
                    shipped[line["product_id"]] += parse_kg(line["quantity_kg"])
        for product_id, amount in shipped.items():
            if amount > caps[product_id]:
                conflict(
                    "Tổng kg giao nhận vượt số lượng sản phẩm trong đơn.",
                    trade_id,
                    product_id=product_id,
                    shipped_kg=decimal_total(amount, 3),
                    ordered_kg=decimal_total(caps[product_id], 3),
                )
        for payment in payments:
            valid = (
                payment["party_id"] == trade["party_id"]
                if trade["direction"] == "outbound"
                else payment["party_id"] in farms
            )
            if not valid:
                conflict("Đối tác thu/chi không thuộc đơn.", trade_id, payment_id=payment["id"])

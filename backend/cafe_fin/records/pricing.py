"""Daily prices use immutable records revisions and exact integer cents."""

import json

from sqlalchemy import select

from cafe_fin.core.amounts import money_string, parse_money
from cafe_fin.core.errors import CoreError

from .migrations import DOCUMENTS as D
from .migrations import REVISIONS as R

KINDS = {"purchase_fresh", "purchase_processed", "sale"}
LINE_DEFAULTS = {
    "pricing_mode": "manual",
    "price_kind": None,
    "price_date": None,
    "price_snapshot": None,
}


def preview(data):
    from .service import invalid

    method = data["pricing_method"]
    field = "flat_price_vnd" if method == "flat" else "grade5_price_vnd"
    other = "grade5_price_vnd" if method == "flat" else "flat_price_vnd"
    if data.get(field) is None or data.get(other) is not None:
        invalid(field, "Chỉ nhập đúng loại giá tương ứng phương pháp tính.")
    try:
        amount = parse_money(data[field])
    except CoreError as exc:
        invalid(field, exc.message, exc.code)
    if amount < 0:
        invalid(field, "Giá không được âm.")
    prices = []
    if method == "grade":
        # Nonnegative integer cents: +50 before /100 is ROUND_HALF_UP at each step.
        for grade in (5, 4, 3, 2, 1):
            prices.append({"grade": grade, "unit_price_vnd": money_string(amount)})
            amount = (amount * 90 + 50) // 100
    return {
        "pricing_method": method,
        "flat_price_vnd": money_string(amount) if method == "flat" else None,
        "grade_prices": prices,
        "formula_version": 1,
    }


def normalize_board(data, old, ref):
    from .service import invalid

    for field in ("price_date", "price_kind", "product_id"):
        if old and data[field] != old[field]:
            invalid(field, "Ngày, nhóm giá và hàng hóa bất biến.", "PRICE_KEY_IMMUTABLE")
    if data["price_kind"] == "sale" and not data["product_id"]:
        invalid("product_id", "Giá bán cần chọn hàng hóa.")
    ref(data["product_id"], "products", "product_id")
    values = preview(data)
    data["flat_price_vnd"] = values["flat_price_vnd"]
    data["grade5_price_vnd"] = (
        values["grade_prices"][0]["unit_price_vnd"] if values["grade_prices"] else None
    )
    key = f"{data['price_kind']}:{data['price_date']}:{data['product_id'] or 'all'}"
    data["code"] = key
    data["name"] = f"{data['price_kind']} {data['price_date']}"


def snapshot(board, *, price_kind, price_date, product_id, grade):
    values = preview(board)
    if board["pricing_method"] == "grade":
        if grade is None:
            raise CoreError("PRICE_GRADE_REQUIRED", "Bảng giá này cần chọn Grade.", 422)
        amount = next(
            row["unit_price_vnd"] for row in values["grade_prices"] if row["grade"] == grade
        )
    else:
        amount = values["flat_price_vnd"]
    return {
        "price_board_id": board["id"],
        "price_board_version": board["version"],
        "price_kind": price_kind,
        "price_date": price_date,
        "product_id": product_id,
        "grade": grade,
        "unit_price_vnd": amount,
        "formula_version": 1,
    }


def quote(conn, *, price_kind, price_date, product_id=None, grade=None):
    from .service import current_query

    def extract(key):
        from sqlalchemy import func

        return func.json_extract(R.c.data_json, "$." + key)

    query = current_query("price-boards").where(
        R.c.deleted_at.is_(None),
        extract("active") == True,  # noqa: E712
        extract("price_kind") == price_kind,
        extract("price_date") == price_date,
        extract("product_id").is_(None) | (extract("product_id") == product_id),
    )
    boards = [json.loads(row.data_json) for row in conn.execute(query).mappings()]
    if not boards:
        raise CoreError("PRICE_NOT_FOUND", "Chưa có bảng giá hiệu lực đúng ngày và hàng hóa.", 422)
    board = next((row for row in boards if row["product_id"] == product_id), boards[0])
    return snapshot(
        board, price_kind=price_kind, price_date=price_date, product_id=product_id, grade=grade
    )


def authentic_snapshot(conn, value):
    """Prove the complete quote against an immutable historical board revision."""
    row = conn.execute(
        select(R.c.data_json)
        .join(D, D.c.id == R.c.document_id)
        .where(
            D.c.kind == "price-boards",
            R.c.document_id == value["price_board_id"],
            R.c.version == value["price_board_version"],
        )
    ).first()
    if not row:
        return False
    board = json.loads(row.data_json)
    if (
        board["deleted_at"]
        or not board["active"]
        or board["price_kind"] != value["price_kind"]
        or board["price_date"] != value["price_date"]
        or board["product_id"] not in (None, value["product_id"])
    ):
        return False
    try:
        return value == snapshot(
            board,
            price_kind=value["price_kind"],
            price_date=value["price_date"],
            product_id=value["product_id"],
            grade=value["grade"],
        )
    except CoreError:
        return False


def normalize_trade(conn, data, old, references):
    from .service import invalid

    # Consume prior lines once. Reordering/removal preserves snapshots, copying
    # an old line does not grant extra permission to reuse a stale board revision.
    remaining = list((old or {}).get("lines", []))
    for index, line in enumerate(data["lines"]):
        prefix = f"lines.{index}"
        for key, default in LINE_DEFAULTS.items():
            line.setdefault(key, default)
        if line["pricing_mode"] == "manual":
            if any(line[key] is not None for key in ("price_kind", "price_date", "price_snapshot")):
                invalid(prefix, "Giá thủ công không có nguồn bảng giá.")
            continue
        kind = line["price_kind"] or (
            "sale" if data["direction"] == "outbound" else "purchase_fresh"
        )
        if (data["direction"] == "outbound") != (kind == "sale"):
            invalid(prefix + ".price_kind", "Nhóm giá không đúng chiều đơn.", "PRICE_KIND_MISMATCH")
        line["price_kind"] = kind
        line["price_date"] = line["price_date"] or data["occurred_on"]
        criteria = {
            "price_kind": kind,
            "price_date": line["price_date"],
            "product_id": line["product_id"],
            "grade": line["grade"],
        }
        value = line["price_snapshot"]
        if value and any(value[key] != expected for key, expected in criteria.items()):
            invalid(
                prefix + ".price_snapshot",
                "Nguồn giá không khớp tiêu chí dòng.",
                "PRICE_SNAPSHOT_INVALID",
            )
        prior = None
        for candidate in remaining:
            if (
                old["direction"] == data["direction"]
                and old["occurred_on"] == data["occurred_on"]
                and candidate.get("pricing_mode") == "daily"
                and candidate.get("farm_id") == line["farm_id"]
                and all(candidate.get(key) == expected for key, expected in criteria.items())
            ):
                if candidate.get("price_snapshot") == value or value is None:
                    prior = candidate
                    break
        if old and value is None:
            invalid(
                prefix + ".price_snapshot",
                "Giữ nguồn giá đã lưu hoặc chủ động chọn giá mới.",
                "PRICE_SNAPSHOT_REQUIRED",
            )
        reused = bool(prior and value == prior.get("price_snapshot"))
        if reused:
            remaining.remove(prior)
        if value is not None and not authentic_snapshot(conn, value):
            invalid(
                prefix + ".price_snapshot", "Nguồn giá không xác thực.", "PRICE_SNAPSHOT_INVALID"
            )
        if not reused:
            try:
                current = quote(conn, **criteria)
            except CoreError as exc:
                if value is not None and exc.code in {"PRICE_NOT_FOUND", "PRICE_GRADE_REQUIRED"}:
                    raise CoreError(
                        "PRICE_CHANGED", "Bảng giá không còn áp dụng; lấy lại giá và xác nhận.", 409
                    ) from None
                raise
            if value is not None and value != current:
                raise CoreError(
                    "PRICE_CHANGED", "Bảng giá đã thay đổi; lấy lại giá và xác nhận.", 409
                )
            value = current
        if line["unit_price_vnd"] is not None and line["unit_price_vnd"] != value["unit_price_vnd"]:
            invalid(
                prefix + ".unit_price_vnd",
                "Đơn giá phải đúng nguồn giá đã xác nhận.",
                "PRICE_MISMATCH",
            )
        if reused and prior["unit_price_vnd"] != value["unit_price_vnd"]:
            invalid(
                prefix + ".price_snapshot",
                "Nguồn giá cũ không khớp đơn giá đã lưu.",
                "PRICE_SNAPSHOT_INVALID",
            )
        line["price_snapshot"] = value
        line["unit_price_vnd"] = value["unit_price_vnd"]
        references.add(value["price_board_id"])

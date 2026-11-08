"""CSV v1 definition; only named mini/checkpoint workloads bypass large-slot gates."""

import csv
import json
from datetime import date, timedelta

from .transport import sha256


def amount(index):
    cents = 10000 + index % 100000
    return f"{cents // 100}.{cents % 100:02d}"


def generate_bulk_csv(root, rows):
    root.mkdir(parents=True, exist_ok=False)
    columns = [
        {"id": "code", "name": "Mã", "kind": "text", "required": True},
        {"id": "day", "name": "Ngày", "kind": "date", "required": True},
        {"id": "amount", "name": "Thu VND", "kind": "money", "precision": 19, "required": True},
        {"id": "quantity", "name": "Khối lượng", "kind": "decimal", "scale": 3, "required": True},
        {"id": "category", "name": "Loại", "kind": "choice", "choices": ["Robusta", "Arabica"]},
        {"id": "note", "name": "Ghi chú", "kind": "text"},
        {"id": "currency", "name": "Đơn vị tiền", "kind": "choice", "choices": ["VND"]},
        {"id": "warehouse", "name": "Kho tham khảo", "kind": "text"},
    ]
    source, repairs = root / "bulk-source.csv", root / "bulk-repairs.jsonl"
    first_cents = final_cents = invalid = duplicates = 0
    with (
        source.open("x", encoding="utf-8-sig", newline="") as stream,
        repairs.open("x", encoding="utf-8") as repair_stream,
    ):
        writer = csv.writer(stream)
        writer.writerow([column["name"] for column in columns])
        for index in range(1, rows + 1):
            original = index - 1 if index % 1000 == 2 else index
            cents, milli = 10000 + original % 100000, 1000 + original % 1000
            final_cents += cents
            if index % 1000 == 0:
                invalid += 1
                repair_stream.write(
                    json.dumps(
                        {
                            "source_sheet": "csv",
                            "source_row": index + 1,
                            "values": {"amount": amount(index)},
                        }
                    )
                    + "\n"
                )
            else:
                first_cents += cents
            duplicates += int(index % 1000 == 2)
            writer.writerow(
                [
                    f"{original:012d}",
                    (date(2026, 1, 1) + timedelta(days=original % 28)).isoformat(),
                    "INVALID_AMOUNT" if index % 1000 == 0 else amount(original),
                    f"{milli // 1000}.{milli % 1000:03d}",
                    "Robusta" if original % 2 else "Arabica",
                    "=literal source text"
                    if original % 113 == 0
                    else "Cà phê tổng hợp, kiểm chứng",
                    "VND",
                    "LOCAL-01",
                ]
            )
    source_info = {
        "path": str(source),
        "sha256": sha256(source),
        "bytes": source.stat().st_size,
        "profile": {"sheet_id": "csv", "header_row": 1, "date_format": "%Y-%m-%d"},
        "mapping": {column["id"]: chr(65 + index) for index, column in enumerate(columns)},
        "expected": {
            "source_rows": rows,
            "valid": rows - invalid,
            "invalid": invalid,
            "duplicate_warning_rows": duplicates * 2,
        },
        "repair_jsonl": {"path": str(repairs), "sha256": sha256(repairs)},
        "scenarios": {
            "keep_all": {
                "first_published": rows - invalid,
                "final_published": rows,
                "first_income": f"{first_cents // 100}.{first_cents % 100:02d}",
                "final_income": f"{final_cents // 100}.{final_cents % 100:02d}",
            }
        },
    }
    return {
        "kit_version": "accounting-csv-v1",
        "synthetic_only": True,
        "rows": rows,
        "book": {
            "name": "Desktop CSV volume v1",
            "columns": columns,
            "semantics": {
                "date_column": "day",
                "income_column": "amount",
                "currency_column": "currency",
                "business_key_columns": ["code"],
            },
        },
        "files": {"csv": source_info},
    }

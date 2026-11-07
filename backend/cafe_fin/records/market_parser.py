"""Gia Lai green Robusta adapter, based on the owner's BangGiaNongSan collector.

Never infer publication date from the machine clock or historical chart series.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from .market_http import MAX_HTML_BYTES, SOURCE_URL, MarketError

PriceRejected = MarketError

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
BANGGIANONGSAN_URL = SOURCE_URL
LABEL = "cà phê gia lai (đồng/kg)"


def normalize(value):
    return " ".join(value.lower().split())


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts, self.tables, self.dates = [], [], []
        self.script = self.table = self.row = self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self.script = []
        if tag == "meta" and attrs.get("property") == "article:modified_time":
            self.dates.append(attrs.get("content", ""))
        if tag == "table":
            if self.table is not None:
                raise MarketError("SOURCE_CHANGED", "Bảng nguồn lồng nhau không được hỗ trợ.")
            self.table = []
        if tag == "tr" and self.table is not None:
            self.row = []
        if tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        elif self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            self.scripts.append("".join(self.script))
            self.script = None
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(normalize("".join(self.cell)))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        if tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def source_day(value):
    try:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            raise ValueError()
        return timestamp.astimezone(VN_TZ).date()
    except (ValueError, TypeError, OverflowError):
        raise PriceRejected(
            "MISSING_SOURCE_DATE", "Nguồn thiếu thời điểm công bố hợp lệ có múi giờ."
        )


def price(value, *, displayed=False):
    try:
        if isinstance(value, bool):
            raise ValueError()
        if displayed:
            if not re.fullmatch(r"\d{2,3}([.,]\d{3})?", value):
                raise ValueError()
            value = value.replace(".", "").replace(",", "")
        result = Decimal(str(value))
        if not result.is_finite() or not Decimal("10000") <= result <= Decimal("500000"):
            raise ValueError()
        if result != result.quantize(Decimal(".01")):
            raise ValueError()
        return result.quantize(Decimal(".01"))
    except (InvalidOperation, ValueError, TypeError):
        raise PriceRejected(
            "INVALID_PRICE",
            "Giá nguồn không phải một số VND/kg hợp lệ trong khoảng 10.000–500.000.",
        )


def nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from nodes(item)
    elif isinstance(value, dict):
        yield value
        yield from nodes(value.get("@graph", []))


def parse_banggianongsan_html(
    html_text: str, default_date: date | None = None
) -> tuple[Decimal, date]:
    """default_date is an expected date, NEVER a fallback for absent evidence."""
    if len(html_text.encode("utf-8")) > MAX_HTML_BYTES:
        raise PriceRejected("SOURCE_CHANGED", "Trang vượt giới hạn 2 MiB.")
    if any(
        marker in html_text.lower()
        for marker in (
            "<title>one moment",
            "<title>just a moment",
            "cf-chl-",
            "g-recaptcha",
        )
    ):
        raise PriceRejected("BLOCKED", "Nguồn yêu cầu xác minh truy cập; chưa lấy được bảng giá.")
    page = Page()
    try:
        page.feed(html_text)
        page.close()
    except MarketError:
        raise
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise MarketError("SOURCE_CHANGED", "HTML bảng nguồn không đúng cấu trúc.") from None
    candidates, dom_prices = [], []
    for script in page.scripts:
        try:
            data = json.loads(script, parse_float=Decimal)
        except (ValueError, RecursionError):
            continue
        for dataset in nodes(data):
            if (
                dataset.get("@type") != "Dataset"
                or dataset.get("@id") != BANGGIANONGSAN_URL + "#dataset"
            ):
                continue
            measures = dataset.get("variableMeasured", [])
            if not isinstance(measures, list):
                raise PriceRejected("SOURCE_CHANGED", "Cấu trúc bảng giá nguồn đã thay đổi.")
            for item in measures:
                if not isinstance(item, dict) or normalize(str(item.get("name", ""))) != LABEL:
                    continue
                if item.get("unitText") != "VND":
                    raise PriceRejected(
                        "WRONG_UNIT", "Giá Gia Lai không có đơn vị VND/kg đã xác minh."
                    )
                candidates.append(
                    (price(item.get("value")), source_day(dataset.get("dateModified")))
                )
    for table in page.tables:
        header = next((row for row in table if "giá mới" in row and "giá cũ" in row), None)
        if header is None:
            continue
        index = header.index("giá mới")
        for row in table:
            if row and row[0] == LABEL:
                if len(row) != len(header):
                    raise PriceRejected("SOURCE_CHANGED", "Số cột giá nguồn không khớp tiêu đề.")
                dom_prices.append(price(row[index], displayed=True))
    if len(set(dom_prices)) > 1 or len(set(candidates)) > 1:
        raise PriceRejected(
            "CONFLICTING_SOURCE", "Nguồn có nhiều giá/ngày Gia Lai không thống nhất."
        )
    if candidates:
        result = candidates[0]
        if dom_prices and dom_prices[0] != result[0]:
            raise PriceRejected(
                "CONFLICTING_SOURCE",
                "Giá mới trên bảng khác dữ liệu cấu trúc của nguồn.",
            )
    elif dom_prices:
        dates = {source_day(value) for value in page.dates}
        if len(dates) != 1:
            raise PriceRejected(
                "MISSING_SOURCE_DATE", "Không xác định được ngày cập nhật bảng giá."
            )
        result = dom_prices[0], dates.pop()
    else:
        raise PriceRejected(
            "SOURCE_CHANGED",
            "Không tìm thấy bảng giá cà phê Gia Lai đúng cấu trúc đã kiểm định.",
        )
    if default_date is not None and result[1] != default_date:
        raise PriceRejected(
            "STALE_SOURCE" if result[1] < default_date else "FUTURE_SOURCE",
            "Nguồn chưa có giá đúng ngày yêu cầu.",
        )
    return result

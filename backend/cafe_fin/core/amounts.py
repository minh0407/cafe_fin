"""Exact core amounts: cents of VND and thousandths of kg; JSON uses strings."""

import re
from decimal import Decimal, InvalidOperation, localcontext

from .errors import CoreError

INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1
_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


def checked_int64(value: int) -> int:
    if type(value) is not int or not INT64_MIN <= value <= INT64_MAX:
        raise CoreError("AMOUNT_OVERFLOW", "Giá trị vượt giới hạn lưu trữ.")
    return value


def _parse(value: str, scale: int) -> int:
    if not isinstance(value, str) or len(value) > 64 or not _DECIMAL.fullmatch(value):
        raise CoreError("INVALID_DECIMAL", "Nhập số thập phân dạng chuỗi hợp lệ.")
    try:
        with localcontext() as ctx:
            ctx.prec = 80
            number = Decimal(value)
            scaled = number * (10**scale)
            if scaled != scaled.to_integral_value():
                raise CoreError("EXCESS_PRECISION", f"Chỉ hỗ trợ tối đa {scale} chữ số lẻ.")
            return checked_int64(int(scaled))
    except InvalidOperation:
        raise CoreError("INVALID_DECIMAL", "Số thập phân không hợp lệ.") from None


def parse_money(value: str) -> int:
    return _parse(value, 2)


def parse_kg(value: str) -> int:
    return _parse(value, 3)


def _string(value: int, scale: int) -> str:
    checked_int64(value)
    sign = "-" if value < 0 else ""
    whole, remainder = divmod(abs(value), 10**scale)
    return f"{sign}{whole}.{remainder:0{scale}d}"


def money_string(value: int) -> str:
    return _string(value, 2)


def kg_string(value: int) -> str:
    return _string(value, 3)


def exact_total(values) -> str:
    """Accumulate beyond int64 in Python; never SQLite SUM(integer) or binary float."""
    total = 0
    for value in values:
        total += checked_int64(value)
    sign = "-" if total < 0 else ""
    whole, part = divmod(abs(total), 100)
    return f"{sign}{whole}.{part:02d}"

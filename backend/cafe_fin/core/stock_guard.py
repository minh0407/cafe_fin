"""Shared chronological guard; records owns ledger persistence and scope selection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import TypeVar

from sqlalchemy.engine import Connection

from .amounts import checked_int64, kg_string
from .errors import CoreError

T = TypeVar("T")


@dataclass(frozen=True)
class StockPoint:
    id: str
    occurred_on: date
    order_key: str
    delta_scaled: int

    @property
    def order(self) -> tuple[date, str, str]:
        return self.occurred_on, self.order_key, self.id


@dataclass(frozen=True)
class StockScope:
    key: str
    points: Iterable[StockPoint]
    opening_scaled: int = 0


def assert_nonnegative(
    points: Iterable[StockPoint], *, opening_scaled: int = 0, scope: str = ""
) -> int:
    """Consume ordered rows without accumulating them; return checked closing balance.

    order_key is allocated once by records and survives edits. Business-day change only
    changes the date component. Every affected old/new product+warehouse scope must be
    reloaded in the same writer transaction after create/edit/delete/restore.
    """
    balance = checked_int64(opening_scaled)
    if balance < 0:
        raise CoreError(
            "STOCK_NEGATIVE",
            "Số dư đầu kỳ không được âm.",
            status=409,
            details={"scope": scope, "balance_kg": kg_string(balance)},
        )
    previous: tuple[date, str, str] | None = None
    for point in points:
        if previous is not None and point.order <= previous:
            raise CoreError(
                "STOCK_ORDER_INVALID",
                "Ledger phải có thứ tự ngày và khóa ổn định duy nhất.",
                status=409,
            )
        previous = point.order
        balance = checked_int64(balance + checked_int64(point.delta_scaled))
        if balance < 0:
            raise CoreError(
                "STOCK_NEGATIVE",
                "Thay đổi làm tồn kho âm tại phiếu liên quan.",
                status=409,
                details={
                    "scope": scope,
                    "related_entry_id": point.id,
                    "occurred_on": point.occurred_on.isoformat(),
                    "balance_kg": kg_string(balance),
                },
            )
    return balance


def guard_stock_mutation(
    conn: Connection,
    mutation: Callable[[Connection], T],
    affected_scopes: Callable[[Connection], Iterable[StockScope]],
) -> T:
    """Execute inside writer transaction; errors roll back mutation and its audit together.

    Caller captures old+new scope keys before mutation. This helper does not create a
    transaction, commit, or turn stock validation into an approval workflow.
    """
    result = mutation(conn)
    for stock_scope in affected_scopes(conn):
        assert_nonnegative(
            stock_scope.points, opening_scaled=stock_scope.opening_scaled, scope=stock_scope.key
        )
    return result

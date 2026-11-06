"""Permission-scoped concrete read provider; no private ORM needed by consumers."""

import json
from collections import defaultdict
from datetime import date, datetime

from cafe_fin.core.contracts import (
    InventoryLineDTO,
    InventorySummaryDTO,
    PartyDTO,
    ReceivableLineDTO,
    ReceivableSummaryDTO,
    WeighingDTO,
)
from cafe_fin.core.errors import CoreError

from .migrations import MOVEMENTS as M
from .responses import InventoryBreakdownDTO, InventoryMovementKindDTO
from .service import (
    RecordsService,
    current_query,
    cutoff_text,
    decimal_total,
    effective_movements,
    get_record,
)


class RecordsReadProvider:
    """Bind one authenticated principal; core rechecks permission on every read.

    lookup_party/get_weighing intentionally include inactive source records for
    reading saved references. They never mutate a contract or the source record.
    """

    def __init__(self, runtime, principal):
        self.runtime, self.principal = runtime, principal
        self.service = RecordsService(runtime)

    def lookup_party(self, identity: str) -> PartyDTO | None:
        with self.runtime.reader() as conn:
            conn.exec_driver_sql("BEGIN")
            self.service._authorize(conn, self.principal)
            try:
                data, _ = get_record(conn, "parties", identity)
            except CoreError as exc:
                if exc.code == "NOT_FOUND":
                    return None
                raise
            # records.read permits entered contract information for both roles;
            # authentication/account administration fields are never part of this DTO.
            return PartyDTO.model_validate_json(
                json.dumps(
                    {
                        key: data[key]
                        for key in (
                            "id",
                            "version",
                            "type",
                            "roles",
                            "name",
                            "tax_code",
                            "address",
                            "contacts",
                            "bank_details",
                            "representative",
                        )
                    }
                )
            )

    def get_weighing(self, identity: str) -> WeighingDTO | None:
        with self.runtime.reader() as conn:
            conn.exec_driver_sql("BEGIN")
            self.service._authorize(conn, self.principal)
            try:
                data, _ = get_record(conn, "weighings", identity)
            except CoreError as exc:
                if exc.code == "NOT_FOUND":
                    return None
                raise
            return WeighingDTO.model_validate_json(
                json.dumps(
                    {
                        key: data[key]
                        for key in ("id", "version", "code", "occurred_on", "party_id", "lines")
                    }
                )
            )

    def inventory_summary(
        self, from_on: date, through_on: date, *, cutoff: datetime
    ) -> InventorySummaryDTO:
        return self._inventory(from_on, through_on, cutoff=cutoff)[0]

    def inventory_breakdown(
        self, from_on: date, through_on: date, *, cutoff: datetime
    ) -> InventoryBreakdownDTO:
        """Additive HTTP/public extension pending root's typed shared DTO addition."""
        summary, breakdown = self._inventory(from_on, through_on, cutoff=cutoff)
        return InventoryBreakdownDTO(
            **summary.model_dump(),
            breakdown=tuple(InventoryMovementKindDTO(**row) for row in breakdown),
        )

    def _inventory(self, from_on, through_on, *, cutoff):
        if type(from_on) is not date or type(through_on) is not date or from_on > through_on:
            raise CoreError("INVALID_RANGE", "Khoảng ngày báo cáo không hợp lệ.", 422)
        cutoff_text(cutoff)
        values, breakdown = defaultdict(lambda: [0, 0, 0]), defaultdict(lambda: [0, 0])
        with self.runtime.reader() as conn:
            conn.exec_driver_sql("BEGIN")
            self.service._authorize(conn, self.principal)
            query = effective_movements(cutoff=cutoff).where(
                M.c.occurred_on <= through_on.isoformat()
            )
            for row in conn.execute(query).mappings():
                key = row.product_id, row.warehouse_id
                delta = row.delta_scaled
                if row.occurred_on < from_on.isoformat():
                    values[key][0] += delta
                else:
                    values[key][1 if delta > 0 else 2] += abs(delta)
                    breakdown[key + (row.entry_type,)][0 if delta > 0 else 1] += abs(delta)
            items = tuple(
                InventoryLineDTO(
                    product_id=p,
                    warehouse_id=w,
                    opening_kg=decimal_total(v[0], 3),
                    received_kg=decimal_total(v[1], 3),
                    issued_kg=decimal_total(v[2], 3),
                    closing_kg=decimal_total(v[0] + v[1] - v[2], 3),
                )
                for (p, w), v in sorted(values.items())
            )
            result = InventorySummaryDTO(
                from_on=from_on,
                through_on=through_on,
                cutoff=cutoff,
                items=items,
                validation_flags=("entered_records_only",),
            )
            parts = [
                {
                    "product_id": p,
                    "warehouse_id": w,
                    "entry_type": t,
                    "in_kg": decimal_total(v[0], 3),
                    "out_kg": decimal_total(v[1], 3),
                }
                for (p, w, t), v in sorted(breakdown.items())
            ]
            return result, parts

    def receivable_summary(self, as_of: date, *, cutoff: datetime) -> ReceivableSummaryDTO:
        if type(as_of) is not date:
            raise CoreError("INVALID_RANGE", "Ngày công nợ không hợp lệ.", 422)
        cutoff_text(cutoff)
        amounts = defaultdict(int)
        with self.runtime.reader() as conn:
            conn.exec_driver_sql("BEGIN")
            self.service._authorize(conn, self.principal)
            for row in conn.execute(current_query("entries", cutoff=cutoff)).mappings():
                data = json.loads(row.data_json)
                if (
                    data["deleted_at"]
                    or data["status"] != "posted"
                    or data["occurred_on"] > as_of.isoformat()
                ):
                    continue
                if data.get("party_id") and data.get("commercial_amount_vnd") is not None:
                    amounts[data["party_id"]] += row.commercial_scaled
            return ReceivableSummaryDTO(
                as_of=as_of,
                cutoff=cutoff,
                items=tuple(
                    ReceivableLineDTO(party_id=p, amount_vnd=decimal_total(v, 2))
                    for p, v in sorted(amounts.items())
                ),
                validation_flags=("commercial_balances_only", "accounting_not_reconciled"),
            )

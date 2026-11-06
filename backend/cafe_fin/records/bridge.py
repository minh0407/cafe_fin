"""Permission-scoped concrete read provider; no private ORM needed by consumers."""

import json
import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime
from weakref import ref

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import case, event, func, select
from sqlalchemy.engine import Connection

from cafe_fin.core.contracts import (
    InventoryLineDTO,
    InventoryMovementSummaryDTO,
    InventorySummaryDTO,
    PartyDTO,
    ReceivableLineDTO,
    ReceivableSummaryDTO,
    SummaryDisplayName,
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

# Classification is explicit source semantics, never inferred from a delta's sign.
_MOVEMENT_COMPONENTS = {
    ("receipt", "in"): "purchased_kg",
    ("issue", "out"): "sold_kg",
    ("production", "out"): "production_input_kg",
    ("production", "in"): "production_output_kg",
    ("transfer", "in"): "transfer_in_kg",
    ("transfer", "out"): "transfer_out_kg",
    ("adjustment", "in"): "adjustment_in_kg",
    ("adjustment", "out"): "adjustment_out_kg",
    # An explicitly entered opening is a stock adjustment, never a new purchase.
    ("opening", "in"): "adjustment_in_kg",
}
_COMPONENT_FIELDS = (
    "purchased_kg",
    "sold_kg",
    "production_input_kg",
    "production_output_kg",
    "transfer_in_kg",
    "transfer_out_kg",
    "adjustment_in_kg",
    "adjustment_out_kg",
)

# SQLite permits comments, BOM and empty statements before a control statement.
# This is a conservative control detector, not an SQL execution/parser facility.
_SQL_PREFIX = re.compile(r"(?:\s+|\ufeff|;+|--[^\n]*(?:\n|$)|/\*.*?\*/)*", re.S)
_SQL_WORD = re.compile(r"[A-Za-z]+")
_QUERY_ONLY_NAME = re.compile(r"\bquery_only\b", re.I)
_EPOCH_KEY = "cafe_fin.records.borrowed_snapshot_epoch"
_DISPLAY_NAME = TypeAdapter(SummaryDisplayName)


def _inventory_labels(conn: Connection, scopes, *, cutoff: datetime):
    """Read only entity names in bounded batches, preserving every numeric scope.

    No active/deleted filter and no join into the ledger: missing/old masters
    cannot remove movements. Master revisions follow the same cutoff and SQLite
    transaction as the quantities. Notes, contacts and party data are not read.
    """
    identities = sorted({identity for scope in scopes for identity in scope})
    labels = {}
    masters = current_query(cutoff=cutoff).subquery("records_summary_masters")
    valid_json = func.json_valid(masters.c.data_json)
    name = case((valid_json, func.json_extract(masters.c.data_json, "$.name")), else_=None)
    name_type = case((valid_json, func.json_type(masters.c.data_json, "$.name")), else_=None)
    for start in range(0, len(identities), 500):
        query = select(
            masters.c.id, masters.c.kind, name.label("name"), name_type.label("name_type")
        ).where(
            masters.c.id.in_(identities[start : start + 500]),
            masters.c.kind.in_(("products", "warehouses")),
        )
        for row in conn.execute(query).mappings():
            label = None
            if row.name_type == "text":
                try:
                    label = _DISPLAY_NAME.validate_python(row.name)
                except ValidationError:
                    pass  # Legacy-invalid display metadata must not fail quantities.
            labels[(row.kind, row.id)] = label
    return labels


class _SnapshotEpoch:
    def __init__(self, conn: Connection):
        # Connection.info can follow a pooled DBAPI connection; never reuse its
        # observer for a different SQLAlchemy Connection wrapper.
        self.owner = ref(conn)
        self.value = 0

    def before_cursor_execute(self, conn, cursor, statement, parameters, context, executemany):
        prefix = _SQL_PREFIX.match(statement)
        word = _SQL_WORD.match(statement, prefix.end())
        keyword = word.group().upper() if word else ""
        if keyword in {"BEGIN", "COMMIT", "END", "ROLLBACK", "SAVEPOINT", "RELEASE"}:
            self.value += 1
        elif keyword == "PRAGMA":
            tail = statement[word.end() :]
            # No bound read may survive a temporary write-enabled connection.
            # Treat setting attempts conservatively, even if SQLite rejects them.
            if "=" in tail or (_QUERY_ONLY_NAME.search(tail) and "(" in tail):
                self.value += 1

    def end_transaction(self, conn):
        self.value += 1


def _snapshot_epoch(conn: Connection) -> _SnapshotEpoch:
    state = conn.info.get(_EPOCH_KEY)
    if not isinstance(state, _SnapshotEpoch) or state.owner() is not conn:
        state = _SnapshotEpoch(conn)
        event.listen(conn, "before_cursor_execute", state.before_cursor_execute)
        event.listen(conn, "commit", state.end_transaction)
        event.listen(conn, "rollback", state.end_transaction)
        conn.info[_EPOCH_KEY] = state
    return state


class RecordsReadProvider:
    """Bind one authenticated principal; core rechecks permission on every read.

    lookup_party/get_weighing intentionally include inactive source records for
    reading saved references. They never mutate a contract or the source record.
    """

    def __init__(self, runtime, principal, *, connection: Connection | None = None):
        self.runtime, self.principal = runtime, principal
        self.service = RecordsService(runtime)
        self.connection = connection
        self._transaction = connection.get_transaction() if connection is not None else None
        self._epoch = (
            _snapshot_epoch(connection)
            if connection is not None and not connection.closed and not connection.invalidated
            else None
        )
        self._epoch_value = self._epoch.value if self._epoch is not None else None

    @staticmethod
    def _require_snapshot(conn: Connection) -> None:
        if (
            conn.closed
            or conn.invalidated
            or not conn.in_transaction()
            or not conn.connection.driver_connection.in_transaction
            or conn.exec_driver_sql("PRAGMA query_only").scalar_one() != 1
        ):
            raise CoreError(
                "READ_ONLY_SNAPSHOT_REQUIRED",
                "Cần connection chỉ đọc đang giữ SQLite BEGIN snapshot do caller quản lý.",
                409,
            )

    def bind_connection(self, conn: Connection) -> "RecordsReadProvider":
        """Borrow caller's explicit read-only transaction without opening/closing it.

        Source.capture may bind records/accounting to the same connection. The
        caller owns BEGIN and lifetime; ending it invalidates subsequent reads.
        """
        self._require_snapshot(conn)
        self.service._authorize(conn, self.principal)
        return RecordsReadProvider(self.runtime, self.principal, connection=conn)

    @contextmanager
    def _read(self):
        if self.connection is not None:
            self._require_snapshot(self.connection)
            if (
                self.connection.get_transaction() is not self._transaction
                or self._epoch is None
                or self._epoch.value != self._epoch_value
            ):
                raise CoreError(
                    "READ_ONLY_SNAPSHOT_REQUIRED",
                    "Snapshot đã kết thúc; cần bind reader mới cho transaction mới.",
                    409,
                )
            self.service._authorize(self.connection, self.principal)
            yield self.connection
        else:
            with self.runtime.reader() as conn:
                conn.exec_driver_sql("BEGIN")
                self.service._authorize(conn, self.principal)
                yield conn

    def lookup_party(self, identity: str) -> PartyDTO | None:
        with self._read() as conn:
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
        with self._read() as conn:
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
        """Core summary plus retained local entry-type detail for desktop clients."""
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
        components = defaultdict(lambda: dict.fromkeys(_COMPONENT_FIELDS, 0))
        unknown = False
        period_opening = False
        with self._read() as conn:
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
                    component = _MOVEMENT_COMPONENTS.get((row.entry_type, row.direction))
                    direction_valid = (row.direction == "in" and delta > 0) or (
                        row.direction == "out" and delta < 0
                    )
                    if component is None or not direction_valid:
                        unknown = True
                    else:
                        components[key][component] += abs(delta)
                        period_opening |= row.entry_type == "opening"
            labels = _inventory_labels(conn, values, cutoff=cutoff)
            items = tuple(
                InventoryLineDTO(
                    product_id=p,
                    warehouse_id=w,
                    product_name=labels.get(("products", p)),
                    warehouse_name=labels.get(("warehouses", w)),
                    opening_kg=decimal_total(v[0], 3),
                    received_kg=decimal_total(v[1], 3),
                    issued_kg=decimal_total(v[2], 3),
                    closing_kg=decimal_total(v[0] + v[1] - v[2], 3),
                )
                for (p, w), v in sorted(values.items())
            )
            flags = ["entered_records_only"]
            if period_opening:
                flags.append("opening_entries_in_adjustments")
            if unknown:
                flags.append("inventory_movement_classification_unknown")
            movement_breakdown = (
                None
                if unknown
                else tuple(
                    InventoryMovementSummaryDTO(
                        product_id=p,
                        warehouse_id=w,
                        product_name=labels.get(("products", p)),
                        warehouse_name=labels.get(("warehouses", w)),
                        **{
                            field: decimal_total(value, 3)
                            for field, value in components[(p, w)].items()
                        },
                    )
                    for p, w in sorted(values)
                )
            )
            result = InventorySummaryDTO(
                from_on=from_on,
                through_on=through_on,
                cutoff=cutoff,
                items=items,
                validation_flags=tuple(flags),
                breakdown_version=None if unknown else 1,
                movement_breakdown=movement_breakdown,
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
        with self._read() as conn:
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

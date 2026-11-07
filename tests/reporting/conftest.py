import copy
from types import SimpleNamespace

import pytest
from cafe_fin.core.contracts import (
    BookSummaryDTO,
    InventoryLineDTO,
    InventoryMovementSummaryDTO,
    InventorySummaryDTO,
    MappedBookMetricDTO,
)
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting import models
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.sources import SourceBundle


class SyntheticSource:
    amount = "123456789012345678901234567890.01"
    closing = "9.999"
    calls = 0
    malicious = "SECRET-sentinel CCCD 012345678901 bank 99999 localhost C:/private token"

    def capture(self, first, last, book_ids, cutoff):
        self.calls += 1
        inventory = InventorySummaryDTO(
            from_on=first,
            through_on=last,
            cutoff=cutoff,
            items=(
                InventoryLineDTO(
                    product_id=self.malicious,
                    warehouse_id="kho-demo",
                    opening_kg="0.000",
                    received_kg="10.001",
                    issued_kg="0.002",
                    closing_kg=self.closing,
                ),
            ),
            validation_flags=(self.malicious,),
        )
        books = tuple(
            BookSummaryDTO(
                book_id=identity,
                from_on=first,
                through_on=last,
                cutoff=cutoff,
                has_valid_money_mapping=identity != "missing",
                metrics=()
                if identity == "missing"
                else (
                    MappedBookMetricDTO(key="income", amount_vnd=self.amount, mapping_revision=2),
                    MappedBookMetricDTO(key="invoice", amount_vnd="999999.99", mapping_revision=2),
                ),
            )
            for identity in book_ids
        )
        return SourceBundle(inventory, books, consistency="atomic_read_snapshot")


class TypedSyntheticSource(SyntheticSource):
    """Actual frozen v2 DTOs, separate from the v1-style unknown-meaning fixture."""

    def capture(self, first, last, book_ids, cutoff):
        self.calls += 1
        totals = (
            InventoryLineDTO(
                product_id="raw",
                warehouse_id="A",
                opening_kg="0.000",
                received_kg="11.000",
                issued_kg="7.000",
                closing_kg="4.000",
            ),
            InventoryLineDTO(
                product_id="raw",
                warehouse_id="B",
                opening_kg="0.000",
                received_kg="2.000",
                issued_kg="1.000",
                closing_kg="1.000",
            ),
            InventoryLineDTO(
                product_id="processed",
                warehouse_id="A",
                opening_kg="0.000",
                received_kg="3.000",
                issued_kg="1.000",
                closing_kg="2.000",
            ),
        )
        # Every category explicitly supplied, including confirmed zeros.
        breakdown = (
            InventoryMovementSummaryDTO(
                product_id="raw",
                warehouse_id="A",
                purchased_kg="10.000",
                sold_kg="1.000",
                production_input_kg="4.000",
                production_output_kg="0.000",
                transfer_in_kg="0.000",
                transfer_out_kg="2.000",
                adjustment_in_kg="1.000",
                adjustment_out_kg="0.000",
            ),
            InventoryMovementSummaryDTO(
                product_id="raw",
                warehouse_id="B",
                purchased_kg="0.000",
                sold_kg="0.000",
                production_input_kg="0.000",
                production_output_kg="0.000",
                transfer_in_kg="2.000",
                transfer_out_kg="0.000",
                adjustment_in_kg="0.000",
                adjustment_out_kg="1.000",
            ),
            InventoryMovementSummaryDTO(
                product_id="processed",
                warehouse_id="A",
                purchased_kg="0.000",
                sold_kg="1.000",
                production_input_kg="0.000",
                production_output_kg="3.000",
                transfer_in_kg="0.000",
                transfer_out_kg="0.000",
                adjustment_in_kg="0.000",
                adjustment_out_kg="0.000",
            ),
        )
        inventory = InventorySummaryDTO(
            from_on=first,
            through_on=last,
            cutoff=cutoff,
            items=totals,
            breakdown_version=1,
            movement_breakdown=breakdown,
            validation_flags=(self.malicious,),
        )
        books = []
        for identity in book_ids:
            metrics = (
                ()
                if identity == "missing"
                else (
                    MappedBookMetricDTO(
                        key="column-A",
                        meaning="cash_receipts",
                        amount_vnd=self.amount,
                        mapping_revision=2,
                    ),
                    MappedBookMetricDTO(
                        key="column-B",
                        meaning="cash_payments",
                        amount_vnd="200.02",
                        mapping_revision=2,
                    ),
                    MappedBookMetricDTO(
                        key="column-C",
                        meaning="cash_receipt_deposits",
                        amount_vnd="100.00",
                        mapping_revision=2,
                    ),
                    MappedBookMetricDTO(
                        key="column-D",
                        meaning="cash_payment_deposits",
                        amount_vnd="20.00",
                        mapping_revision=2,
                    ),
                    MappedBookMetricDTO(
                        key="column-E",
                        meaning="noncash_offsets",
                        amount_vnd="50.03",
                        mapping_revision=2,
                    ),
                    MappedBookMetricDTO(
                        key="invoice", meaning="other", amount_vnd="999999.99", mapping_revision=2
                    ),
                    MappedBookMetricDTO(
                        key="income", meaning=None, amount_vnd="9876543210.01", mapping_revision=2
                    ),
                )
            )
            books.append(
                BookSummaryDTO(
                    book_id=identity,
                    from_on=first,
                    through_on=last,
                    cutoff=cutoff,
                    has_valid_money_mapping=identity != "missing",
                    metrics=metrics,
                )
            )
        return SourceBundle(inventory, tuple(books), consistency="atomic_read_snapshot")


class MemorySecrets:
    """Synthetic tests only; never a production default or on-disk plaintext adapter."""

    available = True

    def __init__(self):
        self.values = {}

    def has(self, key):
        return key in self.values

    def get(self, key):
        return copy.deepcopy(self.values.get(key))

    def put(self, key, value):
        self.values[key] = copy.deepcopy(value)


BOT_ID = "123456"
CHAT_ID = "-1001234567890"
BOT_TOKEN = BOT_ID + ":" + "A" * 35


class FakeTransport:
    def __init__(self):
        from cafe_fin.reporting.telegram import MessageReceipt

        self.texts, self.files, self.verifications = [], [], []
        self.verify_error = self.send_error = self.file_error = None
        self.receipt = MessageReceipt(CHAT_ID, 101)
        self.file_receipt = MessageReceipt(CHAT_ID, 102)
        self.allowed_bot_id, self.allowed_chat_id = BOT_ID, CHAT_ID

    def verify(self, token, chat_id, bot_id, *, documents=False):
        from cafe_fin.reporting.telegram import DeliveryError

        self.verifications.append((chat_id, bot_id, documents))
        if self.verify_error:
            raise self.verify_error
        if bot_id != self.allowed_bot_id:
            raise DeliveryError("TELEGRAM_BOT_MISMATCH")
        if chat_id != self.allowed_chat_id:
            raise DeliveryError("TELEGRAM_CHAT_INVALID")
        return bot_id

    def send_text(self, token, chat_id, text, bot_id):
        self.texts.append(text)
        if self.send_error:
            raise self.send_error
        return self.receipt

    def send_document(self, token, chat_id, content, filename, bot_id):
        self.files.append((content, filename))
        if self.file_error:
            raise self.file_error
        return self.file_receipt


def preview_command(key="preview", reason="", first="2026-10-31", last="2026-11-01"):
    return models.Preview(
        request_key=key, from_on=first, through_on=last, book_ids=["cash", "missing"], reason=reason
    )


def saved(env, key="preview", reason="", first="2026-10-31", last="2026-11-01"):
    row = env.service.preview(env.actor, preview_command(key, reason, first, last))
    return env.service.save(
        env.actor,
        row["id"],
        models.Save(request_key="save-" + key, expected_version=row["version"]),
    )


def configure(env, *, enabled=True, attachments=False):
    from cafe_fin.reporting.sender import check_connection

    config = env.service.settings()
    env.service.update_settings(
        env.actor,
        models.DeliverySettings(
            request_key="config-" + str(config["version"]),
            expected_version=config["version"],
            chat_id=CHAT_ID,
            enabled=enabled,
            send_at="18:00",
            attachments_enabled=attachments,
        ),
    )
    env.service.set_credentials(env.actor, models.Credentials(bot_token=BOT_TOKEN))
    assert check_connection(env.service, env.actor)["state"] == "CONNECTED"
    env.transport.verifications.clear()


@pytest.fixture
def env(tmp_path):
    source, secrets, transport = SyntheticSource(), MemorySecrets(), FakeTransport()
    registry = ModuleRegistry(
        (module_manifest(source=source, secret_store=secrets, transport=transport),)
    )
    runtime = Runtime(tmp_path / "Cà phê tổng hợp", initialize=True, modules=registry)
    auth = runtime.auth.setup("reportadmin", "synthetic-report-password")
    actor = runtime.auth.authenticate(auth["access_token"])
    service = ReportingService(runtime, source=source, secret_store=secrets, transport=transport)
    yield SimpleNamespace(
        runtime=runtime,
        service=service,
        source=source,
        secrets=secrets,
        transport=transport,
        actor=actor,
        registry=registry,
        auth=auth,
        root=runtime.root.path,
    )
    runtime.close()

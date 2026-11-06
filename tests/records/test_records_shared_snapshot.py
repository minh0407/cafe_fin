"""Public records bridge can borrow one caller-owned SQLite snapshot across sources.

The other source below is a synthetic SQL probe, not the accounting implementation.
"""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from cafe_fin.core.db import Database, WriteCoordinator
from cafe_fin.core.errors import CoreError
from sqlalchemy import event

DAY = date(2026, 11, 1)
CUTOFF = datetime(2030, 1, 1, tzinfo=timezone.utc)


def prepare(api):
    masters = api.masters()
    weighing = api.create("weighings", {
        "code": "CAN-SNAPSHOT", "occurred_on": DAY.isoformat(),
        "party_id": masters["party"]["id"],
        "lines": [{"quantity_source": "direct_net", "net_kg": "10.001"}],
    })
    payload = api.entry_data(masters, "10.001") | {"commercial_amount_vnd": "100.01"}
    entry = api.create("entries", payload)
    return masters, weighing, payload, entry


def reads(provider, masters, weighing):
    return (
        lambda: provider.lookup_party(masters["party"]["id"]),
        lambda: provider.get_weighing(weighing["id"]),
        lambda: provider.inventory_summary(DAY, DAY, cutoff=CUTOFF),
        lambda: provider.receivable_summary(DAY, cutoff=CUTOFF),
        lambda: provider.inventory_breakdown(DAY, DAY, cutoff=CUTOFF),
    )


def assert_owned_transaction(conn):
    assert not conn.closed
    assert conn.in_transaction()
    assert conn.connection.driver_connection.in_transaction
    assert conn.exec_driver_sql("SELECT 1").scalar_one() == 1


def test_bound_records_and_other_source_probe_share_one_snapshot_during_writer_commit(records_api):
    from cafe_fin.records.module import RecordsReadProvider
    from cafe_fin.records.service import RecordsService

    api = records_api
    masters, weighing, payload, entry = prepare(api)

    def create_probe(conn):
        conn.exec_driver_sql("CREATE TABLE test_shared_snapshot_probe(id INTEGER PRIMARY KEY, marker INTEGER NOT NULL)")
        conn.exec_driver_sql("INSERT INTO test_shared_snapshot_probe VALUES (1,0)")

    api.runtime.writer.run(create_probe)
    database2 = Database(api.runtime.database.path, create=False)
    writer2 = WriteCoordinator(database2)
    runtime2 = SimpleNamespace(database=database2, reader=database2.read, writer=writer2, auth=api.runtime.auth)
    probe_connections = []

    def update_other_source_on_same_commit(conn):
        # A trusted synthetic second source adds its update before the actual DBAPI
        # commit, so the new records revision and marker become visible atomically.
        assert conn.connection.driver_connection.in_transaction
        probe_connections.append(id(conn.connection.driver_connection))
        conn.exec_driver_sql("UPDATE test_shared_snapshot_probe SET marker=1 WHERE id=1")

    event.listen(database2.engine, "commit", update_other_source_on_same_commit)
    try:
        with api.runtime.reader() as conn:
            conn.exec_driver_sql("BEGIN")
            provider = RecordsReadProvider(api.runtime, api.principal)
            bound = provider.bind_connection(conn)
            old_physical_connection = id(conn.connection.driver_connection)
            assert bound.inventory_summary(DAY, DAY, cutoff=CUTOFF).items[0].closing_kg == "10.001"
            assert conn.exec_driver_sql("SELECT marker FROM test_shared_snapshot_probe WHERE id=1").scalar_one() == 0
            updated = RecordsService(runtime2).save(
                "entries", payload | {
                    "lines": [api.line(masters, "15.001")], "commercial_amount_vnd": "150.01",
                }, actor=api.principal, request_key="shared-snapshot-update",
                identity=entry["id"], expected_version=entry["version"],
            )
            assert updated["version"] == entry["version"] + 1
            assert len(probe_connections) == 1
            assert probe_connections[0] != old_physical_connection
            # Both sources still read the same old SQLite snapshot even though
            # cutoff permits the new revision and the second writer has committed.
            assert bound.inventory_summary(DAY, DAY, cutoff=CUTOFF).items[0].closing_kg == "10.001"
            assert bound.receivable_summary(DAY, cutoff=CUTOFF).items[0].amount_vnd == "100.01"
            assert bound.get_weighing(weighing["id"]).lines[0].net_kg == "10.001"
            assert conn.exec_driver_sql("SELECT marker FROM test_shared_snapshot_probe WHERE id=1").scalar_one() == 0
            assert_owned_transaction(conn)
            # A fresh provider owns a new read transaction and sees the new pair.
            assert provider.inventory_summary(DAY, DAY, cutoff=CUTOFF).items[0].closing_kg == "15.001"
            assert provider.receivable_summary(DAY, cutoff=CUTOFF).items[0].amount_vnd == "150.01"
            with api.runtime.reader() as fresh:
                fresh.exec_driver_sql("BEGIN")
                assert fresh.exec_driver_sql("SELECT marker FROM test_shared_snapshot_probe WHERE id=1").scalar_one() == 1
    finally:
        event.remove(database2.engine, "commit", update_other_source_on_same_commit)
        writer2.close()
        database2.close()


@pytest.mark.parametrize("binding", ["bind_connection", "connection_keyword"])
def test_all_public_reads_use_only_the_borrowed_connection_and_revalidate_each_time(records_api, monkeypatch, binding):
    from cafe_fin.records.module import RecordsReadProvider

    api = records_api
    masters, weighing, _, _ = prepare(api)
    authorized_connections = []
    authorize = api.runtime.auth.authorize

    def checked_authorize(conn, actor, permission):
        authorized_connections.append((conn, actor.id, permission))
        return authorize(conn, actor, permission)

    def unexpected_reader():
        pytest.fail("connection-bound provider opened runtime.reader()")

    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        monkeypatch.setattr(api.runtime.auth, "authorize", checked_authorize)
        if binding == "bind_connection":
            provider = RecordsReadProvider(api.runtime, api.principal).bind_connection(conn)
            assert len(authorized_connections) == 1
            authorized_connections.clear()
        else:
            provider = RecordsReadProvider(api.runtime, api.principal, connection=conn)
        monkeypatch.setattr(api.runtime, "reader", unexpected_reader)
        results = [read() for read in reads(provider, masters, weighing)]
        assert results[0].id == masters["party"]["id"]
        assert results[1].id == weighing["id"]
        assert results[2].items[0].closing_kg == "10.001"
        assert results[3].items[0].amount_vnd == "100.01"
        assert results[4].breakdown[0].in_kg == "10.001"
        assert len(authorized_connections) == 5
        assert all(c is conn and actor == api.principal.id and permission == "records.read"
                   for c, actor, permission in authorized_connections)
        # Errors and missing references also leave lifetime/transaction with caller.
        with pytest.raises(CoreError, match="INVALID_RANGE"):
            provider.inventory_summary(date(2026, 11, 2), DAY, cutoff=CUTOFF)
        assert provider.lookup_party("00000000-0000-0000-0000-000000000000") is None
        assert_owned_transaction(conn)


def test_write_connection_is_rejected_without_ending_caller_transaction(records_api):
    from cafe_fin.records.module import RecordsReadProvider

    api = records_api
    masters, weighing, _, _ = prepare(api)
    with api.runtime.database.engine.connect() as conn:
        conn.exec_driver_sql("BEGIN")
        assert conn.exec_driver_sql("PRAGMA query_only").scalar_one() == 0
        provider = RecordsReadProvider(api.runtime, api.principal)
        with pytest.raises(CoreError, match="READ_ONLY_SNAPSHOT_REQUIRED"):
            provider.bind_connection(conn)
        direct = RecordsReadProvider(api.runtime, api.principal, connection=conn)
        for read in reads(direct, masters, weighing):
            with pytest.raises(CoreError, match="READ_ONLY_SNAPSHOT_REQUIRED"):
                read()
        assert_owned_transaction(conn)
        assert conn.exec_driver_sql("PRAGMA query_only").scalar_one() == 0


def test_query_only_without_explicit_sqlite_begin_is_rejected(records_api):
    from cafe_fin.records.module import RecordsReadProvider

    api = records_api
    with api.runtime.reader() as conn:
        # PRAGMA creates SQLAlchemy autobegin state without an actual SQLite BEGIN.
        assert conn.in_transaction()
        assert not conn.connection.driver_connection.in_transaction
        with pytest.raises(CoreError, match="READ_ONLY_SNAPSHOT_REQUIRED"):
            RecordsReadProvider(api.runtime, api.principal).bind_connection(conn)
        assert not conn.closed
        assert not conn.connection.driver_connection.in_transaction
        conn.exec_driver_sql("BEGIN")
        bound = RecordsReadProvider(api.runtime, api.principal).bind_connection(conn)
        assert bound.lookup_party("00000000-0000-0000-0000-000000000000") is None
        assert_owned_transaction(conn)


@pytest.mark.parametrize("end", ["commit", "rollback"])
def test_ended_borrowed_transaction_is_rejected_on_every_public_read(records_api, end):
    from cafe_fin.records.module import RecordsReadProvider

    api = records_api
    masters, weighing, _, _ = prepare(api)
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        bound = RecordsReadProvider(api.runtime, api.principal).bind_connection(conn)
        getattr(conn, end)()
        assert not conn.in_transaction()
        for read in reads(bound, masters, weighing):
            with pytest.raises(CoreError, match="READ_ONLY_SNAPSHOT_REQUIRED"):
                read()
        assert not conn.closed
        assert not conn.in_transaction()
        assert not conn.connection.driver_connection.in_transaction


def test_closed_borrowed_connection_is_rejected(records_api):
    from cafe_fin.records.module import RecordsReadProvider

    api = records_api
    masters, weighing, _, _ = prepare(api)
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        bound = RecordsReadProvider(api.runtime, api.principal).bind_connection(conn)
    assert conn.closed
    for read in reads(bound, masters, weighing):
        with pytest.raises(CoreError, match="READ_ONLY_SNAPSHOT_REQUIRED"):
            read()


@pytest.mark.parametrize("end", ["commit", "rollback"])
def test_new_begin_on_same_connection_does_not_revive_a_bound_provider(records_api, end):
    from cafe_fin.records.module import RecordsReadProvider

    api = records_api
    masters, weighing, _, _ = prepare(api)
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        provider = RecordsReadProvider(api.runtime, api.principal)
        bound = provider.bind_connection(conn)
        original_transaction = conn.get_transaction()
        getattr(conn, end)()
        conn.exec_driver_sql("BEGIN")
        assert conn.get_transaction() is not original_transaction
        for read in reads(bound, masters, weighing):
            with pytest.raises(CoreError, match="READ_ONLY_SNAPSHOT_REQUIRED"):
                read()
        assert_owned_transaction(conn)
        rebound = provider.bind_connection(conn)
        assert rebound.lookup_party(masters["party"]["id"]).id == masters["party"]["id"]
        assert rebound.inventory_summary(DAY, DAY, cutoff=CUTOFF).items[0].closing_kg == "10.001"
        assert_owned_transaction(conn)


def test_revoked_principal_cannot_bind_and_errors_preserve_connection_ownership(records_api):
    from cafe_fin.records.module import RecordsReadProvider

    api = records_api
    masters, weighing, _, _ = prepare(api)
    account = api.runtime.auth.create_user(
        api.principal, username="shared-reader", password="synthetic-shared-password",
        role="operator", request_key="shared-reader-account",
    )
    session = api.runtime.auth.login("shared-reader", "synthetic-shared-password")
    captured = api.runtime.auth.authenticate(session["access_token"])
    api.runtime.auth.update_user(
        api.principal, account["id"], role="operator", active=False,
        expected_version=account["version"], request_key="shared-reader-revoked",
    )
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        with pytest.raises(CoreError, match="SESSION_EXPIRED"):
            RecordsReadProvider(api.runtime, captured).bind_connection(conn)
        direct = RecordsReadProvider(api.runtime, captured, connection=conn)
        for read in reads(direct, masters, weighing):
            with pytest.raises(CoreError, match="SESSION_EXPIRED"):
                read()
            assert_owned_transaction(conn)
        # Caller can still reuse that exact transaction for an authorized provider.
        valid = RecordsReadProvider(api.runtime, api.principal).bind_connection(conn)
        assert valid.lookup_party(masters["party"]["id"]).id == masters["party"]["id"]
        assert_owned_transaction(conn)

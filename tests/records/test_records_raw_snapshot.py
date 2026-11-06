"""Public SQLAlchemy raw transaction control must not revive a borrowed snapshot."""

import pytest
from cafe_fin.core.errors import CoreError
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from test_records_shared_snapshot import CUTOFF, DAY, prepare, reads


def execute_sql(conn, statement, execution, parameters=None):
    if execution == "text":
        return conn.execute(text(statement), parameters or {})
    if parameters is None:
        return conn.exec_driver_sql(statement)
    return conn.exec_driver_sql(statement, parameters)


def bind(api, conn, construction):
    from cafe_fin.records.module import RecordsReadProvider

    provider = RecordsReadProvider(api.runtime, api.principal)
    if construction == "keyword":
        return RecordsReadProvider(api.runtime, api.principal, connection=conn)
    return provider.bind_connection(conn)


def assert_rejected_without_taking_ownership(provider, masters, weighing, conn):
    for read in reads(provider, masters, weighing):
        with pytest.raises(CoreError, match="READ_ONLY_SNAPSHOT_REQUIRED"):
            read()
        assert not conn.closed
        assert conn.connection.driver_connection.in_transaction
    assert conn.exec_driver_sql("SELECT 1").scalar_one() == 1


def assert_values(provider, masters, weighing, quantity, money):
    result = [read() for read in reads(provider, masters, weighing)]
    assert result[0].id == masters["party"]["id"]
    assert result[1].id == weighing["id"]
    assert result[2].items[0].closing_kg == quantity
    assert result[2].movement_breakdown[0].purchased_kg == quantity
    assert result[3].items[0].amount_vnd == money
    assert result[4].items[0].closing_kg == quantity
    assert result[4].movement_breakdown[0].purchased_kg == quantity


def change_entry_on_another_connection(api, masters, payload, entry, reader_id):
    writer_ids = []

    def capture_writer(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE RECORDS_DOCUMENTS "):
            writer_ids.append(id(connection.connection.driver_connection))

    event.listen(api.runtime.database.engine, "before_cursor_execute", capture_writer)
    try:
        response = api.replace("entries", entry, payload | {
            "lines": [api.line(masters, "15.003")], "commercial_amount_vnd": "150.03",
        })
        assert response.status_code == 200, response.text
    finally:
        event.remove(api.runtime.database.engine, "before_cursor_execute", capture_writer)
    assert len(writer_ids) == 1 and writer_ids[0] != reader_id


def test_raw_rollback_begin_cannot_revive_bound_snapshot(records_api):
    from cafe_fin.records.module import RecordsReadProvider

    api = records_api
    masters, _, payload, entry = prepare(api)
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        bound = RecordsReadProvider(api.runtime, api.principal).bind_connection(conn)
        original_transaction = conn.get_transaction()
        reader_id = id(conn.connection.driver_connection)
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
        assert bound.inventory_summary(DAY, DAY, cutoff=CUTOFF).items[0].closing_kg == "10.001"
        assert bound.receivable_summary(DAY, cutoff=CUTOFF).items[0].amount_vnd == "100.01"
        conn.exec_driver_sql("ROLLBACK")
        assert conn.get_transaction() is original_transaction
        assert not conn.connection.driver_connection.in_transaction
        writer_ids = []

        def capture_writer(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("UPDATE RECORDS_DOCUMENTS "):
                writer_ids.append(id(connection.connection.driver_connection))

        event.listen(api.runtime.database.engine, "before_cursor_execute", capture_writer)
        try:
            response = api.replace("entries", entry, payload | {
                "lines": [api.line(masters, "15.003")], "commercial_amount_vnd": "150.03",
            })
            assert response.status_code == 200, response.text
        finally:
            event.remove(api.runtime.database.engine, "before_cursor_execute", capture_writer)
        assert len(writer_ids) == 1 and writer_ids[0] != reader_id
        conn.exec_driver_sql("BEGIN")
        assert conn.get_transaction() is original_transaction
        assert conn.connection.driver_connection.in_transaction
        try:
            inventory = bound.inventory_summary(DAY, DAY, cutoff=CUTOFF)
        except CoreError as exc:
            assert exc.code == "READ_ONLY_SNAPSHOT_REQUIRED"
        else:
            money = bound.receivable_summary(DAY, cutoff=CUTOFF)
            pytest.fail(
                "Borrowed provider crossed raw ROLLBACK/BEGIN with unchanged RootTransaction: "
                f"old=10.001kg/100.01VND, observed={inventory.items[0].closing_kg}kg/"
                f"{money.items[0].amount_vnd}VND"
            )


@pytest.mark.parametrize("construction", ["bind_connection", "keyword"])
@pytest.mark.parametrize("execution", ["exec_driver_sql", "text"])
@pytest.mark.parametrize("command", ["COMMIT", "END", "ROLLBACK"])
@pytest.mark.parametrize("decoration", ["plain", "bom_semicolons_comments_case"])
def test_raw_end_and_new_begin_invalidate_all_reads_even_with_same_sqlalchemy_wrapper(
    records_api, construction, execution, command, decoration,
):
    api = records_api
    masters, weighing, payload, entry = prepare(api)
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        bound = bind(api, conn, construction)
        original_transaction = conn.get_transaction()
        reader_id = id(conn.connection.driver_connection)
        assert_values(bound, masters, weighing, "10.001", "100.01")
        statement = command
        if decoration != "plain":
            statement = "\ufeff; /* capture boundary */ -- before control\n ; " + command.title() + ";"
        execute_sql(conn, statement, execution)
        assert conn.get_transaction() is original_transaction
        assert not conn.connection.driver_connection.in_transaction
        change_entry_on_another_connection(api, masters, payload, entry, reader_id)
        execute_sql(conn, "BEGIN", execution)
        assert conn.get_transaction() is original_transaction
        assert_rejected_without_taking_ownership(bound, masters, weighing, conn)
        assert_values(bind(api, conn, construction), masters, weighing, "15.003", "150.03")


@pytest.mark.parametrize("construction", ["bind_connection", "keyword"])
@pytest.mark.parametrize("execution,statement,parameters", [
    ("exec_driver_sql", "SELECT 'ROLLBACK' AS value", None),
    ("text", "/* ROLLBACK; SAVEPOINT */ SELECT 'COMMIT' AS value -- END", None),
    ("exec_driver_sql", "SELECT ? AS value", ("ROLLBACK; BEGIN; COMMIT",)),
    ("text", "SELECT :word AS value", {"word": "ROLLBACK; END; SAVEPOINT"}),
    ("exec_driver_sql", "; ; -- END\n SELECT 'ROLLBACK' AS value", None),
    ("text", "\ufeff/* COMMIT */ SELECT 'END' AS value", None),
])
def test_transaction_words_in_select_content_comments_or_parameters_do_not_invalidate_snapshot(
    records_api, construction, execution, statement, parameters,
):
    api = records_api
    masters, weighing, _, _ = prepare(api)
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        bound = bind(api, conn, construction)
        original_transaction = conn.get_transaction()
        execute_sql(conn, statement, execution, parameters).all()
        assert conn.get_transaction() is original_transaction
        assert_values(bound, masters, weighing, "10.001", "100.01")
        assert not conn.closed and conn.connection.driver_connection.in_transaction


def test_transaction_epoch_invalidation_is_shared_by_all_providers_on_the_connection(records_api):
    api = records_api
    masters, weighing, payload, entry = prepare(api)
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        original_transaction = conn.get_transaction()
        reader_id = id(conn.connection.driver_connection)
        providers = [bind(api, conn, "bind_connection"), bind(api, conn, "keyword"), bind(api, conn, "bind_connection")]
        for bound in providers:
            assert_values(bound, masters, weighing, "10.001", "100.01")
        conn.execute(text("/* shared connection */ END"))
        change_entry_on_another_connection(api, masters, payload, entry, reader_id)
        conn.execute(text("BEGIN"))
        assert conn.get_transaction() is original_transaction
        for bound in providers:
            assert_rejected_without_taking_ownership(bound, masters, weighing, conn)
        assert_values(bind(api, conn, "bind_connection"), masters, weighing, "15.003", "150.03")


@pytest.mark.parametrize("execution", ["exec_driver_sql", "text"])
@pytest.mark.parametrize("statement,fails", [("BEGIN", True), ("SAVEPOINT capture_boundary", False)])
def test_transaction_control_attempt_invalidates_even_when_begin_fails_or_savepoint_keeps_snapshot(
    records_api, execution, statement, fails,
):
    api = records_api
    masters, weighing, _, _ = prepare(api)
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        bound = bind(api, conn, "bind_connection")
        original_transaction = conn.get_transaction()
        if fails:
            with pytest.raises(OperationalError):
                execute_sql(conn, statement, execution)
        else:
            execute_sql(conn, statement, execution)
        assert conn.get_transaction() is original_transaction
        assert_rejected_without_taking_ownership(bound, masters, weighing, conn)
        assert_values(bind(api, conn, "keyword"), masters, weighing, "10.001", "100.01")


@pytest.mark.parametrize("end", ["commit", "rollback"])
def test_nested_transaction_end_invalidates_provider_without_replacing_root_transaction(records_api, end):
    api = records_api
    masters, weighing, _, _ = prepare(api)
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        original_transaction = conn.get_transaction()
        nested = conn.begin_nested()
        bound = bind(api, conn, "keyword")
        assert_values(bound, masters, weighing, "10.001", "100.01")
        getattr(nested, end)()
        assert conn.get_transaction() is original_transaction
        assert_rejected_without_taking_ownership(bound, masters, weighing, conn)
        assert_values(bind(api, conn, "bind_connection"), masters, weighing, "10.001", "100.01")


@pytest.mark.parametrize("execution", ["exec_driver_sql", "text"])
@pytest.mark.parametrize("disable,enable", [
    ("PRAGMA query_only=OFF", "PRAGMA query_only=ON"),
    ('PRAGMA main."query_only" = 0', 'PRAGMA main."query_only" = 1'),
    ("PRAGMA [query_only](OFF)", "PRAGMA [query_only](ON)"),
    ("PRAGMA main.`query_only`(0)", "PRAGMA main.`query_only`(1)"),
])
def test_query_only_off_write_on_invalidates_even_when_current_pragma_and_root_identity_look_safe(
    records_api, execution, disable, enable,
):
    api = records_api
    masters, weighing, _, _ = prepare(api)

    def create_probe(conn):
        conn.exec_driver_sql("CREATE TABLE test_raw_snapshot_probe(marker INTEGER NOT NULL)")
        conn.exec_driver_sql("INSERT INTO test_raw_snapshot_probe VALUES (0)")

    api.runtime.writer.run(create_probe)
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        bound = bind(api, conn, "keyword")
        original_transaction = conn.get_transaction()
        assert_values(bound, masters, weighing, "10.001", "100.01")
        execute_sql(conn, disable, execution)
        assert conn.exec_driver_sql("PRAGMA query_only").scalar_one() == 0
        # Trusted malicious-caller fixture proves writes actually became possible;
        # only a synthetic probe is changed, and caller later rolls it back.
        execute_sql(conn, "UPDATE test_raw_snapshot_probe SET marker=1", execution)
        execute_sql(conn, enable, execution)
        assert conn.exec_driver_sql("PRAGMA query_only").scalar_one() == 1
        assert conn.exec_driver_sql("SELECT marker FROM test_raw_snapshot_probe").scalar_one() == 1
        assert conn.get_transaction() is original_transaction
        assert_rejected_without_taking_ownership(bound, masters, weighing, conn)
        assert conn.exec_driver_sql("SELECT marker FROM test_raw_snapshot_probe").scalar_one() == 1

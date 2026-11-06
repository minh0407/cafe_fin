"""Monotonic module timers use one core thread and real SQLite/runtime lifetimes."""

import threading
import time
from dataclasses import FrozenInstanceError

import pytest
from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JobHandler
from cafe_fin.core.modules import Migration, ModuleManifest, ModuleRegistry, schema_checksum
from cafe_fin.core.periodic import PeriodicTask
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import DataRootService
from sqlalchemy import Column, Integer, MetaData, Table, insert, select


def make_runtime(tmp_path, tasks, *, hook=None, handlers=None):
    metadata = MetaData()
    probe = Table(
        "sample_periodic_probe",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("value", Integer, nullable=False),
    )

    def startup(runtime):
        assert not runtime.runner.thread.is_alive()
        assert not runtime.periodic.thread.is_alive()

        def initialize(conn):
            if conn.execute(select(probe.c.id)).first() is None:
                conn.execute(insert(probe).values(id=1, value=0))

        runtime.writer.run(initialize)
        if hook:
            hook(runtime)

    manifest = ModuleManifest(
        "sample",
        "/sample",
        periodic_tasks=tasks,
        job_handlers=handlers or {},
        on_startup=startup,
        migrations=(
            Migration(
                "sample", 1, "periodic probe", metadata.create_all, schema_checksum(metadata)
            ),
        ),
    )
    runtime = Runtime(
        tmp_path / "Timer dữ liệu tổng hợp",
        initialize=True,
        modules=ModuleRegistry((manifest,)),
    )
    return runtime, probe


def increment(runtime, probe):
    runtime.writer.run(lambda conn: conn.execute(probe.update().values(value=probe.c.value + 1)))


def assert_resources_closed(runtime):
    assert runtime._closed and runtime.writer._closed
    assert runtime.root._lock is None and runtime.log_handler.stream is None
    assert not runtime.runner.thread.is_alive() and not runtime.periodic.thread.is_alive()


@pytest.mark.parametrize(
    "name",
    [
        "foreign.tick",
        "sample.",
        "sampletick",
        "sample.Tick",
        "sample.tick\n",
        "sample..tick",
        "sample." + "x" * 129,
        7,
    ],
)
def test_invalid_periodic_namespace_fails_registration(name):
    with pytest.raises(CoreError, match="INVALID_PERIODIC_NAMESPACE"):
        ModuleRegistry(
            (
                ModuleManifest(
                    "sample",
                    "/sample",
                    periodic_tasks={name: PeriodicTask(lambda runtime: None, 1)},
                ),
            )
        )


@pytest.mark.parametrize(
    "run,interval",
    [
        (None, 1),
        (3, 1),
        (lambda runtime: None, True),
        (lambda runtime: None, 1.0),
        (lambda runtime: None, 0),
        (lambda runtime: None, -1),
        (lambda runtime: None, 86401),
    ],
)
def test_invalid_callback_or_interval_is_rejected(run, interval):
    with pytest.raises(CoreError, match="INVALID_PERIODIC_TASK"):
        PeriodicTask(run, interval)


def test_periodic_registration_is_frozen_and_bounds_counts_and_types():
    task = PeriodicTask(lambda runtime: None, 86400)
    tasks = {"sample.tick": task}
    manifest = ModuleManifest("sample", "/sample", periodic_tasks=tasks)
    tasks["sample.other"] = task
    assert tuple(manifest.periodic_tasks) == ("sample.tick",)
    with pytest.raises(TypeError):
        manifest.periodic_tasks["sample.other"] = task
    with pytest.raises(FrozenInstanceError):
        task.interval_seconds = 1
    with pytest.raises(CoreError, match="INVALID_PERIODIC_TASK"):
        ModuleManifest("sample", "/sample", periodic_tasks=[])
    with pytest.raises(CoreError, match="INVALID_PERIODIC_TASK"):
        ModuleRegistry(
            (ModuleManifest("sample", "/sample", periodic_tasks={"sample.tick": object()}),)
        )
    with pytest.raises(CoreError, match="PERIODIC_TASK_LIMIT"):
        ModuleRegistry(
            (
                ModuleManifest(
                    "sample", "/sample", periodic_tasks={f"sample.tick{i}": task for i in range(17)}
                ),
            )
        )
    modules = tuple(
        ModuleManifest(
            f"module{i}",
            f"/module{i}",
            periodic_tasks={f"module{i}.tick{n}": task for n in range(16)},
        )
        for i in range(4)
    )
    registry = ModuleRegistry(modules)
    assert sum(len(module.periodic_tasks) for module in registry.ordered()) == 64
    with pytest.raises(CoreError, match="PERIODIC_TASK_LIMIT"):
        registry.register(ModuleManifest("extra", "/extra", periodic_tasks={"extra.tick": task}))


def test_default_runtime_adds_no_timer_thread_and_keeps_start_close_idempotent(tmp_path):
    runtime = Runtime(tmp_path / "No periodic tasks", initialize=True, modules=ModuleRegistry())
    try:
        runtime.start()
        runtime.start()
        assert runtime.periodic.status()["state"] == "IDLE"
        assert runtime.periodic.thread.ident is None and runtime.periodic.error_code is None
        assert runtime.runner.thread.is_alive()
    finally:
        runtime.close()
    runtime.close()
    assert_resources_closed(runtime)
    with pytest.raises(CoreError, match="RUNTIME_CLOSED"):
        runtime.start()


def test_callbacks_start_after_migrations_hooks_jobs_and_stop_before_writer_teardown(tmp_path):
    entered, release, wrote = threading.Event(), threading.Event(), threading.Event()
    errors, observations = [], []

    def callback(runtime):
        observations.append((runtime.runner.thread.is_alive(), runtime._started))
        entered.set()
        assert release.wait(5)
        increment(runtime, probe)
        wrote.set()

    runtime, probe = make_runtime(tmp_path, {"sample.tick": PeriodicTask(callback, 1)})
    closer = None
    try:
        with runtime.reader() as conn:
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
            assert conn.execute(select(probe.c.id)).all() == []
        runtime.start()
        assert entered.wait(4), runtime.periodic.status()

        def close():
            try:
                runtime.close()
            except BaseException as error:
                errors.append(error)

        closer = threading.Thread(target=close)
        closer.start()
        assert runtime.periodic.stop_event.wait(2)
        assert not runtime.writer._closed and runtime.root._lock is not None
        assert closer.is_alive()
        release.set()
        closer.join(5)
        assert not closer.is_alive() and not errors
        assert wrote.is_set() and observations == [(True, True)]
        assert_resources_closed(runtime)
        count = len(observations)
        threading.Event().wait(1.1)
        assert len(observations) == count
        with pytest.raises(CoreError, match="WRITER_CLOSED"):
            runtime.writer.run(lambda conn: None)
    finally:
        release.set()
        if closer:
            closer.join(5)
        runtime.close()


def test_callbacks_are_sequential_nonoverlapping_and_start_is_single_thread(tmp_path):
    observed, thread_ids = [], set()
    active, maximum = 0, 0
    finished = threading.Event()

    def callback(name):
        def run(runtime):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                thread_ids.add(threading.get_ident())
                observed.append(name)
                increment(runtime, probe)
                threading.Event().wait(0.05)
                if observed.count("second") >= 2:
                    finished.set()
            finally:
                active -= 1

        return run

    runtime, probe = make_runtime(
        tmp_path,
        {
            "sample.first": PeriodicTask(callback("first"), 1),
            "sample.second": PeriodicTask(callback("second"), 1),
        },
    )
    try:
        runtime.start()
        runtime.start()
        assert finished.wait(5), runtime.periodic.status()
    finally:
        runtime.close()
    assert observed[:4] == ["first", "second", "first", "second"]
    assert maximum == 1 and len(thread_ids) == 1
    assert runtime.periodic.thread.ident in thread_ids and runtime.periodic.thread.daemon
    with runtime.database.read() as conn:
        assert conn.execute(select(probe.c.value)).scalar_one() == len(observed)


@pytest.mark.parametrize("exception", [RuntimeError, SystemExit])
def test_callback_errors_are_sanitized_and_later_ticks_continue(tmp_path, exception):
    completed, calls = threading.Event(), []
    previous_error = []

    def callback(runtime):
        calls.append(1)
        if len(calls) == 1:
            raise exception("synthetic-secret-and-private-path-must-not-escape")
        previous_error.append(runtime.periodic.status())
        increment(runtime, probe)
        completed.set()

    runtime, probe = make_runtime(tmp_path, {"sample.tick": PeriodicTask(callback, 1)})
    try:
        runtime.start()
        assert completed.wait(5), runtime.periodic.status()
    finally:
        runtime.close()
    status = runtime.periodic.status()
    assert previous_error[0]["error_code"] == "PERIODIC_TASK_FAILED"
    assert status["error_code"] is None and status["last_error_code"] == "PERIODIC_TASK_FAILED"
    assert status["failures"] == {"sample.tick": 1} and status["runs"]["sample.tick"] >= 2
    assert "synthetic-secret" not in repr(previous_error + [status])


def test_startup_hook_failure_closes_core_resources_without_starting_threads(tmp_path):
    def fail(runtime):
        raise CoreError("SAMPLE_STARTUP_FAILED", "Synthetic startup failure")

    runtime, _ = make_runtime(
        tmp_path,
        {"sample.tick": PeriodicTask(lambda runtime: pytest.fail("tick ran"), 1)},
        hook=fail,
    )
    with pytest.raises(CoreError, match="SAMPLE_STARTUP_FAILED"):
        runtime.start()
    assert_resources_closed(runtime)
    assert runtime.periodic.thread.ident is None and runtime.runner.thread.ident is None
    reopened = Runtime(runtime.root.path, modules=runtime.modules)
    reopened.close()
    assert_resources_closed(reopened)


def test_periodic_thread_start_failure_cleans_up_already_started_job_runner(tmp_path, monkeypatch):
    runtime, _ = make_runtime(tmp_path, {"sample.tick": PeriodicTask(lambda runtime: None, 1)})

    def fail():
        assert runtime.runner.thread.is_alive()
        raise RuntimeError("synthetic-private-start-error")

    monkeypatch.setattr(runtime.periodic.thread, "start", fail)
    with pytest.raises(CoreError, match="PERIODIC_START_FAILED") as caught:
        runtime.start()
    assert "synthetic-private" not in caught.value.message
    assert_resources_closed(runtime)
    assert runtime.periodic.error_code == "PERIODIC_START_FAILED"


def test_failure_after_job_thread_starts_does_not_leak_the_worker(tmp_path, monkeypatch):
    runtime, _ = make_runtime(tmp_path, {"sample.tick": PeriodicTask(lambda runtime: None, 1)})
    start = runtime.runner.start

    def fail_after_start():
        start()
        raise CoreError("SAMPLE_WORKER_START_FAILED", "Synthetic startup failure")

    monkeypatch.setattr(runtime.runner, "start", fail_after_start)
    with pytest.raises(CoreError, match="SAMPLE_WORKER_START_FAILED"):
        runtime.start()
    assert_resources_closed(runtime)
    assert runtime.runner.thread.ident is not None and runtime.periodic.thread.ident is None


def test_long_job_handler_does_not_block_independent_periodic_tick(tmp_path):
    entered, release, ticked, completed = (threading.Event() for _ in range(4))
    worker_threads, timer_threads = [], []

    def worker(context, payload):
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        context.finalize(lambda conn: {"complete": True})
        completed.set()

    def callback(runtime):
        timer_threads.append(threading.get_ident())
        increment(runtime, probe)
        ticked.set()

    runtime, probe = make_runtime(
        tmp_path,
        {"sample.tick": PeriodicTask(callback, 1)},
        handlers={"sample.long": JobHandler(worker)},
    )
    job_id = runtime.jobs.submit("synthetic-actor", "sample.long", {}, "long-job")["job_id"]
    try:
        runtime.start()
        assert entered.wait(2)
        assert ticked.wait(3), runtime.periodic.status()
        assert runtime.jobs.status(job_id)["state"] == "RUNNING" and not release.is_set()
        assert worker_threads[0] != timer_threads[0]
        release.set()
        assert completed.wait(3)
    finally:
        release.set()
        runtime.close()


def test_shutdown_timeout_keeps_writer_database_root_open_until_callback_can_finish(tmp_path):
    entered, release, wrote = threading.Event(), threading.Event(), threading.Event()

    def callback(runtime):
        entered.set()
        assert release.wait(30)
        increment(runtime, probe)
        wrote.set()

    runtime, probe = make_runtime(tmp_path, {"sample.tick": PeriodicTask(callback, 1)})
    try:
        runtime.start()
        assert entered.wait(4), runtime.periodic.status()
        started = time.monotonic()
        with pytest.raises(CoreError, match="PERIODIC_SHUTDOWN_TIMEOUT"):
            runtime.close()
        assert time.monotonic() - started >= 9.5
        assert runtime.periodic.thread.is_alive() and runtime.runner.thread.is_alive()
        assert not runtime._closed and not runtime.writer._closed
        assert runtime.root._lock is not None and runtime.log_handler.stream is not None
        assert runtime.periodic.error_code == "PERIODIC_SHUTDOWN_TIMEOUT"
        with runtime.reader() as conn:
            assert conn.execute(select(probe.c.value)).scalar_one() == 0
        increment(runtime, probe)
        with pytest.raises(CoreError, match="DATA_ROOT_LOCKED"):
            DataRootService(runtime.root.path).acquire_lock()
        with pytest.raises(CoreError, match="RUNTIME_CLOSED"):
            runtime.start()
        release.set()
        runtime.close()
        assert wrote.is_set()
        assert_resources_closed(runtime)
        assert runtime.periodic.error_code is None
        reopened = Runtime(runtime.root.path, modules=runtime.modules)
        try:
            with reopened.reader() as conn:
                assert conn.execute(select(probe.c.value)).scalar_one() == 2
        finally:
            reopened.close()
    finally:
        release.set()
        runtime.close()

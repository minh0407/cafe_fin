"""Private IPC boundaries and real child/HTTP closure; only synthetic local roots."""

import io
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from cafe_fin.core.errors import CoreError
from cafe_fin.core.maintenance_protocol import (
    MAX_FRAME_BYTES,
    MAX_RESPONSE_BYTES,
    BootRequest,
    ControlDispatcher,
    FrameWriter,
    parse_command,
    read_frame,
)
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import DataRootService
from pydantic import ValidationError

TOKEN = "synthetic-private-pipe-session-0123456789"
PASSWORD = "synthetic-private-pipe-password"
ORIGIN = "http://tauri.localhost"


def envelope(generation, command="reports.authorize_open", **fields):
    value = {
        "maintenance_protocol": 1,
        "request_id": str(uuid4()),
        "generation": generation,
        "command": command,
        "access_token": "SYNTHETIC-private-token",
    }
    if command not in ("reports.authorize_open", "maintenance.source_identity"):
        value.update(operation_id=str(uuid4()), origin_generation=generation)
    return value | fields


@pytest.mark.parametrize(
    "raw", [b"{}", b"\xff\n", b"{}\n" + b"x", b'{"a":1,"a":2}\n', b'{"a":NaN}\n', b"[]\n"]
)
def test_frame_rejects_malformed_without_echo(raw):
    if raw == b"{}\n" + b"x":
        source = io.BytesIO(raw)
        assert read_frame(source) == {}
        with pytest.raises(CoreError, match="MAINTENANCE_PROTOCOL_INVALID"):
            read_frame(source)
    else:
        with pytest.raises(CoreError, match="MAINTENANCE_PROTOCOL_INVALID") as caught:
            read_frame(io.BytesIO(raw))
        assert str(caught.value) == "MAINTENANCE_PROTOCOL_INVALID"


def test_binary_reader_limits_before_parse_and_keeps_next_frame():
    class Source(io.BytesIO):
        def readline(self, size=-1):
            assert size == MAX_FRAME_BYTES + 1
            return super().readline(size)

    valid = b'{"a":"' + b"x" * (MAX_FRAME_BYTES - 9) + b'"}\n'
    assert len(valid) == MAX_FRAME_BYTES
    source = Source(valid + b"{}\n")
    assert len(read_frame(source)["a"]) == MAX_FRAME_BYTES - 9
    assert read_frame(source) == {} and read_frame(source) is None
    with pytest.raises(CoreError):
        read_frame(Source(valid[:-1] + b" \n"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("extra", "SENSITIVE"),
        ("generation", "UPPER-invalid"),
        ("maintenance_protocol", True),
        ("operation_id", str(uuid4())),
    ],
)
def test_strict_open_reports_schema_denies_fields_and_secrets(field, value):
    command = envelope(str(uuid4())) | {field: value}
    with pytest.raises(CoreError, match="MAINTENANCE_PROTOCOL_INVALID") as caught:
        parse_command(command)
    assert "SENSITIVE" not in repr(caught.value)


def test_paths_capability_and_repr_are_bounded(tmp_path):
    generation = str(uuid4())
    boot = dict(
        protocol_version=1, session_token=TOKEN, data_root=str(tmp_path), allowed_origin=ORIGIN
    )
    assert BootRequest.model_validate(boot).activation_mode == "active"
    assert TOKEN not in repr(BootRequest.model_validate(boot))
    with pytest.raises((CoreError, ValidationError)):
        BootRequest.model_validate(boot | {"activation_mode": "dormant"})
    with pytest.raises((CoreError, ValidationError)):
        BootRequest.model_validate(boot | {"maintenance_protocol": True, "generation": generation})
    for bad in ["a" * 32768, str(tmp_path / ("😀" * 24576)), "relative", str(tmp_path) + "\x00"]:
        with pytest.raises((CoreError, ValidationError, UnicodeError)):
            BootRequest.model_validate(boot | {"data_root": bad})
    request = envelope(
        generation,
        "maintenance.prepare",
        kind="restore",
        destination=str(tmp_path / "candidate"),
        backup_source=str(tmp_path / "backup"),
    )
    parsed = parse_command(request)
    assert "SYNTHETIC-private-token" not in repr(parsed)
    assert str(tmp_path) not in repr(parsed)
    for wrong in [
        request | {"third_path": "SENSITIVE"},
        request | {"kind": "move"},
        request | {"backup_source": None},
    ]:
        with pytest.raises(CoreError):
            parse_command(wrong)


@pytest.mark.parametrize("failure", [RuntimeError, SystemExit])
def test_dispatch_correlation_nonce_generation_whitelist_and_unknown_error(failure):
    generation, root_id = str(uuid4()), str(uuid4())
    state = {"state": "ACTIVE"}
    calls = []

    def allowed(token):
        calls.append(token)
        return {"allowed": True, "root_id": root_id, "path": "SENSITIVE-PATH", "token": token}

    ops = SimpleNamespace(authorize_open_reports=allowed)
    runtime = SimpleNamespace(maintenance=SimpleNamespace(status=lambda: state))
    dispatcher = ControlDispatcher(runtime, generation, operations=ops, close=lambda: None)
    value = envelope(generation)
    result = dispatcher.execute(parse_command(value))
    assert result["request_id"] == value["request_id"] and result["generation"] == generation
    assert result["allowed"] and result["root_id"] == root_id
    assert "SENSITIVE" not in json.dumps(result)
    assert dispatcher.execute(parse_command(value))["code"] == "MAINTENANCE_REQUEST_REPLAY"
    stale = envelope(str(uuid4()))
    assert dispatcher.execute(parse_command(stale))["code"] == "MAINTENANCE_GENERATION_CONFLICT"
    assert len(calls) == 1
    ops.authorize_open_reports = lambda token: (_ for _ in ()).throw(
        failure("SENSITIVE private error")
    )
    error = dispatcher.execute(parse_command(envelope(generation)))
    assert error["code"] == "MAINTENANCE_COMMAND_FAILED" and "SENSITIVE" not in json.dumps(error)
    ops.status = lambda *args, **kwargs: {
        "state": "FAILED_HELD",
        "code": "BACKUP_INVALID",
        "path": "SENSITIVE",
    }
    failed = dispatcher.execute(parse_command(envelope(generation, "maintenance.status")))
    assert failed["state"] == "FAILED_HELD" and failed["runtime_state"] == "ACTIVE"
    assert failed["status"] == "error" and failed["code"] == "BACKUP_INVALID"
    assert "SENSITIVE" not in json.dumps(failed)
    output = io.BytesIO()
    FrameWriter(output).write(error)
    assert len(output.getvalue()) <= MAX_RESPONSE_BYTES
    with pytest.raises(CoreError, match="MAINTENANCE_RESPONSE_INVALID"):
        FrameWriter(output).write({"x": "a" * MAX_RESPONSE_BYTES})


def test_close_authorization_precedes_callback_and_failing_close_has_no_success():
    generation = str(uuid4())
    state = {"state": "ACTIVE"}
    calls = []

    def authorize(*args, **kwargs):
        calls.append("authorize")
        raise CoreError("PERMISSION_DENIED", "Fixed", 403)

    runtime = SimpleNamespace(maintenance=SimpleNamespace(status=lambda: state))
    ops = SimpleNamespace(authorize_close=authorize)
    dispatcher = ControlDispatcher(
        runtime, generation, operations=ops, close=lambda: calls.append("close")
    )
    assert (
        dispatcher.execute(parse_command(envelope(generation, "maintenance.close")))["code"]
        == "PERMISSION_DENIED"
    )
    assert calls == ["authorize"] and not dispatcher.close_attempted
    ops.authorize_close = lambda *args, **kwargs: calls.append("authorize")
    result = dispatcher.execute(parse_command(envelope(generation, "maintenance.close")))
    assert result["status"] == "error" and result["state"] != "CLOSED"
    assert dispatcher.close_attempted and calls == ["authorize", "authorize", "close"]


class Child:
    def __init__(self, root, *, negotiated=True, mode="active", initialize=True, patches=""):
        self.generation = str(uuid4())
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).parents[2] / "backend")
        environment["PYTHONUTF8"] = "1"
        code = (
            "import cafe_fin.__main__ as entry\n" + patches + "\nraise SystemExit(entry.main())\n"
        )
        self.process = subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.messages = queue.Queue()
        self.lines = []

        def consume():
            while raw := self.process.stdout.readline(MAX_RESPONSE_BYTES + 1):
                assert len(raw) <= MAX_RESPONSE_BYTES
                self.lines.append(raw)
                self.messages.put(json.loads(raw))

        threading.Thread(target=consume, daemon=True).start()
        boot = dict(
            protocol_version=1,
            session_token=TOKEN,
            data_root=str(root),
            initialize=initialize,
            allowed_origin=ORIGIN,
        )
        if negotiated:
            boot.update(maintenance_protocol=1, generation=self.generation, activation_mode=mode)
        self.send(boot)
        self.boot = self.read()
        self.base = self.boot["api_base"]

    def send(self, value):
        self.process.stdin.write((json.dumps(value) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def read(self):
        return self.messages.get(timeout=20)

    def control(self, command, token, **fields):
        request = envelope(self.generation, command, access_token=token, **fields)
        self.send(request)
        result = self.read()
        assert result["request_id"] == request["request_id"]
        assert result["generation"] == self.generation
        return result

    def finish(self):
        if self.process.poll() is None:
            try:
                self.send({"command": "shutdown"})
                self.process.wait(timeout=20)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                self.process.kill()  # Test cleanup only; never accepted as closure proof.
                self.process.wait(timeout=10)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


def login(client, child, *, setup=False, username="pipe-admin"):
    response = client.post(
        child.base + ("/auth/setup" if setup else "/auth/login"),
        headers={"X-App-Session": TOKEN},
        json={"username": username, "password": PASSWORD},
    )
    response.raise_for_status()
    return response.json()["access_token"]


def test_legacy_child_shutdown_and_negotiated_eof_are_distinct(tmp_path):
    legacy = Child(tmp_path / "legacy", negotiated=False)
    try:
        assert legacy.boot["status"] == "ready" and "maintenance_protocol" not in legacy.boot
        legacy.send({"command": "shutdown"})
        assert legacy.process.wait(timeout=20) == 0
    finally:
        legacy.finish()
    child = Child(tmp_path / "eof")
    try:
        child.process.stdin.close()
        assert child.process.wait(timeout=20) != 0
        assert not any(json.loads(line).get("state") == "CLOSED" for line in child.lines)
    finally:
        child.finish()


def test_real_backup_status_reports_permissions_nonce_revocation_and_clean_close(tmp_path):
    # Tiny window exercises the same eviction algorithm with real core receipts;
    # a separate dispatcher boundary test exercises more than the default 4096 IDs.
    child = Child(
        tmp_path / "source",
        patches="import cafe_fin.core.maintenance_protocol as protocol\nprotocol.REPLAY_WINDOW_SIZE=2",
    )
    try:
        assert child.boot["maintenance_protocol"] == 1 and child.boot["runtime_state"] == "ACTIVE"
        with httpx.Client(trust_env=False, timeout=10) as client:
            token = login(client, child, setup=True)
            source_identity = child.control("maintenance.source_identity", token)
            assert set(source_identity) == {
                "maintenance_protocol",
                "request_id",
                "generation",
                "status",
                "state",
                "runtime_state",
                "root_id",
                "source_fingerprint",
            }
            assert source_identity["state"] == source_identity["runtime_state"] == "ACTIVE"
            headers = {"X-App-Session": TOKEN, "Authorization": "Bearer " + token}
            client.post(
                child.base + "/users",
                headers=headers,
                json=dict(
                    username="pipe-operator",
                    password=PASSWORD,
                    role="operator",
                    request_key="operator",
                ),
            ).raise_for_status()
            operator = login(client, child, username="pipe-operator")
            opened = child.control("reports.authorize_open", operator)
            assert opened["allowed"] and opened["root_id"]
            repeated = envelope(child.generation, access_token=operator)
            child.send(repeated)
            assert child.read()["allowed"]
            child.send(repeated)
            assert child.read()["code"] == "MAINTENANCE_REQUEST_REPLAY"
            stale = envelope(str(uuid4()), access_token=operator)
            child.send(stale)
            assert child.read()["code"] == "MAINTENANCE_GENERATION_CONFLICT"
            denied = child.control("maintenance.status", operator)
            assert denied["code"] == "PERMISSION_DENIED"
            denied = child.control("maintenance.quiesce", operator)
            assert denied["code"] == "PERMISSION_DENIED" and denied["runtime_state"] == "ACTIVE"
            users = client.get(child.base + "/users", headers=headers).json()["items"]
            operator_id = next(user["id"] for user in users if user["username"] == "pipe-operator")
            client.patch(
                child.base + "/users/" + operator_id,
                headers=headers,
                json=dict(
                    role="operator",
                    active=False,
                    expected_version=1,
                    request_key="disable-operator",
                ),
            ).raise_for_status()
            assert child.control("reports.authorize_open", operator)["code"] == "SESSION_EXPIRED"
            operation = str(uuid4())
            destination = tmp_path / ("CafeFinBackup-" + operation)
            prepare_request = envelope(
                child.generation,
                "maintenance.prepare",
                access_token=token,
                operation_id=operation,
                kind="backup",
                destination=str(destination),
            )
            child.send(prepare_request)
            prepared = child.read()
            assert prepared["state"] == "PREPARED", prepared
            assert prepared["source_root_id"] == source_identity["root_id"]
            assert prepared["source_fingerprint"] == source_identity["source_fingerprint"]
            assert len(prepared["manifest_sha256"]) == 64 and destination.is_dir()
            for _ in range(2):
                assert child.control("reports.authorize_open", token)["allowed"]
            child.send(prepare_request)  # same wire ID was evicted; core receipt is authoritative
            replay = child.read()
            assert (
                replay["state"] == "PREPARED"
                and replay["manifest_sha256"] == prepared["manifest_sha256"]
            )
            assert replay["candidate_fingerprint"] == prepared["candidate_fingerprint"]
            status = child.control("maintenance.status", token, operation_id=operation)
            assert (
                status["state"] == "PREPARED"
                and status["manifest_sha256"] == prepared["manifest_sha256"]
            )
            client.post(child.base + "/auth/logout", headers=headers).raise_for_status()
            assert (
                child.control("maintenance.status", token, operation_id=operation)["code"]
                == "SESSION_EXPIRED"
            )
            child.send(prepare_request)  # evicted again, but token is now logged out
            assert child.read()["code"] == "SESSION_EXPIRED"
            token = login(client, child)
            closed = child.control("maintenance.close", token, operation_id=operation)
            assert closed["status"] == "ok" and closed["state"] == "CLOSED"
            assert child.process.wait(timeout=10) == 0
            with pytest.raises(httpx.TransportError):
                client.get(child.base + "/health", headers={"X-App-Session": TOKEN})
            root = DataRootService(tmp_path / "source")
            root.acquire_lock()
            root.release_lock()
        transcript = b"".join(child.lines).decode()
        assert token not in transcript and str(tmp_path) not in transcript
    finally:
        child.finish()


def test_real_move_guard_dormant_login_and_activation(tmp_path):
    source = Child(tmp_path / "move-source")
    target = active = legacy = None
    try:
        with httpx.Client(trust_env=False, timeout=10) as client:
            token = login(client, source, setup=True)
            operation = str(uuid4())
            destination = tmp_path / ("CafeFinData-" + operation)
            assert (
                source.control("maintenance.quiesce", token, operation_id=operation)["state"]
                == "QUIESCED"
            )
            prepared = source.control(
                "maintenance.prepare",
                token,
                operation_id=operation,
                kind="move",
                destination=str(destination),
            )
            assert prepared["state"] == "PREPARED", prepared
            assert (
                source.control("maintenance.close", token, operation_id=operation)["state"]
                == "CLOSED"
            )
            assert source.process.wait(timeout=10) == 0
            active = Child(destination, initialize=False)
            assert (
                active.boot["status"] == "error" and active.boot["code"] == "MAINTENANCE_REQUIRED"
            )
            assert active.process.wait(timeout=10) != 0
            legacy = Child(destination, negotiated=False, initialize=False)
            assert legacy.boot["code"] == "MAINTENANCE_REQUIRED"
            assert legacy.process.wait(timeout=10) != 0
            target = Child(destination, initialize=False, mode="dormant")
            assert target.boot["runtime_state"] == "DORMANT"
            headers = {"X-App-Session": TOKEN}
            assert client.get(target.base + "/health", headers=headers).status_code == 200
            assert client.get(target.base + "/accounting/books", headers=headers).status_code == 503
            target_token = login(client, target)
            activated = target.control(
                "maintenance.activate",
                target_token,
                operation_id=operation,
                origin_generation=source.generation,
            )
            assert activated["status"] == "ok" and activated["state"] == "ACTIVE", activated
            assert (
                target.control(
                    "maintenance.close",
                    target_token,
                    operation_id=operation,
                    origin_generation=source.generation,
                )["state"]
                == "CLOSED"
            )
            assert target.process.wait(timeout=10) == 0
    finally:
        for child in (source, target, active, legacy):
            if child is not None:
                child.finish()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"command":"shutdown","extra":"SENSITIVE"}\n',
        b"\xff\n",
        b"{" + b"x" * MAX_FRAME_BYTES + b"\n",
    ],
)
def test_real_control_malformed_oversize_fail_closed_without_echo(tmp_path, raw):
    child = Child(tmp_path / str(uuid4()))
    try:
        child.process.stdin.write(raw)
        child.process.stdin.flush()
        assert child.process.wait(timeout=20) != 0
        assert b"SENSITIVE" not in b"".join(child.lines)
        assert not any(json.loads(line).get("state") == "CLOSED" for line in child.lines)
    finally:
        child.finish()


def test_actual_dormant_starts_no_jobs_timer_or_recovery(tmp_path):
    root, observed = tmp_path / "dormant", tmp_path / "threads.json"
    seed = Runtime(root, initialize=True, modules=ModuleRegistry(()))
    try:
        session = seed.auth.setup("pipe-admin", PASSWORD)
        actor = seed.auth.authenticate(session["access_token"])
        job = seed.jobs.submit(actor.id, "foundation.sample", {}, "pending")["job_id"]
    finally:
        seed.close()
    patches = f"""
import json, threading
from pathlib import Path
actual_start = entry.Runtime.start
def observed_start(runtime):
    actual_start(runtime)
    Path({str(observed)!r}).write_text(json.dumps({{"threads":[t.name for t in threading.enumerate()], "job":runtime.jobs.status({job!r})["state"]}}),encoding="utf8")
entry.Runtime.start = observed_start
"""
    child = Child(root, initialize=False, mode="dormant", patches=patches)
    try:
        assert child.boot["runtime_state"] == "DORMANT"
        result = json.loads(observed.read_text(encoding="utf8"))
        assert result["job"] == "WAITING"
        assert (
            "cafe-fin-jobs" not in result["threads"]
            and "cafe-fin-periodic" not in result["threads"]
        )
        with httpx.Client(trust_env=False, timeout=10) as client:
            token = login(client, child)
            assert child.control("reports.authorize_open", token)["allowed"]
            denied = client.get(
                child.base + "/users",
                headers={"X-App-Session": TOKEN, "Authorization": "Bearer " + token},
            )
            assert denied.status_code == 503
    finally:
        child.finish()


def test_close_ack_waits_for_real_http_stream_and_all_finalizers(tmp_path):
    release = tmp_path / "release-stream"
    patches = f"""
from pathlib import Path
import time
from fastapi.responses import StreamingResponse
actual_app = entry.create_app
def patched_app(*args,**kwargs):
    app=actual_app(*args,**kwargs)
    @app.get('/api/v1/test-stream')
    def test_stream():
        def body():
            yield b'first'
            until=time.monotonic()+10
            while not Path({str(release)!r}).exists():
                if time.monotonic()>until: raise RuntimeError('Synthetic stream gate expired')
                time.sleep(.01)
            yield b'last'
        return StreamingResponse(body())
    return app
entry.create_app=patched_app
"""
    child = Child(tmp_path / "stream-root", patches=patches)
    entered = threading.Event()
    errors, contents = [], []
    thread = None
    try:
        with httpx.Client(trust_env=False, timeout=15) as client:
            token = login(client, child, setup=True)
            operation = str(uuid4())
            assert (
                child.control(
                    "maintenance.prepare",
                    token,
                    operation_id=operation,
                    kind="backup",
                    destination=str(tmp_path / ("CafeFinBackup-" + operation)),
                )["state"]
                == "PREPARED"
            )

            def read_stream():
                try:
                    with httpx.stream(
                        "GET",
                        child.base + "/test-stream",
                        headers={"X-App-Session": TOKEN, "Authorization": "Bearer " + token},
                        trust_env=False,
                        timeout=15,
                    ) as response:
                        response.raise_for_status()
                        for chunk in response.iter_raw():
                            contents.append(chunk)
                            entered.set()
                except Exception as error:
                    errors.append(type(error).__name__)

            thread = threading.Thread(target=read_stream)
            thread.start()
            assert entered.wait(5)
            request = envelope(
                child.generation, "maintenance.close", access_token=token, operation_id=operation
            )
            child.send(request)
            with pytest.raises(queue.Empty):
                child.messages.get(timeout=0.2)
            assert child.process.poll() is None
            release.write_text("release", encoding="utf8")
            response = child.read()
            assert response["request_id"] == request["request_id"] and response["state"] == "CLOSED"
            assert child.process.wait(timeout=10) == 0
            thread.join(timeout=5)
            assert not thread.is_alive() and not errors and b"".join(contents) == b"firstlast"
    finally:
        release.touch(exist_ok=True)
        if thread:
            thread.join(timeout=5)
        child.finish()


def test_post_http_final_close_failure_never_emits_closed_ack(tmp_path):
    patches = """
import threading
from cafe_fin.core.errors import CoreError
actual_close=entry.Runtime.close
ipc_closes=0
def fail_final_close(runtime,*args,**kwargs):
    global ipc_closes
    if threading.current_thread().name=='cafe-fin-ipc':
        ipc_closes+=1
        if ipc_closes==2: raise CoreError('SHUTDOWN_FAILED','Fixed synthetic failure',503)
    return actual_close(runtime,*args,**kwargs)
entry.Runtime.close=fail_final_close
"""
    child = Child(tmp_path / "final-fault", patches=patches)
    try:
        with httpx.Client(trust_env=False, timeout=10) as client:
            token = login(client, child, setup=True)
            operation = str(uuid4())
            assert (
                child.control(
                    "maintenance.prepare",
                    token,
                    operation_id=operation,
                    kind="backup",
                    destination=str(tmp_path / ("CafeFinBackup-" + operation)),
                )["state"]
                == "PREPARED"
            )
            response = child.control("maintenance.close", token, operation_id=operation)
            assert response["status"] == "error" and response["code"] == "SHUTDOWN_FAILED"
            assert response["state"] != "CLOSED"
            assert child.process.wait(timeout=10) != 0
            assert not any(
                json.loads(line).get("status") == "ok" and json.loads(line).get("state") == "CLOSED"
                for line in child.lines
            )
    finally:
        child.finish()


@pytest.mark.parametrize("raw", [b"\xff\n", b"{" + b"x" * MAX_FRAME_BYTES + b"\n"])
def test_real_bad_boot_is_bounded_and_sanitized(tmp_path, raw):
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[2] / "backend"))
    result = subprocess.run(
        [sys.executable, "-m", "cafe_fin"],
        input=raw,
        capture_output=True,
        env=environment,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode != 0 and len(result.stdout) <= MAX_RESPONSE_BYTES
    assert json.loads(result.stdout)["code"] == "BOOT_PROTOCOL_INVALID"


def test_recent_nonce_window_does_not_cap_lifetime_or_disable_close():
    from cafe_fin.core.maintenance_protocol import REPLAY_WINDOW_SIZE

    generation, root_id = str(uuid4()), str(uuid4())
    state = {"state": "ACTIVE"}
    authorized = [True]
    calls = []

    def current(token):
        calls.append(token)
        if not authorized[0]:
            raise CoreError("SESSION_EXPIRED", "Fixed", 401)
        return {"allowed": True, "root_id": root_id}

    def close_auth(*args, **kwargs):
        return current(kwargs["access_token"])

    ops = SimpleNamespace(authorize_open_reports=current, authorize_close=close_auth)
    runtime = SimpleNamespace(maintenance=SimpleNamespace(status=lambda: state))
    dispatcher = ControlDispatcher(
        runtime, generation, operations=ops, close=lambda: state.update(state="CLOSED")
    )
    oldest = envelope(generation)
    assert dispatcher.execute(parse_command(oldest))["allowed"]
    for _ in range(REPLAY_WINDOW_SIZE + 3):
        recent = envelope(generation)
        assert dispatcher.execute(parse_command(recent))["status"] == "ok"
    assert len(dispatcher._seen) == REPLAY_WINDOW_SIZE
    assert dispatcher.execute(parse_command(recent))["code"] == "MAINTENANCE_REQUEST_REPLAY"
    assert dispatcher.execute(parse_command(oldest))[
        "allowed"
    ]  # old ID evicted, fresh auth still called
    authorized[0] = False
    for _ in range(REPLAY_WINDOW_SIZE):
        assert dispatcher.execute(parse_command(envelope(generation)))["code"] == "SESSION_EXPIRED"
    assert dispatcher.execute(parse_command(oldest))["code"] == "SESSION_EXPIRED"
    authorized[0] = True
    closed = dispatcher.execute(parse_command(envelope(generation, "maintenance.close")))
    assert closed["status"] == "ok" and closed["state"] == "CLOSED" and dispatcher.close_attempted


def test_reports_authorization_uses_current_reporting_read_policy(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path / "permission-policy", initialize=True, modules=ModuleRegistry(()))
    try:
        auth = runtime.auth.setup("policy-admin", PASSWORD)
        admin = runtime.auth.authenticate(auth["access_token"])
        runtime.auth.create_user(
            admin,
            username="policy-operator",
            password=PASSWORD,
            role="operator",
            request_key="operator",
        )
        token = runtime.auth.login("policy-operator", PASSWORD)["access_token"]
        generation = str(uuid4())
        dispatcher = ControlDispatcher(runtime, generation, close=lambda: None)
        denied = [False]
        observed = []
        original = runtime.auth.authorize

        def current_policy(connection, actor, permission):
            observed.append(permission)
            if denied[0] and permission == "reporting.read":
                raise CoreError("PERMISSION_DENIED", "Fixed current policy", 403)
            return original(connection, actor, permission)

        monkeypatch.setattr(runtime.auth, "authorize", current_policy)
        assert dispatcher.execute(parse_command(envelope(generation, access_token=token)))[
            "allowed"
        ]
        denied[0] = True
        result = dispatcher.execute(parse_command(envelope(generation, access_token=token)))
        assert result["code"] == "PERMISSION_DENIED"
        assert observed == ["reporting.read", "reporting.read"]
    finally:
        runtime.close()

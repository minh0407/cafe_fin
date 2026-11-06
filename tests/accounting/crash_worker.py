"""Synthetic process-crash fixture; invoked only by test_process_crash.py.

Never point this script at an existing application data root. Input/output JSON
contains synthetic IDs/counts only; os._exit intentionally bypasses cleanup.
"""

import io
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JobContext
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime

EXIT_CRASH = 86
USERNAME = "synthetic-crash-admin"
PASSWORD = "synthetic-crash-password"


def wait(service, actor, batch_id, expected="COMPLETED"):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        batch = service.get_batch(actor, batch_id)
        state = batch.get("job", {}).get("state")
        if state == "COMPLETED" and batch["state"] in {
            "UPLOADED",
            "PARSING",
            "VALIDATING",
            "COMMITTING",
        }:
            time.sleep(0.01)
            continue
        if state in {"COMPLETED", "FAILED", "RECOVERABLE", "CANCELLED"}:
            if state != expected:
                raise RuntimeError("synthetic fixture job state mismatch")
            return batch
        time.sleep(0.01)
    raise RuntimeError("synthetic fixture deadline exceeded")


def save(path, value):
    temporary = path.with_suffix(".part")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def main():
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    root, metadata_path = Path(config["root"]), Path(config["metadata"])
    if root.exists():
        raise RuntimeError("fixture root must be fresh")
    mode, row_count = config["mode"], config["rows"]
    runtime = Runtime(root, initialize=True, modules=ModuleRegistry((module_manifest(),)))
    session = runtime.auth.setup(USERNAME, PASSWORD)
    actor = runtime.auth.authenticate(session["access_token"])
    service = AccountingService(runtime)
    book = service.create_book(
        actor,
        "Synthetic crash book",
        [
            {"id": "code", "name": "Code", "kind": "text", "required": True},
            {"id": "day", "name": "Day", "kind": "date", "required": True},
            {"id": "amount", "name": "Amount", "kind": "money", "required": True},
        ],
        {"date_column": "day", "income_column": "amount"},
        str(uuid4()),
    )
    source = "code,day,amount\n" + "".join(
        f"{index:07d},2026-02-01,1.01\n" for index in range(row_count)
    )
    stored = runtime.files.put(
        io.BytesIO(source.encode()),
        category="workbooks",
        original_name="synthetic-crash.csv",
        actor=actor.id,
        request_key=str(uuid4()),
        authorize=service.authorize(actor),
    )
    batch = service.create_batch(actor, book["id"], stored.id, {}, str(uuid4()))
    metadata = {
        "book_id": book["id"],
        "batch_id": batch["id"],
        "file_id": stored.id,
        "source_sha256": stored.sha256,
        "rows": row_count,
        "mode": mode,
    }
    save(metadata_path, metadata)
    original_chunk, original_finalize = JobContext.commit_chunk, JobContext.finalize

    def crash_chunk(context, *args, **kwargs):
        phase = kwargs["phase"]
        selected = (
            (mode.startswith("parse_") and phase == "parse")
            or (mode.startswith("validation_") and phase == "normalize")
            or (mode.startswith("pending_") and phase == "commit_pending")
        )
        if selected and mode.endswith("before"):
            os._exit(EXIT_CRASH)
        if selected and mode.endswith("precommit"):
            original_effect = kwargs["effect"]

            def uncommitted_effect(connection):
                original_effect(connection)
                os._exit(EXIT_CRASH)

            kwargs["effect"] = uncommitted_effect
        result = original_chunk(context, *args, **kwargs)
        if selected and mode.endswith("after_commit"):
            os._exit(EXIT_CRASH)
        if selected and mode.endswith("failure"):
            raise CoreError("SYNTHETIC_PHASE_FAILURE", "Synthetic checkpoint failure.", 503)
        return result

    def crash_finalize(context, effect):
        result = original_finalize(context, effect)
        if (
            mode == "published_before_ack"
            and context.service.status(context.job_id)["kind"] == "accounting.commit"
        ):
            os._exit(EXIT_CRASH)
        return result

    JobContext.commit_chunk = crash_chunk
    JobContext.finalize = crash_finalize
    runtime.start()
    if mode.startswith("parse_"):
        wait(service, actor, batch["id"], "FAILED" if mode.endswith("failure") else "COMPLETED")
        if mode.endswith("failure"):
            os._exit(EXIT_CRASH)
        raise RuntimeError("parse crash hook was not reached")
    batch = wait(service, actor, batch["id"])
    batch = service.mapping(
        actor,
        batch["id"],
        batch["version"],
        {"code": "A", "day": "B", "amount": "C"},
        {},
        str(uuid4()),
    )
    service.validate(actor, batch["id"], batch["version"], str(uuid4()))
    if mode.startswith("validation_"):
        wait(service, actor, batch["id"], "FAILED" if mode.endswith("failure") else "COMPLETED")
        if mode.endswith("failure"):
            os._exit(EXIT_CRASH)
        raise RuntimeError("validation crash hook was not reached")
    batch = wait(service, actor, batch["id"])
    command = {
        "expected_version": batch["version"],
        "staging_revision": batch["revision"],
        "mapping_revision": batch["mapping_revision"],
        "decision_revision": batch["decision_revision"],
        "validation_token": batch["validation_token"],
        "mode": "valid_rows_only",
        "request_key": str(uuid4()),
    }
    metadata["confirm_command"] = command
    save(metadata_path, metadata)
    service.confirm(actor, batch["id"], command)
    wait(service, actor, batch["id"])
    if mode == "published_before_ack":
        # COMPLETED is visible before the worker returns from finalize; allow
        # that worker to execute its immediate post-commit os._exit hook.
        time.sleep(5)
    raise RuntimeError("commit crash hook was not reached")


if __name__ == "__main__":
    main()

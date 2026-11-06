"""Generate summary-only Vietnamese export evidence from synthetic DTO providers."""

import argparse
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting import models
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.service import ReportingService

from tests.reporting.conftest import TypedSyntheticSource, saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--named",
        action="store_true",
        help="Use synthetic v3 names, including literal markup-like text",
    )
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    if args.named:
        from tests.reporting.test_display_names import NamedSource

        source = NamedSource()
    else:
        source = TypedSyntheticSource()
    source.amount = "1234567890.01"
    source.malicious = "SYNTHETIC-LOCAL-NOTE-NOT-FOR-SHARING"
    registry = ModuleRegistry((module_manifest(source=source),))
    runtime = Runtime(output / ("data-" + uuid.uuid4().hex), initialize=True, modules=registry)
    try:
        auth = runtime.auth.setup("reportdemo", "synthetic-evidence-password")
        actor = runtime.auth.authenticate(auth["access_token"])
        service = ReportingService(runtime, source=source)
        report = saved(SimpleNamespace(service=service, actor=actor))
        files = []
        for format in ("pdf", "xlsx", "txt"):
            exported = service.export(
                actor, report["id"], models.Export(request_key=format, format=format)
            )
            target = output / ("reporting-demo." + format)
            with runtime.files.read(exported["file_id"]) as stream:
                target.write_bytes(stream.read())
            files.append(
                {"path": str(target), "sha256": exported["sha256"], "size": exported["size"]}
            )
        print(json.dumps({"files": files, "snapshot_sha256": report["sha256"]}))
    finally:
        runtime.close()


if __name__ == "__main__":
    main()

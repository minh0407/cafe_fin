"""Seal notices only after a successful full frozen build and notice refresh."""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

INPUTS = (
    "uv.lock",
    "frontend/package-lock.json",
    "desktop/Cargo.lock",
    "desktop/sidecar.spec",
    "desktop/scripts/build-sidecar.ps1",
    "desktop/scripts/refresh-notices.ps1",
    "frontend/scripts/third-party-notices.mjs",
    "desktop/scripts/third-party-notices.mjs",
    "scripts/packaging/notice_provenance.py",
)
OUTPUTS = (
    "backend.txt",
    "frontend.txt",
    "rust.txt",
    "native-license-sources.json",
    "sidecar-native-inventory.json",
    "lgpl-2.1-iconv.txt",
    "tauri-installer-template-license.txt",
    "tauri-installer-template-source.json",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(repo):
    notices = repo / "desktop/notices"
    sidecar = repo / "desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe"
    inventory = json.loads((notices / "sidecar-native-inventory.json").read_text())
    actual = digest(sidecar)
    if (
        actual != inventory["exe_sha256"].lower()
        or sidecar.stat().st_size != inventory["exe_bytes"]
    ):
        raise ValueError("sidecar inventory mismatch")
    for name in OUTPUTS:
        if not (notices / name).is_file() or not (notices / name).stat().st_size:
            raise ValueError("required nonempty notice missing")
    value = {
        "schema_version": 1,
        "source_commit": subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip(),
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "sidecar_sha256": actual,
        "inputs": {name: digest(repo / name) for name in INPUTS},
        "outputs": {name: digest(notices / name) for name in OUTPUTS},
    }
    (notices / "build-inputs.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    write(parser.parse_args().repo)

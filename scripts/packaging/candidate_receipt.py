"""Collect existing source-matched build files; never build, execute or upload them."""

import argparse
import hashlib
import importlib.metadata
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

APP_INPUTS = (
    "backend",
    "frontend",
    "desktop/src",
    "desktop/Cargo.toml",
    "desktop/Cargo.lock",
    "desktop/build.rs",
    "desktop/sidecar.spec",
    "desktop/tauri.conf.json",
    "desktop/capabilities",
    "desktop/permissions",
    "desktop/icons",
    "desktop/scripts",
    "pyproject.toml",
    "uv.lock",
)
NOTICE_FILES = (
    "backend.txt",
    "frontend.txt",
    "rust.txt",
    "native-license-sources.json",
    "sidecar-native-inventory.json",
    "lgpl-2.1-iconv.txt",
)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def entry(root, path):
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("artifact must be a regular contained file")
    return {
        "file": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest(path),
    }


def collect(repo, source, output, allow_missing=False):
    repo = repo.resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("full source commit required")
    if git(repo, "rev-parse", f"{source}^{{commit}}") != source:
        raise ValueError("source commit does not resolve exactly")
    if git(repo, "diff", "--name-only", source, "--", *APP_INPUTS):
        raise ValueError("application build inputs differ from the assigned source")
    if git(repo, "ls-files", "--others", "--exclude-standard", "--", *APP_INPUTS):
        raise ValueError("untracked application input cannot be assigned to source")
    if output.exists():
        raise ValueError("output must be new; existing evidence is never overwritten")
    config = json.loads((repo / "desktop/tauri.conf.json").read_text(encoding="utf-8"))
    windows = config["bundle"]["windows"]
    if windows["webviewInstallMode"]["type"] != "offlineInstaller":
        raise ValueError("candidate must embed the WebView2 offline installer")
    if windows["nsis"]["installMode"] != "currentUser":
        raise ValueError("unexpected install scope")
    sidecar = repo / "desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe"
    inventory = json.loads((repo / "desktop/notices/sidecar-native-inventory.json").read_text())
    if (
        digest(sidecar) != inventory["exe_sha256"].lower()
        or sidecar.stat().st_size != inventory["exe_bytes"]
    ):
        raise ValueError("frozen sidecar and native inventory do not match")
    installers = list((repo / "desktop/target/release/bundle/nsis").glob("*.exe"))
    if len(installers) > 1 or (not installers and not allow_missing):
        raise ValueError("exactly one actual installer required")
    output.mkdir(parents=True)
    for folder in ("binaries", "notices", "source"):
        (output / folder).mkdir()
    shutil.copy2(sidecar, output / "binaries" / sidecar.name)
    if digest(output / "binaries" / sidecar.name) != inventory["exe_sha256"].lower():
        raise ValueError("sidecar changed while collecting")
    if installers:
        (output / "installer").mkdir()
        shutil.copy2(installers[0], output / "installer" / installers[0].name)
    for name in NOTICE_FILES:
        file = repo / "desktop/notices" / name
        if file.is_file() and not file.is_symlink():
            shutil.copy2(file, output / "notices" / file.name)
    source_zip = output / "source" / f"cafe-fin-{source}.zip"
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "archive",
            "--format=zip",
            f"--output={source_zip.resolve()}",
            source,
        ],
        check=True,
    )
    files = [entry(output, path) for path in sorted(output.rglob("*")) if path.is_file()]
    receipt = {
        "schema_version": 1,
        "source_commit": source,
        "tooling_commit": git(repo, "rev-parse", "HEAD"),
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "version": config["version"],
        "target": "x86_64-pc-windows-msvc",
        "build_environment": {
            "python": sys.version.split()[0],
            "sqlite": sqlite3.sqlite_version,
            "pyinstaller": importlib.metadata.version("pyinstaller"),
        },
        "lock_hashes": {
            name: digest(repo / name)
            for name in ("uv.lock", "frontend/package-lock.json", "desktop/Cargo.lock")
        },
        "dependency_manifest_scope": "Locked inputs and full notices; includes conservative build dependencies",
        "install_scope": "currentUser",
        "webview2_mode": "offlineInstaller",
        "webview2_install_acceptance": "NOT_RUN",
        "status": "CANDIDATE_FILES_PRESENT" if installers else "BLOCKED_INSTALLER_MISSING",
        "installer_present": bool(installers),
        "signature_verification": "NOT_RUN",
        "release_clearance": False,
        "client_acceptance": "NOT_RUN",
        "files": files,
    }
    (output / "build-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{item['sha256']}  {item['file']}\n" for item in files)
        + f"{digest(output / 'build-receipt.json')}  build-receipt.json\n",
        encoding="utf-8",
    )
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-missing-installer", action="store_true")
    args = parser.parse_args()
    result = collect(args.repo, args.source, args.output, args.allow_missing_installer)
    print(result["status"])


if __name__ == "__main__":
    main()

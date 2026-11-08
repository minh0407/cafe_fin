"""Synthetic gate tests, not proof of installer/runtime acceptance."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/packaging/candidate_receipt.py"
SPEC = importlib.util.spec_from_file_location("packaging_receipt", SOURCE)
receipt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipt)
PROOF_SPEC = importlib.util.spec_from_file_location(
    "packaging_notice_proof", SOURCE.with_name("notice_provenance.py")
)
proof = importlib.util.module_from_spec(PROOF_SPEC)
PROOF_SPEC.loader.exec_module(proof)


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for folder in ("desktop/binaries", "desktop/notices", "desktop/src"):
        (repo / folder).mkdir(parents=True, exist_ok=True)
    (repo / "frontend").mkdir()
    for name in receipt.NOTICE_INPUTS:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("synthetic lock fixture\n")
    for name in receipt.NOTICE_FILES:
        if name != "build-inputs.json":
            (repo / "desktop/notices" / name).write_text("synthetic notice\n")
    (repo / "desktop/tauri.conf.json").write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "bundle": {
                    "windows": {
                        "webviewInstallMode": {"type": "offlineInstaller"},
                        "nsis": {"installMode": "currentUser"},
                    }
                },
            }
        )
    )
    binary = repo / "desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe"
    binary.write_bytes(b"synthetic bytes; not an executable")
    inventory = {"exe_sha256": receipt.digest(binary), "exe_bytes": binary.stat().st_size}
    (repo / "desktop/notices/sidecar-native-inventory.json").write_text(json.dumps(inventory))
    (repo / "desktop/src/main.rs").write_text("// synthetic receipt fixture\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Synthetic Test",
            "-c",
            "user.email=synthetic@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    proof.write(repo)
    return repo, receipt.git(repo, "rev-parse", "HEAD")


def test_missing_installer_never_becomes_ready_and_default_refuses(repository, tmp_path):
    repo, source = repository
    with pytest.raises(ValueError, match="actual installer"):
        receipt.collect(repo, source, tmp_path / "strict")
    result = receipt.collect(repo, source, tmp_path / "blocked", True)
    assert result["status"] == "BLOCKED_INSTALLER_MISSING"
    assert not result["installer_present"] and not result["release_clearance"]
    assert result["client_acceptance"] == "NOT_RUN"


def test_changed_app_or_inventory_is_refused(repository, tmp_path):
    repo, source = repository
    (repo / "desktop/src/main.rs").write_text("// changed application input\n")
    with pytest.raises(ValueError, match="build inputs differ"):
        receipt.collect(repo, source, tmp_path / "changed", True)
    subprocess.run(["git", "-C", str(repo), "restore", "desktop/src/main.rs"], check=True)
    (repo / "desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe").write_bytes(b"changed")
    with pytest.raises(ValueError, match="inventory do not match"):
        receipt.collect(repo, source, tmp_path / "mismatch", True)


def test_untracked_application_code_cannot_use_clean_source_receipt(repository, tmp_path):
    repo, source = repository
    (repo / "desktop/src/untracked.rs").write_text("// synthetic untracked input\n")
    with pytest.raises(ValueError, match="untracked application"):
        receipt.collect(repo, source, tmp_path / "untracked", True)


def test_no_unlisted_notice_or_existing_output_overwrite(repository, tmp_path):
    repo, source = repository
    (repo / "desktop/notices/unlisted.log").write_text("must not be collected")
    output = tmp_path / "candidate"
    receipt.collect(repo, source, output, True)
    assert not (output / "notices/unlisted.log").exists()
    assert "build-receipt.json" in (output / "SHA256SUMS.txt").read_text()
    with pytest.raises(ValueError, match="never overwritten"):
        receipt.collect(repo, source, output, True)


def test_path_outside_collection_root_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("synthetic")
    with pytest.raises(ValueError, match="contained file"):
        receipt.entry(root, outside)


@pytest.mark.parametrize("name", receipt.NOTICE_FILES)
def test_missing_required_notice_refused(repository, tmp_path, name):
    repo, source = repository
    (repo / "desktop/notices" / name).unlink()
    # Inventory has its own earlier check, before the complete notice set check.
    with pytest.raises((ValueError, FileNotFoundError)):
        receipt.collect(repo, source, tmp_path / "missing", True)
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("field", ("source_commit", "sidecar_sha256", "inputs", "outputs"))
def test_stale_notice_proof_refused(repository, tmp_path, field):
    repo, source = repository
    path = repo / "desktop/notices/build-inputs.json"
    value = json.loads(path.read_text())
    value[field] = {} if field in ("inputs", "outputs") else "0" * 40
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="notice provenance"):
        receipt.collect(repo, source, tmp_path / "stale", True)


def test_changed_notice_bytes_refused(repository, tmp_path):
    repo, source = repository
    (repo / "desktop/notices/rust.txt").write_text("stale or tampered notice")
    with pytest.raises(ValueError, match="notice provenance"):
        receipt.collect(repo, source, tmp_path / "changed-notice", True)


def test_receipt_and_generator_pin_same_inputs_and_outputs():
    assert receipt.NOTICE_INPUTS == proof.INPUTS
    assert receipt.NOTICE_FILES[:-1] == proof.OUTPUTS

"""Manifest/extra-file gates, not installed application evidence."""

import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/packaging/verify_kit.py"
SPEC = importlib.util.spec_from_file_location("packaging_integrity", SOURCE)
integrity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(integrity)


@pytest.fixture
def kit(tmp_path):
    root = tmp_path / "kit"
    root.mkdir()
    data = root / "data.txt"
    data.write_text("synthetic fixture")
    manifest = {
        "source_commit": "0" * 40,
        "status": "PREPARATION_ONLY_NOT_READY_FOR_INSTALL",
        "files": [
            {"file": "data.txt", "bytes": data.stat().st_size, "sha256": integrity.sha(data)}
        ],
    }
    file = root / "kit-manifest.json"
    file.write_text(json.dumps(manifest))
    (root / "SHA256SUMS.txt").write_text(
        f"{integrity.sha(data)}  data.txt\n{integrity.sha(file)}  kit-manifest.json\n"
    )
    return root


def test_integrity_does_not_promote_acceptance_and_zip_reads_back(kit, tmp_path):
    result = integrity.verify(kit, tmp_path / "synthetic.zip")
    assert result["status"] == "FILE_INTEGRITY_PASS_ONLY"
    assert result["runtime_acceptance"] == "NOT_RUN"
    assert result["kit_status"] == "PREPARATION_ONLY_NOT_READY_FOR_INSTALL"


def test_changed_file_or_extra_data_cannot_be_packed(kit, tmp_path):
    (kit / "unlisted.txt").write_text("synthetic extra")
    with pytest.raises(ValueError, match="unlisted"):
        integrity.verify(kit, tmp_path / "not-created.zip")
    assert not (tmp_path / "not-created.zip").exists()


def test_changed_manifest_is_not_hidden_by_valid_file_digest(kit):
    path = kit / "kit-manifest.json"
    value = json.loads(path.read_text())
    value["status"] = "UNREVIEWED"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="checksum list differs"):
        integrity.verify(kit)

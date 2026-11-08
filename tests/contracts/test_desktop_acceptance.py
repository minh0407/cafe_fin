"""Guard the standalone acceptance harness without substituting for a real run."""

from types import SimpleNamespace

import pytest

from .desktop_acceptance import (
    AcceptanceFailure,
    execution_identity,
    fresh_paths,
    validate_handshake,
)


def test_existing_operational_root_is_refused_without_changing_its_marker(tmp_path):
    root = tmp_path / "Existing operational root"
    root.mkdir()
    marker = root / ".cafe-fin-root.json"
    marker.write_bytes(b"synthetic-existing-marker")
    with pytest.raises(AcceptanceFailure, match="FRESH_NONEXISTENT_PATH_REQUIRED"):
        fresh_paths(root, tmp_path / "new-output")
    assert marker.read_bytes() == b"synthetic-existing-marker"
    assert not (tmp_path / "new-output").exists()


@pytest.mark.parametrize("marker", [".git", ".cafe-fin-root.json"])
def test_new_child_paths_inside_repository_or_operational_root_are_refused(tmp_path, marker):
    parent = tmp_path / "guarded"
    parent.mkdir()
    (parent / marker).write_text("synthetic guard", encoding="utf-8")
    with pytest.raises(AcceptanceFailure, match="PATH_INSIDE_"):
        fresh_paths(parent / "new-data", tmp_path / "new-output")
    assert not (parent / "new-data").exists()


@pytest.mark.parametrize(
    "base",
    [
        "http://outside.example/api/v1",
        "http://127.0.0.1:9876/other",
        "http://user@127.0.0.1:9876/api/v1",
        "https://127.0.0.1:9876/api/v1",
        "http://127.0.0.1:9876/api/v1?token=synthetic",
    ],
)
def test_handshake_cannot_redirect_authenticated_client_outside_expected_loopback(base):
    with pytest.raises(AcceptanceFailure, match="NON_LOOPBACK_HANDSHAKE_DENIED"):
        validate_handshake({"protocol_version": 1, "status": "ready", "api_base": base})


def test_frozen_source_match_is_not_granted_by_caller_metadata(tmp_path):
    source = tmp_path / "source"
    (source / "backend").mkdir(parents=True)
    (source / "backend" / "example.py").write_text("synthetic = True\n", encoding="utf-8")
    binary = tmp_path / "synthetic.exe"
    binary.write_bytes(b"MZsynthetic-not-executed")
    provenance = tmp_path / "assertion.json"
    provenance.write_text('{"verified":true,"source_sha":"caller-assertion"}', encoding="utf-8")
    result = execution_identity(
        SimpleNamespace(binary=binary, python=None, source_root=source, provenance=provenance)
    )
    assert result["mode"] == "frozen_binary"
    assert result["source_match"] == "NOT_VERIFIED_BY_HARNESS"
    assert result["supplied_provenance"]["trust"].startswith("EXTERNAL_EVIDENCE_NOT_INDEPENDENTLY")
    assert result["executable_sha256"] and result["source"]["tree_sha256"]

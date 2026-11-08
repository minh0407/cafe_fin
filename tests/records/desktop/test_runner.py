"""Fail closed on a mismatched frozen artifact before spawning any executable."""

import hashlib
import json

import pytest

from .runner import verify_attestation

COMMIT = "eab8c96b851f039de515083189f4301cc09437c0"


def receipt_for(tmp_path):
    binary = tmp_path / "synthetic-never-executed.exe"
    binary.write_bytes(b"synthetic fixture; this file is not an executable")
    receipt = tmp_path / "build-attestation.json"
    payload = {
        "schema_version": 1,
        "source_commit": COMMIT,
        "sidecar": {
            "filename": binary.name,
            "bytes": binary.stat().st_size,
            "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        },
    }
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    return binary, receipt, payload


def test_attestation_matches_exact_source_and_binary(tmp_path):
    binary, receipt, payload = receipt_for(tmp_path)
    result = verify_attestation(binary, receipt, COMMIT)
    assert result["sha256"] == payload["sidecar"]["sha256"]
    assert result["source_commit"] == COMMIT
    assert result["attestation_sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "field,value,step",
    [
        ("source_commit", "0" * 40, "attestation_source"),
        ("schema_version", True, "attestation_schema"),
        ("filename", "other.exe", "attestation_filename"),
        ("bytes", True, "attestation_bytes"),
        ("bytes", 1, "attestation_bytes"),
        ("sha256", "0" * 64, "attestation_hash"),
    ],
)
def test_attestation_rejects_mismatch(tmp_path, field, value, step):
    binary, receipt, payload = receipt_for(tmp_path)
    target = payload if field in {"source_commit", "schema_version"} else payload["sidecar"]
    target[field] = value
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match=f"^{step}$"):
        verify_attestation(binary, receipt, COMMIT)


def test_artifact_modified_after_receipt_is_rejected(tmp_path):
    binary, receipt, _ = receipt_for(tmp_path)
    original = binary.read_bytes()
    binary.write_bytes(b"X" + original[1:])
    with pytest.raises(RuntimeError, match="^attestation_hash$"):
        verify_attestation(binary, receipt, COMMIT)

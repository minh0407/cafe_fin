"""Synthetic NSIS listings/receipts and real Python pipe tests; no installer runs."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/packaging/verify_nsis_payload.py"
SPEC = importlib.util.spec_from_file_location("nsis_payload", SOURCE)
proof = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proof)
SHA = "a" * 40
PAYLOAD = b"synthetic sidecar\x00\xff\xfe; never an executable"


def listing(member="$INSTDIR\\cafe-fin-sidecar.exe", extra="", size=len(PAYLOAD)):
    return (
        "7-Zip synthetic\n\nPath = synthetic-setup.exe\nType = Nsis\nSolid = +\n"
        "\n----------\n"
        f"Path = {member}\nSize = {size}\nAttributes = A\n{extra}\n"
    ).encode()


def refresh_receipt(root):
    items = []
    for file in sorted(root.rglob("*")):
        if file.is_file() and file.name not in ("build-receipt.json", "SHA256SUMS.txt"):
            items.append({"file": file.relative_to(root).as_posix(), **proof.hash_file(file)})
    (root / "build-receipt.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_commit": SHA,
                "target": "x86_64-pc-windows-msvc",
                "status": "CANDIDATE_FILES_PRESENT",
                "installer_present": True,
                "files": items,
            }
        )
    )
    (root / "SHA256SUMS.txt").write_text(
        "".join(f"{item['sha256']}  {item['file']}\n" for item in items)
        + f"{proof.hash_file(root / 'build-receipt.json')['sha256']}  build-receipt.json\n"
    )


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "candidate"
    for name, body in {
        proof.SIDECAR: PAYLOAD,
        proof.INVENTORY: json.dumps(
            {
                "exe_bytes": len(PAYLOAD),
                "exe_sha256": hashlib.sha256(PAYLOAD).hexdigest(),
            }
        ).encode(),
        "installer/synthetic-setup.exe": b"synthetic installer; never an executable",
        f"source/cafe-fin-{SHA}.zip": b"synthetic source archive",
    }.items():
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(body)
    refresh_receipt(root)
    return root


def tool_responses(monkeypatch, *, payload=PAYLOAD, archive_listing=None, mutate=None):
    calls = []

    def fake(command, *, limit, timeout, stream_hash=False):
        calls.append(command)
        if command[1] == "i":
            return b"\n7-Zip 26.06 (synthetic test substitute)\n"
        if command[1] == "l":
            assert command[2:5] == ["-slt", "-sccUTF-8", "--"]
            return archive_listing if archive_listing is not None else listing()
        assert command[1:5] == ["x", "-so", "-spd", "--"]
        assert command[-1] == "$INSTDIR\\cafe-fin-sidecar.exe"
        assert stream_hash and limit == len(PAYLOAD)
        if mutate:
            mutate()
        return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    monkeypatch.setattr(proof, "run_tool", fake)
    return calls


def test_matching_payload_binds_installer_receipts_source_and_never_promotes_gui(
    candidate,
    tmp_path,
    monkeypatch,
):
    calls = tool_responses(monkeypatch)
    before = {str(p): p.read_bytes() for p in candidate.rglob("*") if p.is_file()}
    output = tmp_path / "proof.json"
    result = proof.verify(candidate, SHA, Path(sys.executable), output)
    assert result["status"] == "PAYLOAD_MATCH_ONLY"
    assert result["source_commit"] == SHA
    assert result["payload"]["sha256"] == result["sidecar"]["sha256"]
    assert (
        result["installer"]["sha256"]
        == proof.hash_file(candidate / "installer/synthetic-setup.exe")["sha256"]
    )
    assert result["installer_execution"] == result["gui_acceptance"] == "NOT_RUN"
    assert not result["release_clearance"]
    assert len(calls) == 3
    assert {str(p): p.read_bytes() for p in candidate.rglob("*") if p.is_file()} == before
    assert json.loads(output.read_text())["status"] == "PAYLOAD_MATCH_ONLY"


@pytest.mark.parametrize(
    "change", ["source", "status", "checksum", "inventory", "missing-source", "second-installer"]
)
def test_inconsistent_candidate_refused_before_starting_tool(
    candidate, tmp_path, monkeypatch, change
):
    if change == "source":
        source = "b" * 40
    else:
        source = SHA
    if change == "status":
        path = candidate / "build-receipt.json"
        receipt = json.loads(path.read_text())
        receipt["status"] = "BLOCKED_INSTALLER_MISSING"
        path.write_text(json.dumps(receipt))
    elif change == "checksum":
        (candidate / proof.SIDECAR).write_bytes(b"stale")
    elif change == "inventory":
        (candidate / proof.INVENTORY).write_text(
            json.dumps({"exe_bytes": 0, "exe_sha256": "0" * 64})
        )
        refresh_receipt(candidate)
    elif change == "missing-source":
        (candidate / f"source/cafe-fin-{SHA}.zip").unlink()
        refresh_receipt(candidate)
    elif change == "second-installer":
        (candidate / "installer/old.exe").write_bytes(b"synthetic old installer")
        refresh_receipt(candidate)
    calls = tool_responses(monkeypatch)
    with pytest.raises(ValueError):
        proof.verify(candidate, source, Path(sys.executable), tmp_path / "not-created.json")
    assert calls == []
    assert not (tmp_path / "not-created.json").exists()


@pytest.mark.parametrize(
    "member",
    [
        "../cafe-fin-sidecar.exe",
        "/cafe-fin-sidecar.exe",
        "C:\\cafe-fin-sidecar.exe",
        "$INSTDIR\\..\\cafe-fin-sidecar.exe",
        "bad*\\cafe-fin-sidecar.exe",
        "$INSTDIR\\cafe-fin-sidecar.exe ",
    ],
)
def test_unsafe_member_refused(member):
    with pytest.raises(ValueError, match="unsafe"):
        proof.select_member(listing(member), len(PAYLOAD))


@pytest.mark.parametrize(
    "extra",
    [
        "Folder = +\n",
        "Symbolic Link = elsewhere\n",
        "Hard Link = elsewhere\n",
        "Anti = +\n",
        "Encrypted = +\n",
        "Attributes = D\n",
        "Size = 0\n",
    ],
)
def test_nonregular_or_ambiguous_metadata_refused(extra):
    with pytest.raises(ValueError):
        proof.select_member(listing(extra=extra), len(PAYLOAD))


def test_zero_duplicate_and_wrong_type_members_refused():
    duplicate = listing() + listing("cafe-fin-sidecar.exe").split(b"----------\n")[1]
    for value in (
        listing("other.exe"),
        duplicate,
        listing().replace(b"Type = Nsis", b"Type = zip"),
    ):
        with pytest.raises(ValueError):
            proof.select_member(value, len(PAYLOAD))


def test_streamed_payload_hash_mismatch_never_writes_proof(candidate, tmp_path, monkeypatch):
    tool_responses(monkeypatch, payload=b"stale sidecar")
    with pytest.raises(ValueError, match="packed sidecar differs"):
        proof.verify(candidate, SHA, Path(sys.executable), tmp_path / "not-created.json")
    assert not (tmp_path / "not-created.json").exists()


def test_changed_installer_during_stream_refused(candidate, tmp_path, monkeypatch):
    def change():
        (candidate / "installer/synthetic-setup.exe").write_bytes(b"changed during stream")

    tool_responses(monkeypatch, mutate=change)
    with pytest.raises(ValueError, match="checksum/size mismatch"):
        proof.verify(candidate, SHA, Path(sys.executable), tmp_path / "not-created.json")
    assert not (tmp_path / "not-created.json").exists()


def test_checksum_list_tampering_and_existing_output_are_refused(candidate, tmp_path, monkeypatch):
    calls = tool_responses(monkeypatch)
    output = tmp_path / "existing.json"
    output.write_text("keep")
    with pytest.raises(ValueError, match="output must be new"):
        proof.verify(candidate, SHA, Path(sys.executable), output)
    assert output.read_text() == "keep"
    with pytest.raises(ValueError, match="outside the candidate"):
        proof.verify(candidate, SHA, Path(sys.executable), candidate / "new-proof.json")
    with (candidate / "SHA256SUMS.txt").open("a") as stream:
        stream.write("0" * 64 + "  unlisted\n")
    with pytest.raises(ValueError, match="checksum list"):
        proof.verify(candidate, SHA, Path(sys.executable), tmp_path / "new.json")
    assert calls == []


def test_receipt_path_escape_and_case_duplicate_are_refused(candidate):
    path = candidate / "build-receipt.json"
    receipt = json.loads(path.read_text())
    original = list(receipt["files"])
    receipt["files"].append({"file": "../outside", "bytes": 0, "sha256": "0" * 64})
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="unsafe"):
        proof.candidate_files(candidate, SHA)
    receipt["files"] = original + [original[0] | {"file": original[0]["file"].upper()}]
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="duplicate"):
        proof.candidate_files(candidate, SHA)


def test_directory_attributes_and_wrong_listing_size_are_refused():
    for value in (
        listing().replace(b"Attributes = A", b"Attributes = D"),
        listing(size=len(PAYLOAD) + 1),
    ):
        with pytest.raises(ValueError, match="regular file of expected size"):
            proof.select_member(value, len(PAYLOAD))


def test_real_python_process_streams_binary_and_drains_stderr_without_shell(monkeypatch):
    original = subprocess.Popen
    seen = []

    def record(*args, **kwargs):
        seen.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(proof.subprocess, "Popen", record)
    data = b"\x00\xff\xfe\r\n" * 20000
    result = proof.run_tool(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.buffer.write(b'e'*32000); "
            "sys.stderr.flush(); sys.stdout.buffer.write(b'\\x00\\xff\\xfe\\r\\n'*20000)",
        ],
        limit=len(data),
        timeout=10,
        stream_hash=True,
    )
    assert result == {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    assert seen[0]["shell"] is False and seen[0]["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize(
    "code,limit,exception",
    [
        ("import time; time.sleep(5)", 100, TimeoutError),
        ("import sys; sys.stdout.buffer.write(b'x'*100000)", 100, ValueError),
        ("import sys; sys.stderr.buffer.write(b'x'*100000)", 100, ValueError),
        ("import sys; sys.exit(2)", 100, ValueError),
    ],
)
def test_real_python_tool_timeout_bounds_and_failure_are_refused(code, limit, exception):
    with pytest.raises(exception):
        proof.run_tool([sys.executable, "-c", code], limit=limit, timeout=0.5)

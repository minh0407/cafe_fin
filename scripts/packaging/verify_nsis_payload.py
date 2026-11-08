"""Hash one NSIS sidecar through 7-Zip stdout; never install or write its payload.

Run on a host that already permits 7-Zip. This is payload identity evidence only,
not installer execution, signature, license or clean-Windows acceptance.
"""

import argparse
import hashlib
import json
import re
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

SIDECAR = "binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe"
INVENTORY = "notices/sidecar-native-inventory.json"
MEMBER_NAME = "cafe-fin-sidecar.exe"
MAX_FILE = 1024 * 1024 * 1024
MAX_TOTAL = 2 * MAX_FILE
MAX_METADATA = 2 * 1024 * 1024
MAX_LISTING = 4 * 1024 * 1024
MAX_STDERR = 64 * 1024


def safe_name(name):
    if not isinstance(name, str) or not name or len(name) > 4096:
        raise ValueError("invalid member/file path")
    normalized = name.replace("\\", "/")
    parts = normalized.split("/")
    if (
        normalized.startswith("/")
        or any(part in ("", ".", "..") or part != part.rstrip(" .") for part in parts)
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or any(char in name for char in ':*?[]"<>|')
    ):
        raise ValueError("unsafe member/file path")
    return normalized


def regular_file(root, name):
    normalized = safe_name(name)
    if normalized != name:
        raise ValueError("receipt paths must use forward slashes")
    path = root.joinpath(*PurePosixPath(normalized).parts)
    for item in (path, *path.parents):
        if item.is_symlink() or item.is_junction():
            raise ValueError("linked candidate files are refused")
        if item == root:
            break
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError("candidate file must be regular and contained")
    return path


def hash_file(path, maximum=MAX_FILE):
    size = 0
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > maximum:
                raise ValueError("candidate file exceeds size bound")
            digest.update(chunk)
    return {"bytes": size, "sha256": digest.hexdigest()}


def read_json(path):
    if path.stat().st_size > MAX_METADATA:
        raise ValueError("candidate metadata exceeds size bound")
    return json.loads(path.read_text(encoding="utf-8"))


def candidate_files(root, source):
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("expected full source SHA required")
    receipt_path = regular_file(root, "build-receipt.json")
    receipt = read_json(receipt_path)
    if (
        receipt.get("source_commit") != source
        or receipt.get("status") != "CANDIDATE_FILES_PRESENT"
        or receipt.get("installer_present") is not True
        or receipt.get("target") != "x86_64-pc-windows-msvc"
    ):
        raise ValueError("candidate receipt source/status/target mismatch")
    entries = receipt.get("files")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 128:
        raise ValueError("invalid candidate file inventory")
    expected = {}
    folded = set()
    total = 0
    for item in entries:
        name = item["file"]
        if name.casefold() in folded or name in ("build-receipt.json", "SHA256SUMS.txt"):
            raise ValueError("duplicate or reserved candidate file")
        folded.add(name.casefold())
        path = regular_file(root, name)
        if (
            type(item["bytes"]) is not int
            or not 0 <= item["bytes"] <= MAX_FILE
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        ):
            raise ValueError("invalid candidate file digest/size")
        total += item["bytes"]
        if total > MAX_TOTAL:
            raise ValueError("candidate collection exceeds size bound")
        facts = {"bytes": item["bytes"], "sha256": item["sha256"]}
        if hash_file(path) != facts:
            raise ValueError("candidate file checksum/size mismatch")
        expected[name] = facts
    installers = [name for name in expected if name.startswith("installer/")]
    if len(installers) != 1 or not installers[0].lower().endswith(".exe"):
        raise ValueError("exactly one receipted installer required")
    for name in (SIDECAR, INVENTORY, f"source/cafe-fin-{source}.zip"):
        if name not in expected:
            raise ValueError("candidate lacks required source/sidecar/inventory")
    sums_path = regular_file(root, "SHA256SUMS.txt")
    if sums_path.stat().st_size > MAX_METADATA:
        raise ValueError("checksum list exceeds size bound")
    sums = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or name in sums:
            raise ValueError("invalid or duplicate checksum entry")
        sums[name] = digest
    required_sums = {name: facts["sha256"] for name, facts in expected.items()}
    required_sums["build-receipt.json"] = hash_file(receipt_path)["sha256"]
    if sums != required_sums:
        raise ValueError("checksum list does not match receipt")
    inventory = read_json(regular_file(root, INVENTORY))
    if expected[SIDECAR] != {
        "bytes": inventory.get("exe_bytes"),
        "sha256": inventory.get("exe_sha256", "").lower(),
    }:
        raise ValueError("sidecar inventory does not match receipted binary")
    return (
        installers[0],
        expected,
        {
            "build_receipt_sha256": required_sums["build-receipt.json"],
            "checksum_list_sha256": hash_file(sums_path)["sha256"],
        },
    )


def run_tool(command, *, limit, timeout, stream_hash=False):
    """Drain both pipes with bounds/deadline; payload bytes never become text/files."""
    if not 0 < timeout <= 1200:
        raise ValueError("tool timeout must be greater than zero and at most 1200 seconds")
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    chunks, failures = [], []
    digest = hashlib.sha256()
    counts = [0, 0]

    def drain(pipe, index, bound):
        try:
            while chunk := pipe.read(65536):
                counts[index] += len(chunk)
                if counts[index] > bound:
                    raise ValueError("tool output exceeds size bound")
                if index == 0:
                    if stream_hash:
                        digest.update(chunk)
                    else:
                        chunks.append(chunk)
        except Exception as error:
            failures.append(error)
            if process.poll() is None:
                process.kill()

    readers = [
        threading.Thread(target=drain, args=(process.stdout, 0, limit), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, 1, MAX_STDERR), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
        for reader in readers:
            reader.join(timeout=max(0, deadline - time.monotonic()))
        if any(reader.is_alive() for reader in readers):
            raise TimeoutError("tool pipe deadline exceeded")
        if failures:
            raise ValueError("tool output exceeds bound or cannot be read") from failures[0]
        if process.returncode != 0:
            raise ValueError(f"7-Zip command failed (exit {process.returncode})")
        if stream_hash:
            return {"bytes": counts[0], "sha256": digest.hexdigest()}
        return b"".join(chunks)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("tool execution deadline exceeded") from error
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for reader in readers:
            reader.join(timeout=0.1)
        if not any(reader.is_alive() for reader in readers):
            process.stdout.close()
            process.stderr.close()


def select_member(listing, expected_size):
    text = listing.decode("utf-8-sig", errors="strict").replace("\r\n", "\n")
    header, separator, body = text.partition("\n----------\n")
    if not separator or not re.search(r"(?m)^Type = Nsis$", header):
        raise ValueError("7-Zip did not identify an NSIS archive")
    matches = []
    for block in body.split("\n\n"):
        fields = {}
        for line in block.strip().splitlines():
            key, mark, value = line.partition(" = ")
            if not mark or key in fields:
                raise ValueError("malformed or duplicate NSIS listing field")
            fields[key] = value
        name = fields.get("Path", "")
        if name.replace("\\", "/").rsplit("/", 1)[-1].rstrip(" .").casefold() != MEMBER_NAME:
            continue
        safe_name(name)
        if (
            fields.get("Folder", "-") != "-"
            or fields.get("Anti", "-") != "-"
            or fields.get("Encrypted", "-") != "-"
            or any(key in fields for key in ("Symbolic Link", "Hard Link"))
            or any(char in fields.get("Attributes", "").upper() for char in "DL")
            or fields.get("Size") != str(expected_size)
        ):
            raise ValueError("NSIS sidecar member must be a regular file of expected size")
        matches.append(name)
    if len(matches) != 1:
        raise ValueError("exactly one unique NSIS sidecar member required")
    return matches[0]


def verify(candidate, source, sevenzip, output, timeout=120):
    if candidate.is_symlink() or candidate.is_junction():
        raise ValueError("linked candidate root refused")
    root = candidate.resolve(strict=True)
    if output.exists() or output.resolve().is_relative_to(root):
        raise ValueError("proof output must be new and outside the candidate collection")
    if sevenzip.is_symlink() or sevenzip.is_junction():
        raise ValueError("linked 7-Zip tool refused")
    tool = sevenzip.resolve(strict=True)
    if not tool.is_file():
        raise ValueError("explicit existing regular 7-Zip tool required")
    tool_hash = hash_file(tool)
    installer, files, receipts = candidate_files(root, source)
    version_output = run_tool([str(tool), "i", "-sccUTF-8"], limit=MAX_LISTING, timeout=timeout)
    versions = [
        line
        for line in version_output.decode("utf-8").splitlines()
        if line.startswith("7-Zip ") and len(line) <= 512
    ]
    if len(versions) != 1:
        raise ValueError("cannot identify 7-Zip tool version")
    listing = run_tool(
        [str(tool), "l", "-slt", "-sccUTF-8", "--", str(root / installer)],
        limit=MAX_LISTING,
        timeout=timeout,
    )
    member = select_member(listing, files[SIDECAR]["bytes"])
    payload = run_tool(
        [str(tool), "x", "-so", "-spd", "--", str(root / installer), member],
        limit=files[SIDECAR]["bytes"],
        timeout=timeout,
        stream_hash=True,
    )
    if payload != files[SIDECAR]:
        raise ValueError("packed sidecar differs from receipted binary and inventory")
    if candidate_files(root, source) != (installer, files, receipts):
        raise ValueError("candidate changed during verification")
    if hash_file(tool) != tool_hash:
        raise ValueError("7-Zip tool changed during verification")
    proof = {
        "schema_version": 1,
        "status": "PAYLOAD_MATCH_ONLY",
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "source_commit": source,
        "installer": {"file": installer, **files[installer]},
        "payload": {"member": member, **payload},
        "sidecar": {"file": SIDECAR, **files[SIDECAR]},
        "inventory": {"file": INVENTORY, **files[INVENTORY]},
        "application_source": {
            "file": f"source/cafe-fin-{source}.zip",
            **files[f"source/cafe-fin-{source}.zip"],
        },
        "receipts": receipts,
        "sevenzip": {"version": versions[0], **tool_hash},
        "method": "7-Zip NSIS member stdout SHA256; no payload written or executed",
        "installer_execution": "NOT_RUN",
        "gui_acceptance": "NOT_RUN",
        "signature_verification": "NOT_RUN",
        "release_clearance": False,
    }
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(proof, indent=2) + "\n")
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument(
        "--source", required=True, help="Expected reviewed/CI head SHA, 40 hex digits"
    )
    parser.add_argument("--sevenzip", required=True, type=Path, help="Already permitted 7z.exe/7zz")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args()
    result = verify(args.candidate, args.source, args.sevenzip, args.output, args.timeout_seconds)
    print(result["status"])


if __name__ == "__main__":
    main()

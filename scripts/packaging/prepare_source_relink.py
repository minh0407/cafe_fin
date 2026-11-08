"""Fetch pinned audited materials and safely unpack a new offline relink workbench.

No downloaded code is executed. Historical native provenance remains inference;
the manifest never equates material availability with a tested relink or clearance.
"""

import argparse
import hashlib
import json
import shutil
import tarfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

HOSTS = {
    "codeload.github.com",
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "files.pythonhosted.org",
    "raw.githubusercontent.com",
}


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https" or urlparse(newurl).hostname not in HOSTS:
            raise ValueError("unapproved material redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def sha(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            result.update(chunk)
    return result.hexdigest()


def fetch(material, target):
    url = urlparse(material["url"])
    if url.scheme != "https" or url.hostname not in HOSTS:
        raise ValueError("unapproved material source")
    if target.exists():
        if target.stat().st_size != material["bytes"] or sha(target) != material["sha256"]:
            raise ValueError("existing material does not match pin")
        return
    temporary = target.with_suffix(target.suffix + ".part")
    opener = urllib.request.build_opener(SafeRedirect())
    with opener.open(material["url"], timeout=30) as response, temporary.open("xb") as stream:
        remaining = material["bytes"]
        while chunk := response.read(min(65536, remaining + 1)):
            remaining -= len(chunk)
            if remaining < 0:
                raise ValueError("material exceeds pinned length")
            stream.write(chunk)
    if remaining != 0 or sha(temporary) != material["sha256"]:
        raise ValueError("downloaded material differs from pin")
    temporary.replace(target)


def unpack(archive, output):
    """Single-root upstream tar, regular files/directories only, no links/devices."""
    if output.is_symlink() or (output.exists() and any(output.iterdir())):
        raise ValueError("source output must be new")
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        roots = {PurePosixPath(member.name).parts[0] for member in members}
        if len(roots) != 1:
            raise ValueError("source archive must have one root")
        total = 0
        for member in members:
            parts = PurePosixPath(member.name).parts
            if (
                member.name.startswith(("/", "\\"))
                or ".." in parts
                or "\\" in member.name
                or ":" in member.name
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("unsafe or linked source member")
            total += member.size
            if total > 256 * 1024 * 1024:
                raise ValueError("source expansion limit")
        output.mkdir(parents=True, exist_ok=True)
        for member in members:
            parts = PurePosixPath(member.name).parts[1:]
            if not parts:
                continue
            destination = output.joinpath(*parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as reader, destination.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)


def prepare(catalog, output):
    if output.exists():
        raise ValueError("material workbench output must be new")
    output.mkdir(parents=True)
    (output / "archives").mkdir()
    receipt = {
        "schema_version": 1,
        "prepared_at_utc": datetime.now(UTC).isoformat(),
        "status": "MATERIALS_FETCH_IN_PROGRESS",
        "relink_execution": "NOT_RUN",
        "wheel_native_provenance": "HISTORICAL_INFERENCE_NOT_ATTESTATION",
        "distribution_clearance": False,
        "materials": [],
    }
    manifest = output / "materials-receipt.json"
    for material in catalog["materials"]:
        filename = material["file"]
        if Path(filename).name != filename:
            raise ValueError("material filename must be a leaf")
        target = output / "archives" / filename
        fetch(material, target)
        if material.get("extract_to"):
            relative = PurePosixPath(material["extract_to"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("invalid source layout")
            unpack(target, output.joinpath(*relative.parts))
        receipt["materials"].append(material | {"verified_sha256": sha(target)})
        manifest.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print("Verified", material["file"], flush=True)
    receipt["status"] = "PINNED_MATERIALS_PRESENT_RELINK_NOT_RUN"
    manifest.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(Path(__file__).with_name("materials.lock.json"), output / "materials.lock.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    catalog = json.loads(Path(__file__).with_name("materials.lock.json").read_text())
    prepare(catalog, args.output)


if __name__ == "__main__":
    main()

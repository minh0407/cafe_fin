"""Developer integrity check/ZIP packaging only; never run binaries or promote acceptance."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath


def sha(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def verify(root, zip_output=None):
    root = root.resolve()
    manifest_path = root / "kit-manifest.json"
    if manifest_path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("manifest too large")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = set()
    total = 0
    for item in manifest["files"]:
        name = item["file"]
        relative = PurePosixPath(name)
        path = root.joinpath(*relative.parts)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in name
            or ":" in name
            or name.casefold() in names
            or path.is_symlink()
            or path.is_junction()
            or not path.resolve().is_relative_to(root)
        ):
            raise ValueError("invalid or duplicate kit path")
        names.add(name.casefold())
        if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise ValueError("kit file differs from manifest")
        total += item["bytes"]
    actual = {
        path.relative_to(root).as_posix().casefold() for path in root.rglob("*") if path.is_file()
    }
    if actual != names | {"kit-manifest.json", "sha256sums.txt"}:
        raise ValueError("unlisted or missing kit file")
    sums = (root / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    expected = {item["file"]: item["sha256"] for item in manifest["files"]}
    expected["kit-manifest.json"] = sha(manifest_path)
    parsed = {}
    for line in sums:
        digest, separator, name = line.partition("  ")
        if not separator or name in parsed:
            raise ValueError("invalid checksum list")
        parsed[name] = digest
    if parsed != expected:
        raise ValueError("checksum list differs from manifest")
    result = {
        "status": "FILE_INTEGRITY_PASS_ONLY",
        "files": len(manifest["files"]),
        "payload_bytes": total,
        "source_commit": manifest["source_commit"],
        "kit_status": manifest["status"],
        "runtime_acceptance": "NOT_RUN",
    }
    if zip_output:
        with zipfile.ZipFile(zip_output, "x") as output:
            for name in sorted(expected.keys() | {"SHA256SUMS.txt"}):
                compress = (
                    zipfile.ZIP_STORED
                    if Path(name).suffix.lower()
                    in {".exe", ".zip", ".gz", ".whl", ".png", ".xlsx", ".xlsm"}
                    else zipfile.ZIP_DEFLATED
                )
                output.write(root / name, arcname=name, compress_type=compress)
        with zipfile.ZipFile(zip_output) as saved:
            if saved.testzip() is not None:
                raise ValueError("ZIP readback CRC failed")
        result["zip"] = {
            "file": zip_output.name,
            "bytes": zip_output.stat().st_size,
            "sha256": sha(zip_output),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--zip-output", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.kit, args.zip_output), indent=2))


if __name__ == "__main__":
    main()

"""Read-only comparison of a trusted PyInstaller sidecar with a Git revision.

This verifies application Python code/data, not the third-party runtime, native
bootloader, installer provenance or reproducibility. Never executes the binary.
Run using the exact Python bytecode version used by the packaging lane.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import marshal
import subprocess
import types
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def normalized(value):
    """Retain every semantic/debug code field except rewritten co_filename."""
    if isinstance(value, types.CodeType):
        fields = (
            "co_argcount",
            "co_posonlyargcount",
            "co_kwonlyargcount",
            "co_nlocals",
            "co_stacksize",
            "co_flags",
            "co_code",
            "co_consts",
            "co_names",
            "co_varnames",
            "co_name",
            "co_qualname",
            "co_firstlineno",
            "co_linetable",
            "co_exceptiontable",
            "co_freevars",
            "co_cellvars",
        )
        return {"code": {field: normalized(getattr(value, field)) for field in fields}}
    if value is None or isinstance(value, (str, bool, int)):
        return [type(value).__name__, value]
    if value is Ellipsis:
        return ["ellipsis"]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, float):
        return ["float", value.hex()]
    if isinstance(value, complex):
        return ["complex", value.real.hex(), value.imag.hex()]
    if isinstance(value, tuple):
        return ["tuple", [normalized(item) for item in value]]
    if isinstance(value, frozenset):
        return ["frozenset", sorted((normalized(item) for item in value), key=canonical)]
    raise ValueError(f"Unsupported code constant: {type(value).__name__}")


def code_digest(code):
    if not isinstance(code, types.CodeType):
        raise ValueError("Expected module code object")
    return hashlib.sha256(canonical(normalized(code))).hexdigest()


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout


def expected_application(repo, revision):
    commit = git(repo, "rev-parse", "--verify", revision + "^{commit}").decode().strip()
    paths = (
        git(repo, "ls-tree", "-rz", "--name-only", commit, "--", "backend/cafe_fin")
        .decode()
        .split("\0")
    )
    modules, data = {}, {}
    for path in filter(None, paths):
        relative = path.removeprefix("backend/")
        if path.endswith(".py"):
            module = relative[:-3].replace("/", ".")
            module = module.removesuffix(".__init__")
            source = git(repo, "show", f"{commit}:{path}")
            modules[module] = code_digest(
                compile(source, relative, "exec", dont_inherit=True, optimize=0)
            )
        elif relative.startswith("cafe_fin/core/assets/") or (
            relative.startswith("cafe_fin/contracts/templates/") and relative.endswith(".json")
        ):
            data[relative] = hashlib.sha256(git(repo, "show", f"{commit}:{path}")).hexdigest()
    if "cafe_fin.__main__" not in modules or not data:
        raise ValueError("Revision lacks the expected application layout")
    return commit, modules, data


def compare_maps(expected, actual):
    return {
        "missing": sorted(expected.keys() - actual.keys()),
        "unexpected": sorted(actual.keys() - expected.keys()),
        "different": sorted(
            key for key in expected.keys() & actual.keys() if expected[key] != actual[key]
        ),
    }


def verify(binary, repo, revision, expected_sha256):
    binary = Path(binary).resolve(strict=True)
    with binary.open("rb") as stream:
        binary_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    if binary_sha != expected_sha256.lower():
        raise ValueError("Executable SHA-256 differs from the supplied trusted receipt")
    commit, modules, data = expected_application(repo, revision)
    archive = CArchiveReader(str(binary))
    pyz_names = [name for name, entry in archive.toc.items() if entry[-1] == "z"]
    if len(pyz_names) != 1:
        raise ValueError("Expected exactly one PYZ archive")
    raw_pyz = archive.extract(pyz_names[0])
    if raw_pyz[:8] != b"PYZ\0" + importlib.util.MAGIC_NUMBER:
        raise ValueError("PYZ bytecode magic differs from this verifier Python")
    pyz = archive.open_embedded_archive(pyz_names[0])
    actual_modules = {
        name: code_digest(pyz.extract(name))
        for name in pyz.toc
        if name == "cafe_fin" or name.startswith("cafe_fin.")
    }
    actual_data = {}
    for name in archive.toc:
        relative = name.replace("\\", "/")
        if relative.startswith("cafe_fin/core/assets/") or (
            relative.startswith("cafe_fin/contracts/templates/") and relative.endswith(".json")
        ):
            actual_data[relative] = hashlib.sha256(archive.extract(name)).hexdigest()
    module_diff = compare_maps(modules, actual_modules)
    data_diff = compare_maps(data, actual_data)
    entry_names = [
        name
        for name, entry in archive.toc.items()
        if entry[-1] == "s" and name in ("__main__", "__main__.py")
    ]
    entry_match = (
        len(entry_names) == 1
        and code_digest(marshal.loads(archive.extract(entry_names[0])))
        == modules["cafe_fin.__main__"]
    )
    passed = entry_match and not any(module_diff.values()) and not any(data_diff.values())
    return {
        "status": "PASS" if passed else "FAIL",
        "commit": commit,
        "binary": str(binary),
        "binary_sha256": binary_sha,
        "bytecode_magic": importlib.util.MAGIC_NUMBER.hex(),
        "module_count": len(modules),
        "data_count": len(data),
        "expected_module_digests": modules,
        "expected_data_digests": data,
        "module_diff": module_diff,
        "data_diff": data_diff,
        "entrypoint_match": entry_match,
        "scope": "Application Python code and packaged application data only; filename normalization only",
        "limitations": "No native runtime/dependency/installer provenance or reproducible-build claim; binary never executed",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be a new evidence file")
    output = args.output.resolve()
    if not args.output.is_absolute() or not output.parent.is_dir():
        parser.error("Output needs an absolute path and an existing external parent")
    if any((parent / ".git").exists() for parent in (output.parent, *output.parents)):
        parser.error("Generated evidence must remain outside Git repositories")
    result = verify(args.binary, args.repo, args.revision, args.sha256)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

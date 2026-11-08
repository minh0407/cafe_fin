"""Tiny synthetic archives; no native executable build or execution."""

import hashlib
import subprocess

import pytest
from PyInstaller.archive.writers import CArchiveWriter, ZlibArchiveWriter

from .artifact_identity import code_digest, verify


def run_git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, timeout=20)


@pytest.fixture
def application(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    sources = {
        "cafe_fin": '"""Synthetic package."""\n',
        "cafe_fin.__main__": "def main():\n    return 42\n",
        "cafe_fin.example": "def amount():\n    return '100.50'\n",
    }
    paths = {}
    for name, source in sources.items():
        relative = name.replace(".", "/") + ".py"
        if name == "cafe_fin":
            relative = "cafe_fin/__init__.py"
        path = repo / "backend" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        paths[name] = path
    data_name = "cafe_fin/contracts/templates/purchase.json"
    data = repo / "backend" / data_name
    data.parent.mkdir(parents=True)
    data.write_text('{"synthetic":true}', encoding="utf-8")
    run_git(repo, "init")
    run_git(repo, "add", "backend")
    run_git(
        repo,
        "-c",
        "user.name=Synthetic Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "Synthetic fixture",
    )

    def archive(
        *,
        changed=None,
        omitted=None,
        data_content=None,
        main_content=None,
        wrong_magic=False,
        extra_module=False,
    ):
        entries, codes = [], {}
        for name, path in paths.items():
            if name == omitted:
                continue
            source = changed if name == "cafe_fin.example" and changed else path.read_bytes()
            codes[name] = compile(
                source, "different-build-machine-path.py", "exec", dont_inherit=True, optimize=0
            )
            entries.append((name, str(path), "PYMODULE"))
        if extra_module:
            codes["cafe_fin.untracked"] = compile("value = 1", "untracked.py", "exec")
            entries.append(("cafe_fin.untracked", "untracked.py", "PYMODULE"))
        pyz = tmp_path / "PYZ.pyz"
        ZlibArchiveWriter(str(pyz), entries, codes)
        if wrong_magic:
            content = pyz.read_bytes()
            pyz.write_bytes(content[:4] + b"BAD!" + content[8:])
        main = paths["cafe_fin.__main__"]
        if main_content:
            main = tmp_path / "main.py"
            main.write_text(main_content, encoding="utf-8")
        packaged_data = data
        if data_content:
            packaged_data = tmp_path / "purchase.json"
            packaged_data.write_text(data_content, encoding="utf-8")
        output = tmp_path / "synthetic.pkg"
        CArchiveWriter(
            str(output),
            [
                ("PYZ.pyz", str(pyz), False, "z"),
                ("__main__", str(main), True, "s"),
                (data_name, str(packaged_data), True, "x"),
            ],
            "python312.dll",
        )
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        return output, digest

    return repo, archive


def test_matches_all_app_code_data_and_entrypoint(application):
    repo, archive = application
    path, digest = archive()
    result = verify(path, repo, "HEAD", digest)
    assert result["status"] == "PASS"
    assert result["module_count"] == 3
    assert result["data_count"] == 1
    assert result["entrypoint_match"]


@pytest.mark.parametrize(
    "change,section",
    [
        ({"changed": "def amount():\n    return '100.51'\n"}, "module_diff"),
        ({"omitted": "cafe_fin.example"}, "module_diff"),
        ({"data_content": '{"synthetic":false}'}, "data_diff"),
    ],
)
def test_rejects_changed_or_missing_application(application, change, section):
    repo, archive = application
    path, digest = archive(**change)
    result = verify(path, repo, "HEAD", digest)
    assert result["status"] == "FAIL"
    assert any(result[section].values())


def test_separate_entrypoint_must_match(application):
    repo, archive = application
    path, digest = archive(main_content="def main():\n    return 43\n")
    result = verify(path, repo, "HEAD", digest)
    assert result["status"] == "FAIL"
    assert not result["entrypoint_match"]


def test_untracked_application_code_is_rejected(application):
    repo, archive = application
    path, digest = archive(extra_module=True)
    result = verify(path, repo, "HEAD", digest)
    assert result["status"] == "FAIL"
    assert result["module_diff"]["unexpected"] == ["cafe_fin.untracked"]


def test_wrong_python_magic_is_rejected_before_unmarshal(application):
    repo, archive = application
    path, digest = archive(wrong_magic=True)
    with pytest.raises(ValueError, match="bytecode magic"):
        verify(path, repo, "HEAD", digest)


def test_hash_guard_runs_before_archive_parse(application):
    repo, archive = application
    path, _ = archive()
    path.write_bytes(b"not an archive")
    with pytest.raises(ValueError, match="SHA-256"):
        verify(path, repo, "HEAD", "0" * 64)


def test_filename_only_normalization_keeps_semantics_and_line_numbers():
    source = "def value():\n    return frozenset({1, 2, 3})\n"
    assert code_digest(compile(source, "a.py", "exec")) == code_digest(
        compile(source, "b.py", "exec")
    )
    assert code_digest(compile(source, "a.py", "exec")) != code_digest(
        compile("\n" + source, "a.py", "exec")
    )

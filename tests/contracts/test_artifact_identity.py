"""Tiny synthetic archives; no native executable build or execution."""

import hashlib
import json
import subprocess

import pytest
from PyInstaller.archive.writers import CArchiveWriter, ZlibArchiveWriter

from .artifact_identity import code_digest, exact_windows_checkout_crlf, git, main, verify


def run_git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, timeout=20)


@pytest.fixture
def application(tmp_path, request):
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
    data_name = getattr(request, "param", "cafe_fin/contracts/templates/purchase.json")
    data = repo / "backend" / data_name
    data.parent.mkdir(parents=True)
    data.write_bytes(b'{"synthetic":true,\n"second":1}\n')
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
        if data_content is not None:
            packaged_data = tmp_path / "purchase.json"
            packaged_data.write_bytes(
                data_content.encode("utf-8") if isinstance(data_content, str) else data_content
            )
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
@pytest.mark.parametrize("allow_crlf", [False, True])
def test_rejects_changed_or_missing_application(application, change, section, allow_crlf):
    repo, archive = application
    path, digest = archive(**change)
    result = verify(path, repo, "HEAD", digest, allow_windows_checkout_crlf=allow_crlf)
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


def test_crlf_requires_explicit_opt_in_and_retains_raw_failure_evidence(application):
    repo, archive = application
    name = "cafe_fin/contracts/templates/purchase.json"
    original = git(repo, "show", f"HEAD:backend/{name}")
    converted = original.replace(b"\n", b"\r\n")
    path, digest = archive(data_content=converted)
    strict = verify(path, repo, "HEAD", digest)
    assert strict["status"] == strict["strict_status"] == "FAIL"
    assert strict["data_policy"] == "strict_raw_bytes"
    assert strict["eol_only_assets"] == []
    result = verify(path, repo, "HEAD", digest, allow_windows_checkout_crlf=True)
    assert result["status"] == "PASS"
    assert result["strict_status"] == "FAIL"
    assert result["data_policy"] == "windows_checkout_crlf_known_utf8_v1"
    assert result["data_diff"] == strict["data_diff"]
    assert not any(result["effective_data_diff"].values())
    assert result["eol_only_assets"] == [
        {
            "path": name,
            "expected_raw_sha256": hashlib.sha256(original).hexdigest(),
            "actual_raw_sha256": hashlib.sha256(converted).hexdigest(),
            "expected_lf_to_crlf_sha256": hashlib.sha256(converted).hexdigest(),
            "expected_bytes": len(original),
            "actual_bytes": len(converted),
            "converted_lf_count": 2,
            "proof": "actual == expected.replace(LF, CRLF); expected has LF only, UTF-8 text without BOM",
        }
    ]


@pytest.mark.parametrize(
    "actual",
    [
        b'{"synthetic":false,\r\n"second":1}\r\n',  # Changed content.
        b'{"synthetic":true,\r\n"second":1}\n',  # Mixed EOL.
        b'{"synthetic":true,\r\n"second":1} \r\n',  # Added whitespace.
        b'\xef\xbb\xbf{"synthetic":true,\r\n"second":1}\r\n',  # Added BOM.
        b'{"synthetic":true,\r\n"second":1}',  # Missing trailing newline.
        b"\xff\x00\r\n",  # Binary content in an allowlisted text path.
    ],
)
def test_opt_in_rejects_any_change_beyond_exact_conversion(application, actual):
    repo, archive = application
    path, digest = archive(data_content=actual)
    result = verify(path, repo, "HEAD", digest, allow_windows_checkout_crlf=True)
    assert result["status"] == "FAIL"
    assert result["eol_only_assets"] == []
    assert result["effective_data_diff"] == result["data_diff"]


@pytest.mark.parametrize(
    "application",
    [
        "cafe_fin/core/assets/NotoSans-Regular.ttf",
        "cafe_fin/core/assets/notices/unlisted-LICENSE.txt",
    ],
    indirect=True,
)
def test_opt_in_does_not_apply_to_fonts_or_unlisted_text(application):
    repo, archive = application
    path, digest = archive(data_content=b'{"synthetic":true,\r\n"second":1}\r\n')
    result = verify(path, repo, "HEAD", digest, allow_windows_checkout_crlf=True)
    assert result["status"] == "FAIL"
    assert result["eol_only_assets"] == []


@pytest.mark.parametrize(
    "source",
    [
        b"line\r\nline\n",
        b"line\r\nline\r\n",
        b"no newline",
        b"\xef\xbb\xbfline\n",
        b"\xff\n",
        b"\x00\n",
        b"\x01\n",
    ],
)
def test_opt_in_rejects_mixed_crlf_bom_or_binary_source(source):
    assert not exact_windows_checkout_crlf(source, source.replace(b"\n", b"\r\n"))


def test_license_formfeeds_and_tabs_are_preserved_exactly():
    source = b"license page\n\f\tsecond page\n"
    assert exact_windows_checkout_crlf(source, b"license page\r\n\f\tsecond page\r\n")
    assert not exact_windows_checkout_crlf(source, b"license page\r\nsecond page\r\n")


def test_cli_default_still_fails_and_explicit_flag_records_policy(
    application, tmp_path, monkeypatch
):
    repo, archive = application
    path, digest = archive(data_content=b'{"synthetic":true,\r\n"second":1}\r\n')
    common = [
        "artifact_identity",
        "--binary",
        str(path),
        "--repo",
        str(repo),
        "--revision",
        "HEAD",
        "--sha256",
        digest,
    ]
    for flag, expected_exit in (([], 1), (["--allow-windows-checkout-crlf"], 0)):
        output = tmp_path / f"receipt-{expected_exit}.json"
        monkeypatch.setattr("sys.argv", [*common, "--output", str(output), *flag])
        assert main() == expected_exit
        receipt = json.loads(output.read_text("utf-8"))
        assert receipt["strict_status"] == "FAIL"
        assert receipt["data_policy"] == (
            "windows_checkout_crlf_known_utf8_v1" if flag else "strict_raw_bytes"
        )

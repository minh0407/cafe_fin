"""Output isolation checks use only synthetic directories under pytest Temp."""

import os
import subprocess
from pathlib import Path

import pytest

from . import runner


@pytest.mark.parametrize(
    "marker,directory",
    [
        (".git", False),  # linked-worktree marker is a file, not a directory
        (".git", True),
        (".cafe-fin-root.json", False),
        (".cafe-fin-root.json", True),
    ],
)
@pytest.mark.parametrize("nested", [False, True])
def test_run_rejects_protected_root_and_descendants_before_mkdir(
    tmp_path,
    monkeypatch,
    marker,
    directory,
    nested,
):
    protected = tmp_path / "synthetic protected root"
    protected.mkdir()
    sentinel = protected / marker
    if directory:
        sentinel.mkdir()
    else:
        sentinel.write_bytes(b"synthetic marker; contents must not be parsed")
    target = protected / "missing" / "nested" if nested else protected
    before = set(tmp_path.rglob("*"))

    def no_creation(*args, **kwargs):
        pytest.fail("A protected output path must fail before mkdir/mkdtemp or sidecar launch.")

    monkeypatch.setattr(Path, "mkdir", no_creation)
    monkeypatch.setattr(runner.tempfile, "mkdtemp", no_creation)
    monkeypatch.setattr(runner.Sidecar, "__enter__", no_creation)
    with pytest.raises(RuntimeError, match="^output_outside_protected_root$"):
        runner.run(target)
    assert set(tmp_path.rglob("*")) == before
    if not directory:
        assert sentinel.read_bytes() == b"synthetic marker; contents must not be parsed"


@pytest.mark.parametrize(
    "raw",
    [
        r"\\synthetic-host.invalid\share\missing",
        "//synthetic-host.invalid/share/missing",
        r"\\?\UNC\synthetic-host.invalid\share\missing",
        r"\\.\synthetic-device\missing",
        r"\??\UNC\synthetic-host.invalid\share\missing",
    ],
)
def test_unc_and_device_paths_rejected_without_filesystem_access(monkeypatch, raw):
    def forbidden(*args, **kwargs):
        pytest.fail("UNC/device paths must be rejected lexically without filesystem access.")

    monkeypatch.setattr(Path, "lstat", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    with pytest.raises(RuntimeError, match="^output_local_path$"):
        runner.run(Path(raw))


@pytest.mark.skipif(os.name != "nt", reason="Real Windows directory junction evidence")
def test_junction_ancestor_rejected_before_resolve_and_without_writes(tmp_path, monkeypatch):
    target = tmp_path / "synthetic destination"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_bytes(b"synthetic original")
    junction = tmp_path / "synthetic junction"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, "Failed to create the synthetic junction for the guard test."
    try:

        def forbidden(*args, **kwargs):
            pytest.fail("Reparse ancestors must be rejected before resolve or mkdir.")

        monkeypatch.setattr(Path, "resolve", forbidden)
        monkeypatch.setattr(Path, "mkdir", forbidden)
        with pytest.raises(RuntimeError, match="^output_no_reparse$"):
            runner.run(junction / "missing" / "nested")
        assert list(target.iterdir()) == [sentinel]
        assert sentinel.read_bytes() == b"synthetic original"
    finally:
        # Remove only this test's junction entry; never recurse into its target.
        junction.rmdir()


def test_safe_new_local_output_accepted_without_creating_it(tmp_path):
    target = tmp_path / "new synthetic output" / "nested"
    assert runner.guarded_output_parent(target) == target.resolve()
    assert not target.exists()

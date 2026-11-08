"""Archive/pin guard checks only; never compile or execute downloaded source."""

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/packaging/prepare_source_relink.py"
SPEC = importlib.util.spec_from_file_location("packaging_materials", SOURCE)
materials = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(materials)


def archive(path, name, kind=tarfile.REGTYPE):
    with tarfile.open(path, "w:gz") as stream:
        item = tarfile.TarInfo(name)
        item.type = kind
        if kind == tarfile.REGTYPE:
            item.size = 9
        if kind == tarfile.SYMTYPE:
            item.linkname = "../../outside"
        stream.addfile(item, io.BytesIO(b"synthetic") if kind == tarfile.REGTYPE else None)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("root/../../escape", tarfile.REGTYPE),
        ("root/C:/escape", tarfile.REGTYPE),
        ("root/link", tarfile.SYMTYPE),
    ],
)
def test_unsafe_material_member_never_extracts(tmp_path, name, kind):
    source = tmp_path / "bad.tar.gz"
    archive(source, name, kind)
    with pytest.raises(ValueError, match="unsafe"):
        materials.unpack(source, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_parent_gitlink_empty_directory_can_receive_pinned_submodule(tmp_path):
    source = tmp_path / "good.tar.gz"
    archive(source, "root/file.txt")
    output = tmp_path / "empty-gitlink"
    output.mkdir()
    materials.unpack(source, output)
    assert (output / "file.txt").read_bytes() == b"synthetic"
    with pytest.raises(ValueError, match="must be new"):
        materials.unpack(source, output)


def test_material_cache_pin_and_transport_are_enforced(tmp_path):
    target = tmp_path / "source.tar.gz"
    target.write_bytes(b"synthetic")
    item = {
        "url": "https://codeload.github.com/example/source",
        "bytes": 9,
        "sha256": materials.sha(target),
    }
    materials.fetch(item, target)
    target.write_bytes(b"changed")
    with pytest.raises(ValueError, match="does not match pin"):
        materials.fetch(item, target)
    with pytest.raises(ValueError, match="unapproved"):
        materials.fetch(item | {"url": "http://example.invalid/source"}, target)

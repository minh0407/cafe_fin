"""Kit failure gates only, no Office, macros, network or app execution."""

import importlib.util
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/packaging/assemble_pc2_kit.py"
SPEC = importlib.util.spec_from_file_location("packaging_client_kit", SOURCE)
kit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kit)


def test_unreviewed_vba_rejected_before_reading_workbook(tmp_path):
    macro = tmp_path / "not-a-macro.bin"
    macro.write_bytes(b"synthetic unapproved bytes")
    with pytest.raises(ValueError, match="reviewed sample"):
        kit.macro_fixture(tmp_path / "not-read.xlsx", macro, tmp_path / "not-created.xlsm")
    assert not (tmp_path / "not-created.xlsm").exists()


def test_changed_candidate_file_stops_before_copy(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "artifact.txt").write_text("changed")
    (candidate / "build-receipt.json").write_text(
        json.dumps({"files": [{"file": "artifact.txt", "bytes": 99, "sha256": "0" * 64}]})
    )
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="receipt verification"):
        kit.assemble(tmp_path, candidate, tmp_path, tmp_path, tmp_path, None, output)
    assert not output.exists()


def test_candidate_receipt_path_escape_rejected(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("synthetic")
    (candidate / "build-receipt.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "file": "../outside.txt",
                        "bytes": outside.stat().st_size,
                        "sha256": kit.sha(outside),
                    }
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="receipt verification"):
        kit.assemble(tmp_path, candidate, tmp_path, tmp_path, tmp_path, None, tmp_path / "output")


def test_macro_container_supports_implicit_type_and_absent_dimension(tmp_path, monkeypatch):
    # Structure-only synthetic substitute. This is not VBA validity/runtime proof.
    macro = tmp_path / "synthetic.bin"
    macro.write_bytes(b"synthetic structure test")
    monkeypatch.setattr(kit, "MACRO_SHA", kit.sha(macro))
    source = tmp_path / "source.xlsx"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            f'<Types xmlns="{kit.C}"><Default Extension="xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>',
        )
        z.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{kit.P}"/>')
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{kit.S}"><sheets/><calcPr/></workbook>')
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{kit.S}"><sheetData><row r="1"/><row r="2"/></sheetData></worksheet>',
        )
    output = tmp_path / "fixture.xlsm"
    kit.macro_fixture(source, macro, output)
    with zipfile.ZipFile(output) as z:
        types = ET.fromstring(z.read("[Content_Types].xml"))
        main = types.find(f'{{{kit.C}}}Override[@PartName="/xl/workbook.xml"]')
        assert main.get("ContentType") == "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        assert sheet.find(f"{{{kit.S}}}dimension").get("ref") == "A1:I6"
        assert z.read("xl/vbaProject.bin") == macro.read_bytes()

"""Assemble a PC2 preparation or trial kit, never upload or execute it."""

import argparse
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
C = "http://schemas.openxmlformats.org/package/2006/content-types"
MACRO_SHA = "0ced1464b3677e98f5e3a8c5d80135e18dc98dca39299f1a8cfd2a00999fbf9f"
MACRO_LICENSE_SHA = "cf08b60a4ded986b58a617cb8304373bda5c4eff42fb4e30d7597b616e116e87"


def sha(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def file_entry(root, path):
    return {
        "file": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha(path),
    }


def checked_tree(source, target):
    for path in [source, *source.rglob("*")]:
        if path.is_symlink() or path.is_junction():
            raise ValueError("links/junctions are not collected")
    shutil.copytree(source, target)


def macro_fixture(xlsx, macro, output):
    if sha(macro) != MACRO_SHA:
        raise ValueError("VBA fixture differs from the reviewed sample")
    with zipfile.ZipFile(xlsx) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    types = ET.fromstring(parts["[Content_Types].xml"])
    workbook_type = False
    for element in types:
        if element.get("PartName") == "/xl/workbook.xml":
            workbook_type = True
            element.set("ContentType", "application/vnd.ms-excel.sheet.macroEnabled.main+xml")
    if not workbook_type:
        ET.SubElement(
            types,
            f"{{{C}}}Override",
            PartName="/xl/workbook.xml",
            ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml",
        )
    ET.SubElement(
        types,
        f"{{{C}}}Default",
        Extension="bin",
        ContentType="application/vnd.ms-office.vbaProject",
    )
    ET.SubElement(
        types,
        f"{{{C}}}Override",
        PartName="/xl/externalLinks/externalLink1.xml",
        ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml",
    )
    parts["[Content_Types].xml"] = ET.tostring(types, encoding="utf-8", xml_declaration=True)
    rels = ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
    ET.SubElement(
        rels,
        f"{{{P}}}Relationship",
        Id="rIdCFVba",
        Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject",
        Target="vbaProject.bin",
    )
    ET.SubElement(
        rels,
        f"{{{P}}}Relationship",
        Id="rIdCFExternal",
        Type=f"{R}/externalLink",
        Target="externalLinks/externalLink1.xml",
    )
    parts["xl/_rels/workbook.xml.rels"] = ET.tostring(rels, encoding="utf-8", xml_declaration=True)
    workbook = ET.fromstring(parts["xl/workbook.xml"])
    references = ET.Element(f"{{{S}}}externalReferences")
    ET.SubElement(references, f"{{{S}}}externalReference", {f"{{{R}}}id": "rIdCFExternal"})
    calc = workbook.find(f"{{{S}}}calcPr")
    workbook.insert(list(workbook).index(calc) if calc is not None else len(workbook), references)
    parts["xl/workbook.xml"] = ET.tostring(workbook, encoding="utf-8", xml_declaration=True)
    sheet = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    dimension = sheet.find(f"{{{S}}}dimension")
    if dimension is None:
        dimension = ET.Element(f"{{{S}}}dimension")
        sheet.insert(1 if sheet.find(f"{{{S}}}sheetPr") is not None else 0, dimension)
    dimension.set("ref", "A1:I6")
    data = sheet.find(f"{{{S}}}sheetData")
    row1 = data.find(f"{{{S}}}row[@r='1']")
    header = ET.SubElement(row1, f"{{{S}}}c", r="I1", t="inlineStr")
    ET.SubElement(ET.SubElement(header, f"{{{S}}}is"), f"{{{S}}}t").text = "External"
    row2 = data.find(f"{{{S}}}row[@r='2']")
    cell = ET.SubElement(row2, f"{{{S}}}c", r="I2")
    ET.SubElement(cell, f"{{{S}}}f").text = "[1]Sheet1!$A$1"
    ET.SubElement(
        cell, f"{{{S}}}v"
    ).text = "0"  # Deliberately untrusted cache; never a valid fallback.
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(sheet, encoding="utf-8", xml_declaration=True)
    parts["xl/vbaProject.bin"] = macro.read_bytes()
    parts["xl/externalLinks/externalLink1.xml"] = (
        f'''<externalLink xmlns="{S}" xmlns:r="{R}"><externalBook r:id="rId1"><sheetNames><sheetName val="Sheet1"/></sheetNames></externalBook></externalLink>'''.encode()
    )
    parts["xl/externalLinks/_rels/externalLink1.xml.rels"] = (
        f'''<Relationships xmlns="{P}"><Relationship Id="rId1" Type="{R}/externalLinkPath" Target="https://example.invalid/cafe-fin-never-fetch.xlsx" TargetMode="External"/></Relationships>'''.encode()
    )
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as destination:
        for name, body in parts.items():
            destination.writestr(name, body)


def assemble(repo, candidate, fixtures, materials, macro_material, webview, output):
    if output.exists():
        raise ValueError("kit output must be new")
    receipt = json.loads((candidate / "build-receipt.json").read_text(encoding="utf-8"))
    for item in receipt["files"]:
        path = candidate / item["file"]
        if (
            not path.resolve().is_relative_to(candidate.resolve())
            or not path.is_file()
            or sha(path) != item["sha256"]
            or path.stat().st_size != item["bytes"]
        ):
            raise ValueError("candidate receipt verification failed")
    material_receipt = json.loads((materials / "materials-receipt.json").read_text())
    if material_receipt["status"] != "PINNED_MATERIALS_PRESENT_RELINK_NOT_RUN":
        raise ValueError("source materials incomplete")
    for item in material_receipt["materials"]:
        archive = materials / "archives" / item["file"]
        if (
            Path(item["file"]).name != item["file"]
            or archive.is_symlink()
            or archive.stat().st_size != item["bytes"]
            or sha(archive) != item["sha256"]
        ):
            raise ValueError("source material pin changed")
    if sha(macro_material / "LICENSE.txt") != MACRO_LICENSE_SHA:
        raise ValueError("macro sample license changed")
    output.mkdir(parents=True)
    (output / "candidate").mkdir()
    for relative in [item["file"] for item in receipt["files"]] + [
        "build-receipt.json",
        "SHA256SUMS.txt",
    ]:
        source = candidate / relative
        if source.is_symlink() or source.is_junction():
            raise ValueError("candidate link refused")
        destination = output / "candidate" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (output / "source-relink").mkdir()
    (output / "source-relink/archives").mkdir()
    for item in material_receipt["materials"]:
        shutil.copy2(
            materials / "archives" / item["file"], output / "source-relink/archives" / item["file"]
        )
    checked_tree(materials / "trees", output / "source-relink/trees")
    for name in ("materials-receipt.json", "materials.lock.json", "plan-only-receipt.json"):
        if (materials / name).is_file():
            shutil.copy2(materials / name, output / "source-relink" / name)
    (output / "fixtures").mkdir()
    for name in ("mini.csv", "mini.xlsx", "mini-preview.png"):
        shutil.copy2(fixtures / name, output / "fixtures" / name)
    macro_fixture(
        fixtures / "mini.xlsx",
        macro_material / "vbaProject.bin",
        output / "fixtures/preserve-only.xlsm",
    )
    shutil.copy2(macro_material / "LICENSE.txt", output / "fixtures/VBA-SAMPLE-LICENSE.txt")
    shutil.copy2(macro_material / "receipt.json", output / "fixtures/VBA-SAMPLE-SOURCE.json")
    scripts = output / "source-relink/recipe"
    scripts.mkdir()
    for name in (
        "prepare_source_relink.py",
        "materials.lock.json",
        "relink_lxml.ps1",
        "verify_relinked_lxml.py",
        "candidate_receipt.py",
        "notice_provenance.py",
        "verify_kit.py",
        "assemble_pc2_kit.py",
        "create_mini_fixture.mjs",
    ):
        shutil.copy2(repo / "scripts/packaging" / name, scripts / name)
    (output / "docs").mkdir()
    for source, name in (
        ("docs/release/PC2_GUI_ACCEPTANCE_20261108.md", "PC2_GUI_ACCEPTANCE.txt"),
        ("docs/release/SOURCE_RELINK_20261108.md", "SOURCE_RELINK.txt"),
        ("docs/USER_GUIDE.md", "USER_GUIDE.txt"),
    ):
        shutil.copy2(repo / source, output / "docs" / name)
    if webview:
        view = json.loads((webview / "webview2-receipt.json").read_text(encoding="utf-8-sig"))
        binary = webview / view["filename"]
        if (
            Path(view["filename"]).name != view["filename"]
            or view["signature"] != "Valid"
            or view["sha256"].lower() != sha(binary)
            or view["bytes"] != binary.stat().st_size
        ):
            raise ValueError("WebView2 file/receipt verification failed")
        (output / "webview2-offline-support").mkdir()
        for source in (binary, webview / "webview2-receipt.json"):
            if source.is_symlink() or source.is_junction():
                raise ValueError("WebView2 link refused")
            shutil.copy2(source, output / "webview2-offline-support" / source.name)
    expectations = {
        "synthetic": True,
        "ui_execution": "NOT_RUN",
        "source_data_rows": 5,
        "coordinate_basis": "one_based_file_rows_and_columns_including_header_row",
        "mapping": [
            {"source": i, "name": name, "kind": kind, "scale": scale}
            for i, name, kind, scale in [
                (1, "Ngày", "date", 0),
                (2, "Mã", "text", 0),
                (3, "Diễn giải", "text", 0),
                (4, "Thu", "money", 2),
                (5, "Chi", "money", 2),
                (6, "Kg", "decimal", 3),
            ]
        ],
        "duplicate_policy": "Explicitly exclude source row4 matching source row2; do not assume a universal business key",
        "first_confirm": {
            "published_rows": 3,
            "excluded_source_rows": [4],
            "invalid_source_rows": [5],
            "thu": "15000000.00",
            "chi": "10000000.00",
            "kg": "2050.750",
        },
        "repair_source_row5": {"date": "2026-11-08", "thu": "250000.00", "kg": "1.234"},
        "second_confirm": {
            "new_published_rows": 1,
            "total_published_rows": 4,
            "thu": "15250000.00",
            "chi": "10000000.00",
            "kg": "2051.984",
        },
        "stock_mutations_from_accounting": 0,
        "macro_fixture": {
            "vba_sha256": MACRO_SHA,
            "macro_execution": "NEVER",
            "external_link_execution": "NEVER",
            "cached_external_zero": "UNTRUSTED",
            "safety_certification": False,
        },
    }
    (output / "fixtures/expected-results.json").write_text(
        json.dumps(expectations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    has_installer = receipt["installer_present"]
    (output / "START_HERE.txt").write_text(
        (
            "CAFE FIN — BỘ CÀI THỬ VÀ NGHIỆM THU\n\n"
            if has_installer
            else "CAFE FIN — KIT CHUẨN BỊ, CHƯA CÓ BỘ CÀI\n\n"
        )
        + f"Source baseline: {receipt['source_commit']}\nInstaller có file: {receipt['installer_present']}\n"
        + (
            "Mở file .exe trong candidate/installer để cài thử, rồi làm theo docs/PC2_GUI_ACCEPTANCE.txt bằng GUI.\n"
            if has_installer
            else "Chưa thể cài thử: kit này chưa có file bộ cài .exe.\n"
        )
        + "Không chạy sidecar trực tiếp. Các tệp hỗ trợ không cần chạy riêng.\n"
        + "Kết quả Windows sạch/PC2 và relink vẫn NOT RUN; xem phạm vi bằng chứng trong manifest và docs.\n"
        + "Không mở/bật macro hoặc external link của preserve-only.xlsm trong Office. Chỉ dùng nhập app để kiểm bảo toàn byte.\n",
        encoding="utf-8-sig",
    )
    (output / "RESULTS.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_commit": receipt["source_commit"],
                "pc2_access": "NOT_RUN",
                "machine": {},
                "cases": {
                    name: {"status": "NOT_RUN", "evidence": []}
                    for name in (
                        "install",
                        "offline_first_launch",
                        "select_local_drive",
                        "local_workflow",
                        "tray",
                        "startup_opt_in",
                        "backup_move_restore",
                        "upgrade",
                        "uninstall_reinstall",
                        "macro_external_guard",
                    )
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    files = [file_entry(output, path) for path in sorted(output.rglob("*")) if path.is_file()]
    manifest = {
        "schema_version": 1,
        "prepared_at_utc": datetime.now(UTC).isoformat(),
        "source_commit": receipt["source_commit"],
        "status": "TRIAL_KIT_NOT_RELEASE_ACCEPTED"
        if has_installer
        else "PREPARATION_ONLY_NOT_READY_FOR_INSTALL",
        "installer_present": receipt["installer_present"],
        "relink_execution": "NOT_RUN",
        "distribution_clearance": False,
        "pc2_acceptance": "NOT_RUN",
        "files": files,
    }
    (output / "kit-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{item['sha256']}  {item['file']}\n" for item in files)
        + f"{sha(output / 'kit-manifest.json')}  kit-manifest.json\n",
        encoding="utf-8",
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "fixtures", "materials", "macro-material", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--webview", type=Path)
    args = parser.parse_args()
    result = assemble(
        args.repo,
        args.candidate,
        args.fixtures,
        args.materials,
        args.macro_material,
        args.webview,
        args.output,
    )
    print(result["status"], len(result["files"]), "files")


if __name__ == "__main__":
    main()

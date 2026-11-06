# -*- mode: python ; coding: utf-8 -*-
"""Windows x64 sidecar: stdio IPC stays available; the native parent hides its window."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

desktop = Path(SPECPATH).resolve()
repository = desktop.parent
backend = repository / "backend"
entrypoint = backend / "cafe_fin" / "__main__.py"
if not entrypoint.is_file():
    raise RuntimeError("Backend entrypoint is not implemented yet; do not package a placeholder.")

# Fixed package assets include Noto font binaries, their OFL license and exact
# dependency notices. Do not collect ReportLab's unrelated DarkGarden GPL fonts.
datas = collect_data_files("cafe_fin", includes=["core/assets/**/*", "contracts/templates/*.json"])
datas += collect_data_files("docx", includes=["templates/**/*"])
datas += collect_data_files("tzdata")
datas += copy_metadata("cafe-fin", recursive=True)
for package in ("argon2-cffi", "argon2-cffi-bindings", "cffi", "python-docx", "reportlab", "pillow", "lxml", "tzdata"):
    datas += copy_metadata(package)

hiddenimports = ["_cffi_backend", "_argon2_cffi_bindings", "lxml.etree", "lxml.objectify", "PIL._imaging"]
hiddenimports += collect_submodules("cafe_fin")
hiddenimports += collect_submodules("uvicorn")

analysis = Analysis(
    [str(entrypoint)],
    pathex=[str(backend)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PIL.ImageTk", "PIL._imagingtk", "IPython", "pytest", "pypdf", "rlextra", "pyRXP", "lxml.isoschematron"],
    noarchive=False,
)

# Hooks may discover additional ReportLab data. None of the renderer's code
# depends on those bundled third-party font examples.
analysis.datas = [
    item for item in analysis.datas
    if "darkgarden" not in str(item).lower()
]
# Windows 11 is the supported platform. Its system UCRT is always used; never
# redistribute a UCRT/API-set DLL discovered from an unrelated host PATH.
analysis.binaries = [
    item for item in analysis.binaries
    if item[0].lower() != "ucrtbase.dll"
    and not item[0].lower().startswith(("api-ms-win-", "ext-ms-win-"))
]
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="cafe-fin-sidecar-x86_64-pc-windows-msvc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    runtime_tmpdir=None,
    uac_admin=False,
)

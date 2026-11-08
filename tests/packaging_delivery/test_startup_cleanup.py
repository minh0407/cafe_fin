"""Installer wiring plus opt-in real NSIS/raw-registry test in an isolated key.

No production Run key is accessed. Set CAFE_FIN_TEST_MAKENSIS to an absolute
makensis.exe path only on a host authorized to execute newly compiled probes.
"""

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_hook_is_post_uninstall_and_skips_update():
    config = json.loads((ROOT / "desktop/tauri.conf.json").read_text())
    hooks = config["bundle"]["windows"]["nsis"]["installerHooks"]
    assert hooks == "./scripts/installer-hooks.nsh"
    text = (ROOT / "desktop" / hooks).read_text()
    assert "!macro NSIS_HOOK_POSTUNINSTALL" in text
    assert text.index("StrCmp $UpdateMode 1") < text.index("!insertmacro CF_CLEANUP")
    assert '"Software\\Microsoft\\Windows\\CurrentVersion\\Run"' in text
    # MAINBINARYNAME and UpdateMode are defined after Tauri includes the hooks.
    assert "Function " not in text


def test_custom_template_changes_only_stock_unconditional_startup_deletion():
    config = json.loads((ROOT / "desktop/tauri.conf.json").read_text())
    template = config["bundle"]["windows"]["nsis"]["template"]
    text = (ROOT / "desktop" / template).read_text(encoding="utf-8")
    proof = json.loads((ROOT / "desktop/notices/tauri-installer-template-source.json").read_text())
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    assert lock["packages"]["node_modules/@tauri-apps/cli"]["version"] == "2.12.4"
    assert proof["upstream_tag"] == "tauri-cli-v2.12.4"
    assert (
        proof["upstream_lf_sha256"]
        == "d00089d3b1a2c4a30d7b6e098079100cb8f25e980f84d4515aca4597b95e967d"
    )
    assert text.count(proof["replacement_block"]) == 1
    original = text.replace(proof["replacement_block"], proof["removed_block"])
    assert hashlib.sha256(original.encode()).hexdigest() == proof["upstream_lf_sha256"]
    assert "CurrentVersion\\Run" not in text
    license_file = ROOT / "desktop/notices/tauri-installer-template-license.txt"
    assert (
        hashlib.sha256(license_file.read_text(encoding="utf-8").encode()).hexdigest()
        == proof["license_lf_sha256"]
    )


@pytest.mark.skipif(
    sys.platform != "win32" or not os.environ.get("CAFE_FIN_TEST_MAKENSIS"),
    reason="opt-in native NSIS probe; local AppControl restriction is not bypassed",
)
def test_native_cleanup_exact_raw_value_only(tmp_path):
    import ctypes
    import winreg
    from ctypes import wintypes

    compiler = Path(os.environ["CAFE_FIN_TEST_MAKENSIS"])
    assert compiler.is_absolute() and compiler.is_file()
    subkey = rf"Software\CafeFinPackagingTest-{uuid.uuid4().hex}"
    assert subkey.startswith("Software\\CafeFinPackagingTest-")
    install = "C:\\CafeFin test\\Cà phê 𠮷"
    command = f'"{install}\\cafe-fin-desktop.exe" --startup-v1'
    expected = (command + "\0").encode("utf-16-le")
    exe = tmp_path / "cleanup-probe.exe"

    def nsis(value):
        return str(value).replace("$", "$$").replace('"', '$\\"')

    script = tmp_path / "cleanup-probe.nsi"
    script.write_text(
        "Unicode true\nRequestExecutionLevel user\nSilentInstall silent\n"
        f'OutFile "{nsis(exe)}"\nName "CafeFin isolated cleanup probe"\n'
        '!define MAINBINARYNAME "cafe-fin-desktop"\n'
        f'!include "{nsis(ROOT / "desktop/scripts/startup-cleanup.nsh")}"\n'
        f'Section\nStrCpy $INSTDIR "{nsis(install)}"\n'
        f'!insertmacro CF_CLEANUP_OWNED_STARTUP "{subkey}"\nSectionEnd\n',
        encoding="utf-8-sig",
    )
    subprocess.run([str(compiler), "/NOCD", "/V2", str(script)], check=True, timeout=60)
    assert exe.is_file()
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.RegSetValueExW.argtypes = (
        wintypes.HKEY,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    api.RegSetValueExW.restype = wintypes.LONG
    api.RegQueryValueExW.argtypes = (
        wintypes.HKEY,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
    )
    api.RegQueryValueExW.restype = wintypes.LONG
    access = winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY

    def query(key, name):
        kind, size = wintypes.DWORD(), wintypes.DWORD()
        rc = api.RegQueryValueExW(
            int(key), name, None, ctypes.byref(kind), None, ctypes.byref(size)
        )
        if rc == 2:
            return None
        assert rc == 0
        buffer = ctypes.create_string_buffer(size.value)
        assert (
            api.RegQueryValueExW(
                int(key), name, None, ctypes.byref(kind), buffer, ctypes.byref(size)
            )
            == 0
        )
        return kind.value, buffer.raw[: size.value]

    def run():
        subprocess.run([str(exe)], check=True, timeout=20)

    def assert_missing_key():
        with pytest.raises(FileNotFoundError):
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, access):
                pass

    def remove_leaf():
        try:
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, subkey, winreg.KEY_WOW64_64KEY)
        except FileNotFoundError:
            pass

    try:
        assert_missing_key()
        run()
        assert_missing_key()  # cleanup never creates a missing key
        cases = [
            ("exact", winreg.REG_SZ, expected, True),
            ("expand-type", winreg.REG_EXPAND_SZ, expected, False),
            ("binary-type", winreg.REG_BINARY, expected, False),
            ("case", winreg.REG_SZ, expected.replace(b"C\0", b"c\0", 1), False),
            ("path", winreg.REG_SZ, expected.replace(b"t\0e\0s\0t\0", b"b\0e\0s\0t\0"), False),
            ("flag", winreg.REG_SZ, expected.replace(b"v\0" + b"1\0", b"v\0" + b"2\0"), False),
            ("arguments", winreg.REG_SZ, (command + " --foreign\0").encode("utf-16-le"), False),
            ("missing-nul", winreg.REG_SZ, expected[:-2], False),
            ("extra-nul", winreg.REG_SZ, expected + b"\0\0", False),
            ("embedded-nul", winreg.REG_SZ, expected[:12] + b"\0\0" + expected[14:], False),
            ("odd-byte-count", winreg.REG_SZ, expected[:-1], False),
            ("empty", winreg.REG_SZ, b"", False),
        ]
        for name, kind, raw, deleted in cases:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, access) as key:
                winreg.SetValueEx(key, "OtherEntry", 0, winreg.REG_SZ, "keep me")
                buffer = ctypes.create_string_buffer(raw)
                assert api.RegSetValueExW(int(key), "CafeFin", 0, kind, buffer, len(raw)) == 0
            run()
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, access) as key:
                assert query(key, "CafeFin") == (None if deleted else (kind, raw)), name
                assert winreg.QueryValueEx(key, "OtherEntry") == ("keep me", winreg.REG_SZ)
            remove_leaf()
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, access) as key:
            winreg.SetValueEx(key, "OtherEntry", 0, winreg.REG_SZ, "keep me")
        run()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, access) as key:
            assert query(key, "CafeFin") is None
            assert winreg.QueryValueEx(key, "OtherEntry") == ("keep me", winreg.REG_SZ)
    finally:
        remove_leaf()  # this one random leaf only; never Run or its parent

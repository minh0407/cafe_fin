"""Scoped Windows Credential Manager adapter; no file, environment or DB fallback."""

import ctypes
import hashlib
import json
import re
import sys
import uuid
from contextlib import contextmanager

from .errors import CoreError

MAX_CREDENTIAL_BYTES = 2560
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168
_DWORD = ctypes.c_uint32
_BYTE = ctypes.c_ubyte


class _FileTime(ctypes.Structure):
    _fields_ = [("low", _DWORD), ("high", _DWORD)]


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", _DWORD),
        ("Type", _DWORD),
        ("TargetName", ctypes.c_wchar_p),
        ("Comment", ctypes.c_wchar_p),
        ("LastWritten", _FileTime),
        ("CredentialBlobSize", _DWORD),
        ("CredentialBlob", ctypes.POINTER(_BYTE)),
        ("Persist", _DWORD),
        ("AttributeCount", _DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


class _WindowsAPI:
    def __init__(self):
        # Resolve a system DLL only, never an adjacent DLL or an executable on PATH.
        self.dll = ctypes.WinDLL("advapi32.dll", use_last_error=True, winmode=0x00000800)
        self.read = self.dll.CredReadW
        self.read.argtypes = [
            ctypes.c_wchar_p,
            _DWORD,
            _DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        ]
        self.read.restype = ctypes.c_int32
        self.write = self.dll.CredWriteW
        self.write.argtypes = [ctypes.POINTER(_Credential), _DWORD]
        self.write.restype = ctypes.c_int32
        self.delete = self.dll.CredDeleteW
        self.delete.argtypes = [ctypes.c_wchar_p, _DWORD, _DWORD]
        self.delete.restype = ctypes.c_int32
        self.free = self.dll.CredFree
        self.free.argtypes = [ctypes.c_void_p]
        self.free.restype = None
        self.kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True, winmode=0x00000800)
        self.create_mutex = self.kernel.CreateMutexW
        self.create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_wchar_p]
        self.create_mutex.restype = ctypes.c_void_p
        self.wait = self.kernel.WaitForSingleObject
        self.wait.argtypes = [ctypes.c_void_p, _DWORD]
        self.wait.restype = _DWORD
        self.release_mutex = self.kernel.ReleaseMutex
        self.release_mutex.argtypes = [ctypes.c_void_p]
        self.release_mutex.restype = ctypes.c_int32
        self.close_handle = self.kernel.CloseHandle
        self.close_handle.argtypes = [ctypes.c_void_p]
        self.close_handle.restype = ctypes.c_int32


def _target_for(key: str) -> str:
    """Map only the reporting namespace to application-owned generic credentials."""
    if not isinstance(key, str) or len(key) > 256:
        raise CoreError("SECRET_KEY_INVALID", "Khóa kho bí mật không hợp lệ.")
    parts = key.split("/")
    legacy = len(parts) == 4 and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", parts[3])
    telegram = (
        len(parts) == 5
        and parts[3] == "telegram"
        and re.fullmatch(r"[1-9][0-9]{0,15}", parts[4])
        and int(parts[4]) < 2**52
    )
    if parts[:2] != ["cafe_fin", "reporting"] or not (legacy or telegram):
        raise CoreError("SECRET_KEY_INVALID", "Khóa kho bí mật không hợp lệ.")
    try:
        canonical_root = str(uuid.UUID(parts[2]))
    except (ValueError, AttributeError):
        raise CoreError("SECRET_KEY_INVALID", "Khóa kho bí mật không hợp lệ.") from None
    if parts[2] != canonical_root:
        raise CoreError("SECRET_KEY_INVALID", "Khóa kho bí mật không hợp lệ.")
    prefix = "CafeFin:reporting:telegram:v1:" if telegram else "CafeFin:reporting:v1:"
    return prefix + hashlib.sha256(key.encode("utf-8")).hexdigest()


def _unavailable() -> CoreError:
    return CoreError("SECRET_STORE_UNAVAILABLE", "Không truy cập được kho bí mật Windows.", 503)


def _reject_constant(_value):
    raise ValueError("Non-finite JSON")


@contextmanager
def _locked(api, target):
    # Serialize cooperating adapters across threads/processes in this Windows session.
    # Native concurrent replacement can transiently return ERROR_NOT_FOUND to a reader.
    try:
        handle = api.create_mutex(None, False, "Local\\CafeFin.Credentials." + target[-64:])
    except (OSError, ValueError, ctypes.ArgumentError):
        raise _unavailable() from None
    if not handle:
        raise _unavailable()
    acquired = False
    try:
        try:
            result = api.wait(handle, 5000)
        except (OSError, ValueError, ctypes.ArgumentError):
            raise _unavailable() from None
        if result == 258:
            raise CoreError("SECRET_STORE_BUSY", "Kho bí mật đang bận; vui lòng thử lại.", 503)
        if result not in (0, 128):  # WAIT_OBJECT_0 or ownership after WAIT_ABANDONED.
            raise _unavailable()
        acquired = True
        yield
    finally:
        if acquired:
            api.release_mutex(handle)
        api.close_handle(handle)


class WindowsCredentialStore:
    """One UTF-8 JSON object per credential; each put replaces the whole object.

    ``available`` reports whether the Windows API is loaded, not whether a key is
    configured. OS errors raise sanitized CoreError and must not be treated as a
    successful credential lookup. Callers must authorize access before invoking
    this internal adapter. Credentials belong to the current Windows user.
    """

    def __init__(self):
        self._api = None
        if sys.platform == "win32":
            try:
                self._api = _WindowsAPI()
            except (OSError, AttributeError):
                pass

    @property
    def available(self) -> bool:
        return self._api is not None

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    def get(self, key: str) -> dict | None:
        target = _target_for(key)
        api = self._api
        if api is None:
            return None
        with _locked(api, target):
            return self._get(api, target)

    @staticmethod
    def _get(api, target):
        pointer = ctypes.POINTER(_Credential)()
        try:
            ok = api.read(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer))
        except (OSError, ValueError, ctypes.ArgumentError):
            raise _unavailable() from None
        if not ok:
            if ctypes.get_last_error() == _ERROR_NOT_FOUND:
                return None
            raise _unavailable()
        try:
            if not pointer:
                raise ValueError("Missing credential")
            credential = pointer.contents
            if (
                credential.Type != _CRED_TYPE_GENERIC
                or credential.TargetName != target
                or credential.Persist != _CRED_PERSIST_LOCAL_MACHINE
                or not 0 < credential.CredentialBlobSize <= MAX_CREDENTIAL_BYTES
                or not credential.CredentialBlob
            ):
                raise ValueError("Invalid credential")
            blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            value = json.loads(blob.decode("utf-8"), parse_constant=_reject_constant)
            if not isinstance(value, dict):
                raise ValueError("Invalid JSON object")
            return value
        except (ValueError, UnicodeError, TypeError, RecursionError):
            raise CoreError(
                "SECRET_VALUE_INVALID", "Dữ liệu trong kho bí mật không hợp lệ.", 503
            ) from None
        finally:
            if pointer:
                api.free(pointer)

    def put(self, key: str, value: dict) -> None:
        target = _target_for(key)
        if not isinstance(value, dict) or any(not isinstance(field, str) for field in value):
            raise CoreError("SECRET_VALUE_INVALID", "Dữ liệu kho bí mật phải là đối tượng JSON.")
        try:
            blob = json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
            raise CoreError("SECRET_VALUE_INVALID", "Dữ liệu kho bí mật không hợp lệ.") from None
        if len(blob) > MAX_CREDENTIAL_BYTES:
            raise CoreError(
                "SECRET_VALUE_TOO_LARGE", "Dữ liệu kho bí mật vượt giới hạn 2.560 byte."
            )
        api = self._api
        if api is None:
            raise _unavailable()
        buffer = (_BYTE * len(blob)).from_buffer_copy(blob)
        credential = _Credential()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.Comment = "Cafe Fin reporting credentials"
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(_BYTE))
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "CafeFin"
        try:
            # Never delete first: a failed validation or failed OS call keeps the old value.
            with _locked(api, target):
                if not api.write(ctypes.byref(credential), 0):
                    raise _unavailable()
        except (OSError, ValueError, ctypes.ArgumentError):
            raise _unavailable() from None
        finally:
            ctypes.memset(buffer, 0, len(buffer))

    def delete(self, key: str) -> None:
        target = _target_for(key)
        api = self._api
        if api is None:
            raise _unavailable()
        try:
            with _locked(api, target):
                ok = api.delete(target, _CRED_TYPE_GENERIC, 0)
                if not ok and ctypes.get_last_error() != _ERROR_NOT_FOUND:
                    raise _unavailable()
        except (OSError, ValueError, ctypes.ArgumentError):
            raise _unavailable() from None

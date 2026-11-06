"""One Win32 disk spelling for identity and IO; verbatim is never a device escape."""

import os
import re
import stat
from pathlib import Path

from .errors import CoreError

_DISK = re.compile(r"^[A-Za-z]:\\")
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$"} | {
    prefix + digit for prefix in ("COM", "LPT") for digit in "123456789¹²³"
}


def local_path(value: Path | str) -> Path:
    """Normalize only safe drive aliases before pathlib can erase lexical hazards.

    Standard Windows long-path support remains usable; never truncate components
    or rewrite on-disk markers/fingerprints. Other platforms keep Path semantics.
    """
    raw = os.fspath(value)
    if os.name != "nt":
        return Path(raw).absolute()
    if not isinstance(raw, str) or "\x00" in raw:
        raise CoreError("DATA_ROOT_PATH_INVALID", "Đường dẫn local không hợp lệ.", 409)
    if raw.startswith("\\\\?\\"):
        tail = raw[4:]
        if tail.upper().startswith("UNC\\"):
            raise CoreError("DATA_ROOT_REMOTE", "Chọn thư mục trên ổ đĩa local.")
        if not _DISK.match(tail) or "/" in tail:
            raise CoreError("DATA_ROOT_PATH_INVALID", "Chỉ nhận đường dẫn ổ đĩa local.", 409)
        raw = tail
    elif raw.startswith(("\\\\.\\", "\\??\\")):
        raise CoreError("DATA_ROOT_PATH_INVALID", "Không dùng đường dẫn thiết bị.", 409)
    elif raw.startswith(("\\\\", "//")):
        raise CoreError("DATA_ROOT_REMOTE", "Chọn thư mục trên ổ đĩa local.")
    else:
        raw = raw.replace("/", "\\")
    if raw.startswith("\\") or (len(raw) >= 2 and raw[1] == ":" and not _DISK.match(raw)):
        raise CoreError("DATA_ROOT_PATH_INVALID", "Cần đường dẫn ổ đĩa đầy đủ.", 409)
    tail = raw[3:] if _DISK.match(raw) else raw
    for component in tail.rstrip("\\").split("\\") if tail.rstrip("\\") else ():
        if (
            not component
            or component in (".", "..")
            or component.endswith((".", " "))
            or any(ord(char) < 32 or char in '<>:"|?*' for char in component)
            or component.split(".")[0].rstrip(" ").upper() in _RESERVED
        ):
            raise CoreError("DATA_ROOT_PATH_INVALID", "Thành phần đường dẫn không an toàn.", 409)
    return Path(raw).absolute()


def resolved_local_path(value: Path | str) -> Path:
    # resolve() can return a verbatim spelling; canonical identity must not retain it.
    return local_path(local_path(value).resolve())


def is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        raise CoreError("DATA_ROOT_UNAVAILABLE", "Không kiểm tra được vị trí local.", 409) from None
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )

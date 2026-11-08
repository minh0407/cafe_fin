"""Recipient-only executable proof; not run on an AppControl-blocked host."""

import argparse
import ctypes
import hashlib
import json
from pathlib import Path

from lxml import etree, objectify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    modules = []
    for module in (etree, objectify):
        library = ctypes.CDLL(module.__file__)
        probe = library.cafe_fin_relink_probe
        probe.argtypes = []
        probe.restype = ctypes.c_int
        if probe() != 20261108:
            raise RuntimeError("modified iconv proof missing from linked module")
        modules.append(
            {
                "module": module.__name__,
                "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
                "probe": 20261108,
            }
        )
    xml = "<hợp_đồng>Tiếng Việt và ký tự 𠮷 😀</hợp_đồng>"
    parsed = etree.fromstring(xml)
    assert etree.tostring(parsed, encoding="unicode") == xml
    assert objectify.fromstring(xml.encode("utf-8")).text == "Tiếng Việt và ký tự 𠮷 😀"
    args.output.write_text(
        json.dumps(
            {"status": "MODIFIED_ICONV_IN_BOTH_PYDS", "unicode_parse": "PASS", "modules": modules},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

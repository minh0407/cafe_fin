"""Download pinned public VBA example as data only; never import or execute it."""

import argparse
import json
from pathlib import Path

from prepare_source_relink import fetch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("fixture material output must be new")
    args.output.mkdir(parents=True)
    catalog = json.loads(Path(__file__).with_name("fixture_materials.lock.json").read_text())
    for item in catalog["materials"]:
        if Path(item["file"]).name != item["file"]:
            raise ValueError("invalid material filename")
        fetch(item, args.output / item["file"])
    (args.output / "receipt.json").write_text(
        json.dumps(catalog | {"status": "DOWNLOADED_NOT_EXECUTED"}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

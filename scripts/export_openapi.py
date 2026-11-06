"""Export only the schema from a new temporary synthetic runtime, never user data."""

import json
import tempfile
from pathlib import Path

from cafe_fin.core.api import create_app
from cafe_fin.core.runtime import Runtime


def main():
    destination = Path(__file__).resolve().parents[1] / "docs/handoffs/foundation/openapi-v1.json"
    with tempfile.TemporaryDirectory(prefix="cafe-fin-openapi-") as temporary:
        runtime = Runtime(Path(temporary) / "synthetic-root", initialize=True)
        try:
            app = create_app(runtime, "schema-export-synthetic-session-0123456789", port=49152)
            schema = app.openapi()
        finally:
            runtime.close()
    destination.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(destination)


if __name__ == "__main__":
    main()

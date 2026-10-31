"""Write the FastAPI OpenAPI spec to openapi/openapi.json at the repo root.

uv run python scripts/export_openapi.py          # write the file
uv run python scripts/export_openapi.py --check  # fail if the file is out of date (CI)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app  # noqa: E402

OUTPUT = Path(__file__).resolve().parents[2] / "openapi" / "openapi.json"


def main() -> int:
    spec = json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"

    if "--check" in sys.argv:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != spec:
            print(f"{OUTPUT} is out of date. Run: uv run python scripts/export_openapi.py")
            return 1
        print("OpenAPI spec is up to date.")
        return 0

    OUTPUT.write_text(spec, encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

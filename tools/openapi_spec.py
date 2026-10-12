"""Writes docs/openapi-v1.json, the OpenAPI spec of StationPlay's API
(version 1), from the server itself. Run it after changing the API:

    python tools/openapi_spec.py

tests/test_api.py checks that the file and the server match.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "openapi-v1.json"


def written() -> str:
    """The spec, as the file holds it."""
    sys.path.insert(0, str(ROOT))
    from app import api
    from app.config import Settings
    from app.main import create_app

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(plex_url="http://plex.invalid", plex_token="token", data_dir=Path(tmp))
        spec = api.spec(create_app(settings))
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    SPEC.write_text(written())
    print(f"Wrote {SPEC.relative_to(ROOT)}")

"""DocEngine — Utility: Export and version OpenAPI v3 specification.

Generates `docs/openapi.json` from the running FastAPI application definition.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.main import create_app
from app.config.settings import get_settings


def export_openapi() -> Path:
    """Generate and write docs/openapi.json."""
    settings = get_settings()
    with patch("app.api.main._build_extraction_service"):
        app = create_app(settings)
        openapi_schema = app.openapi()

    output_path = Path("docs") / "openapi.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)

    print(f"OpenAPI specification successfully exported to: {output_path.resolve()}")
    return output_path


if __name__ == "__main__":
    export_openapi()

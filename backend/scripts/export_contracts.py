"""Generate exact API contract artifacts without starting the application."""

import json
from pathlib import Path

from app.main import create_app

BACKEND = Path(__file__).resolve().parents[1]


def export():
    spec = create_app().openapi()
    (BACKEND / "openapi.json").write_text(
        json.dumps(spec, indent=2) + "\n", encoding="utf-8"
    )
    # A standalone self-contained subset for pasting into MEMORY.md.
    responses = {}
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            responses[f"{method.upper()} {path}"] = operation["responses"]
    contract = {"responses": responses, "components": spec["components"]}
    (BACKEND / "response-schemas.json").write_text(
        json.dumps(contract, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Exported {len(responses)} routes and {len(spec['components']['schemas'])} schema components"
    )
    return contract


if __name__ == "__main__":
    export()

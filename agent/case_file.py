"""Validate a case file against agent/case_file.schema.json, standard library only.

Supports the JSON Schema keywords the schema uses: type, required, properties,
additionalProperties, items, enum, const, pattern, minLength, maxLength,
minItems and maxItems.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().with_name("case_file.schema.json")

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _check(value, schema: dict, path: str, errors: list[str]) -> None:
    expected = schema.get("type")
    if expected and not (isinstance(value, _TYPES[expected]) and not (expected != "boolean" and isinstance(value, bool))):
        errors.append(f"{path}: expected {expected}")
        return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']} characters")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match {schema['pattern']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for index, item in enumerate(value):
                _check(item, schema["items"], f"{path}[{index}]", errors)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: missing")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _check(item, properties[key], f"{path}.{key}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: not allowed")


def validate(case, schema: dict | None = None) -> list[str]:
    """Return a list of problems; an empty list means the case file is valid."""
    errors: list[str] = []
    _check(case, schema or load_schema(), "case", errors)
    return errors


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python agent/case_file.py cases/C-001.json")
    problems = validate(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    print("\n".join(problems) if problems else "valid")
    sys.exit(1 if problems else 0)

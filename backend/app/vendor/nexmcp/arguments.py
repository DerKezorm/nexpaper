"""The arguments of a call, checked against the tool's schema before anything runs or waits: the union of what
nexnotes, nexlore, nextime and nexdeck checked. A problem is one short English sentence for the program."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

#: How deep arguments may nest, and the largest whole number in them (what SQLite holds).
MAX_DEPTH = 20
INT_LIMIT = 2**63 - 1

_KINDS: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def shape_problem(args: Any) -> str | None:
    """What no tool takes, whatever its schema says: nested too deep, text that is not valid Unicode (a lone surrogate
    cannot be stored), whole numbers past 64 bits."""
    waiting: list[tuple[Any, int]] = [(args, 0)]
    while waiting:
        value, depth = waiting.pop()
        if depth > MAX_DEPTH:
            return f"The arguments are nested deeper than {MAX_DEPTH} levels."
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return "The arguments hold text that is not valid Unicode."
        elif isinstance(value, bool):
            continue
        elif isinstance(value, int):
            if not -INT_LIMIT - 1 <= value <= INT_LIMIT:
                return "A number in the arguments is too large."
        elif isinstance(value, dict):
            for key, inner in value.items():
                waiting.append((key, depth + 1))
                waiting.append((inner, depth + 1))
        elif isinstance(value, list):
            waiting.extend((inner, depth + 1) for inner in value)
    return None


def _value_problem(name: str, value: Any, spec: Mapping[str, Any]) -> str | None:
    kind = spec.get("type")
    wanted = _KINDS.get(kind) if isinstance(kind, str) else None
    if wanted is not None:
        if not isinstance(value, wanted) or (isinstance(value, bool) and kind in ("integer", "number")):
            return f"'{name}' must be of type {kind}."
    if "enum" in spec and value not in spec["enum"]:
        return f"'{name}' must be one of {', '.join(map(str, spec['enum']))}."
    if isinstance(value, str):
        if len(value) > spec.get("maxLength", len(value)):
            return f"'{name}' holds at most {spec['maxLength']} characters."
        if len(value) < spec.get("minLength", 0):
            return f"'{name}' holds at least {spec['minLength']} characters."
        pattern = spec.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            return f"'{name}' does not have the expected form."
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < spec.get("minimum", value) or value > spec.get("maximum", value):
            return f"'{name}' is out of range."
    if isinstance(value, list):
        if len(value) > spec.get("maxItems", len(value)):
            return f"'{name}' holds at most {spec['maxItems']} entries."
        items = spec.get("items")
        if isinstance(items, Mapping):
            for index, inner in enumerate(value):
                problem = _value_problem(f"{name}[{index}]", inner, items)
                if problem:
                    return problem
    if isinstance(value, dict) and isinstance(spec.get("properties"), Mapping):
        return _object_problem(value, spec, name + ".")
    return None


def _object_problem(args: Mapping[str, Any], schema: Mapping[str, Any], prefix: str = "") -> str | None:
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    for key in required:
        if args.get(key) is None:
            return f"'{prefix}{key}' is missing."
    for key, value in args.items():
        spec = properties.get(key)
        if spec is None:
            if schema.get("additionalProperties") is not False:
                continue
            return f"There is no argument '{prefix}{key}'."
        if value is None and key not in required:
            continue
        problem = _value_problem(f"{prefix}{key}", value, spec)
        if problem:
            return problem
    return None


def check(schema: Mapping[str, Any], args: Any) -> str | None:
    """What is wrong with ``args`` by ``schema``; ``None`` when they fit. Unknown arguments are refused where the
    schema says ``additionalProperties: false`` (nexnotes, nextime always; nexlore, nexdeck where they said so)."""
    if not isinstance(args, dict):
        return "'arguments' must be an object."
    return shape_problem(args) or _object_problem(args, schema)

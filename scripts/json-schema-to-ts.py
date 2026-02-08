#!/usr/bin/env python3
"""Convert JSON Schema (from Pydantic models) to TypeScript interface definitions.

This is a lightweight converter that handles the subset of JSON Schema produced
by Pydantic v2's model_json_schema(). It avoids external dependencies like
openapi-typescript so the generation pipeline requires only Python.

Usage:
    python scripts/json-schema-to-ts.py <schema.json> [--output FILE]

Input:  A JSON file mapping model names to their JSON Schema.
Output: TypeScript interface declarations.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def json_type_to_ts(prop: dict[str, Any], defs: dict[str, Any] | None = None) -> str:
    """Convert a JSON Schema property definition to a TypeScript type string."""
    # Handle $ref
    if "$ref" in prop:
        ref_name = prop["$ref"].rsplit("/", 1)[-1]
        return ref_name

    # Handle anyOf (Pydantic's way of representing Optional / Union types)
    if "anyOf" in prop:
        types = []
        for variant in prop["anyOf"]:
            ts = json_type_to_ts(variant, defs)
            if ts != "null":
                types.append(ts)
        non_null = [t for t in types if t != "null"]
        has_null = any(
            v.get("type") == "null" for v in prop["anyOf"]
        )
        if not non_null:
            return "null"
        result = " | ".join(non_null) if len(non_null) > 1 else non_null[0]
        if has_null:
            result += " | null"
        return result

    # Handle allOf (single-item allOf is common for $ref wrapping)
    if "allOf" in prop:
        parts = [json_type_to_ts(p, defs) for p in prop["allOf"]]
        return " & ".join(parts)

    json_type = prop.get("type")

    if json_type == "string":
        return "string"
    if json_type == "integer" or json_type == "number":
        return "number"
    if json_type == "boolean":
        return "boolean"
    if json_type == "null":
        return "null"
    if json_type == "array":
        items = prop.get("items", {})
        item_type = json_type_to_ts(items, defs)
        return f"{item_type}[]"
    if json_type == "object":
        additional = prop.get("additionalProperties")
        if additional and isinstance(additional, dict):
            val_type = json_type_to_ts(additional, defs)
            return f"Record<string, {val_type}>"
        return "Record<string, unknown>"

    # Fallback
    return "unknown"


def schema_to_interface(
    name: str,
    schema: dict[str, Any],
    emitted: set[str],
) -> list[str]:
    """Convert a single JSON Schema to TypeScript interface declaration(s).

    Returns a list of interface strings (may include nested $defs).
    """
    lines: list[str] = []
    defs = schema.get("$defs", {})

    # First emit any $defs that haven't been emitted yet
    for def_name, def_schema in defs.items():
        if def_name not in emitted:
            lines.extend(schema_to_interface(def_name, def_schema, emitted))

    if name in emitted:
        return lines
    emitted.add(name)

    # Build the interface
    description = schema.get("description", "").split("\n")[0]
    if description:
        lines.append(f"/** {description} */")

    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))

    lines.append(f"export interface {name} {{")

    for prop_name, prop_def in properties.items():
        ts_type = json_type_to_ts(prop_def, defs)
        optional = prop_name not in required_fields
        opt_marker = "?" if optional else ""
        prop_desc = prop_def.get("description", "")
        if prop_desc:
            lines.append(f"\t/** {prop_desc} */")
        lines.append(f"\t{prop_name}{opt_marker}: {ts_type};")

    lines.append("}")
    lines.append("")

    return lines


def generate_typescript(schemas: dict[str, dict[str, Any]]) -> str:
    """Generate TypeScript type definitions from a dictionary of JSON Schemas."""
    output_lines: list[str] = [
        "// =============================================================================",
        "// GENERATED FILE - DO NOT EDIT MANUALLY",
        "// =============================================================================",
        "// Generated from backend Pydantic models by scripts/generate-api-types.sh",
        "// Source of truth: services/orchestrator/api/models/",
        "//",
        "// To regenerate: ./scripts/generate-api-types.sh",
        "// To check for drift: ./scripts/check-api-contracts.sh",
        "// =============================================================================",
        "",
    ]

    emitted: set[str] = set()

    for name, schema in schemas.items():
        interface_lines = schema_to_interface(name, schema, emitted)
        output_lines.extend(interface_lines)

    return "\n".join(output_lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert JSON Schema to TypeScript interfaces"
    )
    parser.add_argument("schema_file", type=Path, help="Input JSON Schema file")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output TypeScript file (default: stdout)",
    )
    args = parser.parse_args()

    with open(args.schema_file) as f:
        schemas = json.load(f)

    ts_output = generate_typescript(schemas)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(ts_output)
        print(f"Generated TypeScript types in {args.output}")
    else:
        sys.stdout.write(ts_output)


if __name__ == "__main__":
    main()

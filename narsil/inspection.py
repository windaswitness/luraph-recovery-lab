"""Static literal inspection. Input source is never executed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .lua_lex import decode, location, normalize_number, quote, scan


def inspect_file(input_path, output_dir) -> dict:
    source_bytes = Path(input_path).read_bytes()
    try:
        source = source_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Input must be UTF-8 source; invalid byte at offset {exc.start}") from exc
    tokens = list(scan(source))
    rendered, strings, blobs = [], [], {}
    for kind, raw, offset in tokens:
        value = raw
        if kind in ("string", "long"):
            decoded = decode(raw)
            value = quote(decoded)
            if decode(value) != decoded:
                raise AssertionError("Internal literal round-trip failure")
            line, column = location(source, offset)
            row = {"index": len(strings), "source_character_offset": offset,
                   "line": line, "column": column, "bytes": len(decoded),
                   "text": decoded.decode("utf-8", errors="backslashreplace")}
            if len(decoded) >= 1024:
                name = f"blob_{len(strings):04d}.bin"
                blobs[name] = decoded
                row["blob_file"] = name
            strings.append(row)
        elif kind == "number":
            value = normalize_number(raw)
        rendered.append(value)
        if kind == "comment" or value in (";", "then", "do", "else", "end", "repeat"):
            rendered.append("\n")
    result = {
        "schema_version": 1, "operation": "inspect", "executed_input": False,
        "input_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "input_bytes": len(source_bytes), "tokens": len(tokens), "strings": len(strings),
        "large_blobs": len(blobs), "offset_unit": "Unicode characters after optional UTF-8 BOM",
        "status": "Static literal normalization only; this does not recover the original program or make it safe to run.",
        "files": ["normalized.lua", "strings.json", *blobs, "manifest.json"],
    }
    destination = Path(output_dir)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("Output directory must be new or empty")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "normalized.lua").write_text(" ".join(rendered), encoding="utf-8")
    (destination / "strings.json").write_text(json.dumps(strings, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    for name, data in blobs.items():
        (destination / name).write_bytes(data)
    (destination / "manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result

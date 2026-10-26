"""Structural inventory of Luau bytecode v6/types v3, not a decompiler."""
from __future__ import annotations

import json
from pathlib import Path
import struct

from .unpack import MAX_BYTES, digest, read_bounded

MAX_ITEMS = 1_000_000


class Reader:
    def __init__(self, data: bytes):
        if len(data) > MAX_BYTES:
            raise ValueError("Bytecode exceeds byte budget")
        self.data, self.pos = data, 0
        self.items_left = MAX_ITEMS

    def take(self, size: int) -> bytes:
        if size < 0 or size > len(self.data) - self.pos:
            raise ValueError(f"Truncated bytecode at offset {self.pos}, need {size} bytes")
        result = self.data[self.pos:self.pos + size]
        self.pos += size
        return result

    def byte(self) -> int:
        return self.take(1)[0]

    def varint(self) -> int:
        result = 0
        for i in range(5):
            byte = self.byte()
            if i == 4 and byte > 15:
                raise ValueError("Varint exceeds uint32")
            result |= (byte & 127) << (7 * i)
            if byte < 128:
                if i and byte == 0:
                    raise ValueError("Noncanonical varint")
                return result
        raise ValueError("Unterminated varint")

    def count(self, minimum_bytes=1) -> int:
        count = self.varint()
        if count > self.items_left or count * minimum_bytes > len(self.data) - self.pos:
            raise ValueError("Count exceeds remaining input or item budget")
        self.items_left -= count
        return count

    def flag(self) -> bool:
        value = self.byte()
        if value not in (0, 1):
            raise ValueError("Expected boolean flag")
        return bool(value)

    def block(self) -> bytes:
        return self.take(self.varint())


def inspect_bytes(data: bytes) -> dict:
    r = Reader(data)
    version, types = r.byte(), r.byte()
    if (version, types) != (6, 3):
        raise ValueError(f"Unsupported bytecode/type version: {version}/{types}; expected 6/3")
    strings = [r.block() for _ in range(r.count())]

    def string_ref(optional=False):
        value = r.varint()
        if not (0 if optional else 1) <= value <= len(strings):
            raise ValueError(f"Invalid string reference: {value}")
        return value

    usertypes = {}
    while True:
        tag = r.byte()
        if tag == 0:
            break
        if tag in usertypes:
            raise ValueError("Duplicate userdata type tag")
        usertypes[tag] = string_ref()
    count = r.count(minimum_bytes=13)
    if count == 0:
        raise ValueError("Bytecode has no prototypes")
    protos = []
    for index in range(count):
        stack, params, upvalues = r.byte(), r.byte(), r.byte()
        vararg, flags = r.flag(), r.byte()
        if stack == 0 or params > stack:
            raise ValueError("Invalid stack/parameter counts")
        typeinfo = r.block()
        code_size = r.count(minimum_bytes=4)
        code = r.take(code_size * 4)
        if not code_size:
            raise ValueError("Prototype has no code words")
        constants = []
        for _ in range(r.count()):
            tag = r.byte()
            if tag == 0:
                constant = {"kind": "nil"}
            elif tag == 1:
                constant = {"kind": "boolean", "value": r.flag()}
            elif tag == 2:
                constant = {"kind": "number", "ieee754_le_hex": r.take(8).hex()}
            elif tag == 3:
                constant = {"kind": "string", "string_id": string_ref()}
            elif tag == 4:
                constant = {"kind": "import", "packed_id": struct.unpack("<I", r.take(4))[0]}
            elif tag == 5:
                constant = {"kind": "table", "keys": [r.varint() for _ in range(r.count())]}
            elif tag == 6:
                constant = {"kind": "closure", "prototype_id": r.varint()}
            elif tag == 7:
                constant = {"kind": "vector", "ieee754_le_hex": r.take(16).hex()}
            else:
                raise ValueError(f"Unsupported constant tag {tag} at offset {r.pos - 1}")
            constants.append(constant)
        children = [r.varint() for _ in range(r.count())]
        line, name = r.varint(), string_ref(optional=True)
        has_lines = r.flag()
        if has_lines:
            gap = r.byte()
            if gap > 31:
                raise ValueError("Invalid line info gap")
            r.take(code_size)
            r.take((((code_size - 1) >> gap) + 1) * 4)
        has_debug = r.flag()
        if has_debug:
            for _ in range(r.count(minimum_bytes=4)):
                string_ref()
                start, end, register = r.varint(), r.varint(), r.byte()
                if not 0 <= start <= end <= code_size or register >= stack:
                    raise ValueError("Invalid debug local range")
            debug_upvalues = r.count()
            if debug_upvalues != upvalues:
                raise ValueError("Debug upvalue count mismatch")
            for _ in range(debug_upvalues):
                string_ref()
        for c in constants:
            if c["kind"] == "table" and any(k >= len(constants) for k in c["keys"]):
                raise ValueError("Invalid table constant reference")
            if c["kind"] == "closure" and c["prototype_id"] >= index:
                raise ValueError("Closure must reference an earlier prototype")
        if any(child >= index for child in children):
            raise ValueError("Child must reference an earlier prototype")
        protos.append({
            "id": index, "stack": stack, "params": params, "upvalues": upvalues,
            "vararg": vararg, "flags": flags, "typeinfo_hex": typeinfo.hex(),
            "code_words": code_size, "code_le_hex": code.hex(), "constants": constants,
            "children": children, "line_defined": line, "name_string_id": name,
            "has_line_info": has_lines, "has_debug_info": has_debug,
        })
    root = r.varint()
    if root >= count:
        raise ValueError("Invalid root prototype")
    if r.pos != len(data):
        raise ValueError(f"Trailing data: {len(data) - r.pos} bytes")
    return {
        "status": "structural-inventory", "version": version, "types_version": types,
        "sha256": digest(data), "bytes_consumed": r.pos, "root": root,
        "strings": [{"id": i + 1, "hex": value.hex()} for i, value in enumerate(strings)],
        "userdata_types": usertypes, "prototypes": protos, "executed_input": False,
        "diagnostics": [
            "Code words are opaque: opcode semantics and AUX boundaries are not decoded.",
            "Type metadata and import IDs are preserved, not semantically validated.",
            "Structural parsing is not proof that bytecode is executable or correctly recovered.",
            "This inventory is not a column-vm-v1 capture and cannot be passed to recover.",
        ],
    }


def run(input_path: Path, output_dir: Path):
    inventory = inspect_bytes(read_bounded(input_path))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Output directory must be empty")
    (output / "bytecode.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return {key: inventory[key] for key in ("status", "version", "types_version", "bytes_consumed",
                                           "sha256", "executed_input", "diagnostics")} | {
        "prototypes": len(inventory["prototypes"]), "strings": len(inventory["strings"]),
        "artifact": "bytecode.json",
    }

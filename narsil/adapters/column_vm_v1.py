"""One observed column-VM opcode/layout adapter, NOT a version detector.

The profile records independently recovered instruction semantics. It contains
no application constants, encrypted payload, original loader, or game source.
Inputs must already be captured/materialized by an analyst-controlled process.
"""
from __future__ import annotations

import math
from pathlib import Path
import json

from .selfmod import resolve

PROFILE = "column-vm-v1"
ALIASES = {8: 97, 16: 60, 36: 3, 107: 19}
BRANCH_COLUMN = {
    7: 11, 12: 2, 25: 11, 27: 8, 29: 2, 32: 2, 48: 2,
    52: 2, 55: 2, 62: 11, 66: 2, 68: 2, 89: 11, 91: 8,
    102: 11, 116: 8, 118: 11,
}
RETURN_OPS = {13, 24, 38, 54, 58, 78, 86, 109}
INTERNAL_OPS = {10, 34, 76, 112, 119}


class Capture:
    """A run-local graph and resolved prototype collection.

    ``nodes`` is an array of tables; each table is an array of [key, value]
    pairs. {"ref": N} refers to nodes[N-1]. Strings are {"hex": "..."}.
    {"nil": true} and {"number": "nan"|"+inf"|"-inf"} are supported values.
    No lazy lookup or captured executable code is evaluated by this loader.
    """

    def __init__(self, document):
        if not isinstance(document, dict) or not isinstance(document.get("nodes"), list):
            raise ValueError("capture requires an object with root and nodes")
        rows = document["nodes"]
        if len(rows) > 100_000:
            raise ValueError("capture exceeds 100000 table nodes")
        tables = [{} for _ in rows]

        def scalar(value, *, key=False):
            if isinstance(value, dict):
                if set(value) == {"ref"}:
                    ref = value["ref"]
                    if type(ref) is not int or not 1 <= ref <= len(tables):
                        raise ValueError("invalid graph reference")
                    if key:
                        raise ValueError("table-valued keys are not supported by this adapter")
                    return tables[ref-1]
                if set(value) == {"hex"} and isinstance(value["hex"], str):
                    try:
                        return bytes.fromhex(value["hex"])
                    except ValueError as exc:
                        raise ValueError("invalid hex string") from exc
                if set(value) == {"nil"} and value["nil"] is True:
                    return None
                if set(value) == {"number"} and value["number"] in ("nan", "+inf", "-inf"):
                    return {"nan": math.nan, "+inf": math.inf, "-inf": -math.inf}[value["number"]]
                raise ValueError("unknown graph scalar tag")
            if value is None or isinstance(value, (str, bool, int, float)):
                if isinstance(value, str):
                    raise ValueError("Lua strings must use the hex tag")
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("nonfinite numbers must use a number tag")
                return value
            raise ValueError("unsupported graph scalar")

        entries = 0
        for table, pairs in zip(tables, rows):
            if not isinstance(pairs, list):
                raise ValueError("each graph table must be an array of pairs")
            for pair in pairs:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValueError("graph table entry must be [key, value]")
                key = scalar(pair[0], key=True)
                # Python bool/int keys collide whereas Lua true/1 do not.
                if key is None or isinstance(key, bool) or (isinstance(key, float) and not math.isfinite(key)):
                    raise ValueError("this profile requires finite numeric or byte-string table keys")
                if key in table:
                    raise ValueError("duplicate graph table key")
                table[key] = scalar(pair[1])
                entries += 1
                if entries > 3_000_000:
                    raise ValueError("capture exceeds 3000000 table entries")
        self.root = scalar(document.get("root"))
        self.protos = [p for p in tables if isinstance(p.get(9), dict)
                       and type(p.get(4)) is int and type(p.get(7)) is int]
        self.ids = {id(p): i for i, p in enumerate(self.protos)}
        if id(self.root) not in self.ids:
            raise ValueError("root does not match column-vm-v1 prototype layout")
        self.root_index = self.ids[id(self.root)]
        if len(self.protos) > 1000:
            raise ValueError("capture exceeds 1000 prototypes")
        for index, proto in enumerate(self.protos):
            for col in (1, 2, 3, 5, 6, 8, 9, 10, 11):
                if not isinstance(proto.get(col), dict):
                    raise ValueError(f"prototype {index} lacks materialized column {col}")
            if len(proto[9]) > 100_000:
                raise ValueError("prototype exceeds 100000 instructions")
            for pc, opcode in proto[9].items():
                if type(pc) is not int or pc < 1 or type(opcode) is not int:
                    raise ValueError("opcode columns require positive integer PCs and integer opcodes")
                proto[9][pc] = ALIASES.get(opcode, opcode)
        if self.root[5]:
            raise ValueError("root external upvalues are unsupported; capture a closed root")
        self.resolution = {"resolved": [], "failed_candidates": []}

    def resolve(self):
        """Evaluate only bounded, recognized instruction-column mutations."""
        for index, proto in enumerate(self.protos):
            for pc, opcode in list(proto[9].items()):
                if opcode != 39 or proto[8].get(pc) != pc:
                    continue
                try:
                    writes, end, visited = resolve(proto, pc)
                except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                    self.resolution["failed_candidates"].append({"function": index, "pc": pc, "reason": str(exc)})
                    continue
                for (column, target), value in writes.items():
                    proto[column][target] = value
                proto[8][pc] = end
                self.resolution["resolved"].append({"function": index, "pc": pc, "end": end, "writes": len(writes)})
            live = self.reachable(proto)
            unresolved = [(pc, proto[9][pc]) for pc in sorted(live) if proto[9][pc] in INTERNAL_OPS]
            if unresolved:
                raise ValueError(f"prototype {index}: unresolved VM-internal instructions {unresolved[:8]}")

    @staticmethod
    def reachable(proto):
        def destination(value):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value:
                raise ValueError("instruction target must be a finite integer")
            value = int(value)
            if value not in proto[9]:
                raise ValueError(f"reachable instruction target {value} is absent from opcode stream")
            return value

        destination(1)
        pending = [1]
        seen = set()
        while pending:
            pc = pending.pop()
            while pc in proto[9] and pc not in seen:
                seen.add(pc)
                opcode = proto[9][pc]
                if not 0 <= opcode <= 120:
                    raise ValueError(f"unsupported op {opcode} at {pc}")
                if opcode in (39, 22, 101):
                    pc = destination(proto[2 if opcode == 101 else 8][pc] + 1)
                    continue
                if opcode in BRANCH_COLUMN:
                    pending.append(destination(proto[BRANCH_COLUMN[opcode]][pc] + 1))
                if opcode in RETURN_OPS:
                    break
                pc = destination(pc + 1)
        return seen


def load(path):
    """Read JSON only. This never imports or executes the input."""
    path = Path(path)
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("capture exceeds 128 MiB")
    return Capture(json.loads(path.read_text(encoding="utf8")))

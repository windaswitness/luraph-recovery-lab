"""Offline graph-to-Luau reconstruction for one explicit experimental profile."""
from __future__ import annotations

import json
from pathlib import Path

from .adapters.column_vm_v1 import PROFILE, load
from .engine.lift import Function, Structurer, encode
from .engine.render import render
from .engine.trace import check


def run(capture_path, output_dir, profile=PROFILE):
    """Reconstruct an intermediate non-invoked Luau root function.

    The capture must match the observed opcode/layout profile. This is not an
    arbitrary-source deobfuscator and does not identify a Luraph version.
    Unknown opcodes, unresolved VM operations, invalid CFGs and bounded trace
    mismatches raise ValueError/RuntimeError. No Lua, subprocess, network, or
    live Studio operation is executed. Results still require analyst review.
    """
    if profile != PROFILE:
        raise ValueError(f"unknown profile: {profile}")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("output directory must be empty")
    context = load(capture_path)
    try:
        context.resolve()
        parents = {}
        functions = [Function(i, p, context, parents) for i, p in enumerate(context.protos)]
        # A prototype reused at different lexical sites needs separate closure
        # instantiations/naming contexts; the current renderer does not clone it.
        sites = {}
        for function in functions:
            for pc, (body, term) in function.nodes.items():
                for op in body:
                    if op.kind == "set" and op.args[1][0] == "closure":
                        child = op.args[1][1]
                        if child in sites and sites[child] != (function.index, pc):
                            raise ValueError(f"prototype {child} is reused at multiple lexical sites")
                        sites[child] = (function.index, pc)
        structured = {}
        strategies = {}
        for function in functions:
            errors = []
            for prefer_postdom in (False, True):
                try:
                    structurer = Structurer(function, prefer_postdom=prefer_postdom)
                    body = structurer.emit(function.entry)
                    mismatch = check(function, body)
                    if mismatch:
                        raise ValueError(f"abstract CFG trace mismatch: {mismatch}")
                    structured[function.index] = body
                    strategies[function.index] = "postdom" if prefer_postdom else "nearest-continuation"
                    break
                except (ValueError, RuntimeError, KeyError, RecursionError) as exc:
                    errors.append(str(exc))
            else:
                raise ValueError(f"cannot structure prototype {function.index}: {errors}")
        code = "-- Experimental intermediate reconstruction; review before use.\n" + render(context, functions, parents, structured)
    except (KeyError, TypeError, AssertionError, IndexError, RecursionError) as exc:
        raise ValueError(f"capture does not satisfy {PROFILE}: {exc}") from exc
    artifacts = {
        "luau": "reconstructed.luau",
        "structured_ir": "structured.json",
        "selfmod_log": "selfmod.json",
        "report": "report.json",
    }
    result = {
        "status": "intermediate",
        "profile": profile,
        "artifacts": artifacts,
        "stats": {
            "prototypes": len(functions),
            "reachable_instructions": sum(len(f.live) for f in functions),
            "resolved_islands": len(context.resolution["resolved"]),
            "abstract_trace_cases": len(functions)*30,
            "luau_bytes": len(code.encode("utf8")),
        },
        "diagnostics": [
            "Experimental profile for one observed opcode/layout variant; not all Luraph 14.3 files.",
            "Names are generated. Structured CFG traces are bounded checks, not execution equivalence proof.",
            "Output returns the reconstructed root function without invoking it; application startup is manual.",
        ],
        "structuring_strategies": strategies,
    }
    (output / artifacts["luau"]).write_text(code, encoding="utf8")
    (output / artifacts["structured_ir"]).write_text(json.dumps(encode(structured), indent=2), encoding="utf8")
    (output / artifacts["selfmod_log"]).write_text(json.dumps(context.resolution, indent=2), encoding="utf8")
    (output / artifacts["report"]).write_text(json.dumps(result, indent=2), encoding="utf8")
    return result

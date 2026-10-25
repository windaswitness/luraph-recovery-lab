"""Generate an exact-profile capture plan; never execute the generated code.

Interception and cooperative guards are NOT a safety sandbox. A loader can
perform side effects before the intercepted call; a guard cannot preempt a
native call, recursion, or a straight-line computation between checkpoints.
"""
from __future__ import annotations

import hashlib
from importlib import resources
import json
import math
from pathlib import Path
import re

from .lua_lex import scan


class CapturePlanError(ValueError):
    """The source does not match an explicit, valid capture profile."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CapturePlanError(f"Duplicate profile key: {key}")
        result[key] = value
    return result


def _keys(value, allowed, label):
    if not isinstance(value, dict):
        raise CapturePlanError(f"{label} must be an object")
    unexpected = set(value) - set(allowed)
    if unexpected:
        raise CapturePlanError(f"Unknown {label} keys: {', '.join(sorted(unexpected))}")


def _text(value, label):
    if not isinstance(value, str) or not value:
        raise CapturePlanError(f"{label} must be a nonempty string")
    return value


def _positive_int(value, label, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise CapturePlanError(f"{label} must be an integer from 1 to {maximum}")
    return value


def _guard(source, settings):
    _keys(settings, {"instruction_limit", "time_limit_seconds", "hook_name", "yield_every"}, "guard")
    limit = _positive_int(settings.get("instruction_limit"), "guard.instruction_limit", 1_000_000_000)
    seconds = settings.get("time_limit_seconds")
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 3600:
        raise CapturePlanError("guard.time_limit_seconds must be a finite number in (0, 3600]")
    every = settings.get("yield_every", 1000)
    if type(every) is not int or not 0 <= every <= 1_000_000_000:
        raise CapturePlanError("guard.yield_every must be an integer from 0 to 1000000000")
    name = settings.get("hook_name", "__capture_guard")
    if not isinstance(name, str) or not re.fullmatch(r"__[A-Za-z_][A-Za-z_0-9]*", name):
        raise CapturePlanError("guard.hook_name must be an identifier beginning with __")
    tokens = list(scan(source))
    if any(kind == "identifier" and raw == name for kind, raw, _ in tokens):
        raise CapturePlanError(f"Guard identifier already occurs in source: {name}")
    insertions = [offset + len(raw) for kind, raw, offset in tokens
                  if kind == "identifier" and raw in ("do", "repeat")]
    transformed = source
    for offset in reversed(insertions):
        transformed = transformed[:offset] + f" {name}(); " + transformed[offset:]
    # Internal names are scoped inside the initializer, outside the loader.
    prefix = f'''-- Generated capture PLAN. NOT a sandbox. Review before any execution.
local {name} = (function()
    local count = 0
    local clock, fail = os.clock, error
    local started = clock()
    local canYield = coroutine and coroutine.isyieldable
    local waitForTask = task and task.wait
    return function()
        count = count + 1
        if count > {limit} then fail("capture checkpoint budget exceeded", 0) end
        if clock() - started > {seconds!r} then fail("capture elapsed-time budget exceeded", 0) end
        if {every} > 0 and count % {max(every, 1)} == 0 and canYield and canYield() and waitForTask then
            waitForTask()
        end
    end
end)()
{name}()
'''
    return prefix + transformed, len(insertions), {
        "instruction_limit": limit, "time_limit_seconds": seconds,
        "hook_name": name, "yield_every": every,
        "counting_unit": "entry checkpoints at do/repeat blocks, not VM or CPU instructions",
    }


def plan_capture(input_path, profile_path, output_dir) -> dict:
    """Validate the input hash and generate files from one exact capture profile.

    ``intercept.returns`` defaults to ``prototype``. Any custom exposure must
    use ``reviewed_custom`` and ``reviewed: true``. These are review declarations,
    not proof that an arbitrary replacement or loader is safe.
    """
    source_bytes = Path(input_path).read_bytes()
    profile_bytes = Path(profile_path).read_bytes()
    try:
        profile = json.loads(profile_bytes.decode("utf-8-sig"), object_pairs_hook=_object,
                             parse_constant=lambda value: (_ for _ in ()).throw(CapturePlanError(f"Nonfinite JSON number: {value}")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CapturePlanError(f"Invalid UTF-8 JSON capture profile: {exc}") from exc
    _keys(profile, {"schema_version", "name", "input_sha256", "intercept", "strip_tail", "guard", "include_graph_serializer"}, "profile")
    if type(profile.get("schema_version")) is not int or profile["schema_version"] != 1:
        raise CapturePlanError("Only capture profile schema_version 1 is supported")
    name = _text(profile.get("name"), "profile.name")
    expected = profile.get("input_sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise CapturePlanError("profile.input_sha256 must contain exactly 64 hexadecimal characters")
    digest = hashlib.sha256(source_bytes).hexdigest()
    if digest != expected.lower():
        raise CapturePlanError(f"Input SHA-256 mismatch: expected {expected.lower()}, found {digest}")
    try:
        source = source_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CapturePlanError(f"Input must be UTF-8 source; invalid byte at offset {exc.start}") from exc
    tokens = list(scan(source))
    intercept = profile.get("intercept")
    _keys(intercept, {"marker", "replacement", "returns", "reviewed"}, "intercept")
    marker = _text(intercept.get("marker"), "intercept.marker")
    replacement = _text(intercept.get("replacement"), "intercept.replacement")
    mode = intercept.get("returns", "prototype")
    reviewed = intercept.get("reviewed", False)
    if type(reviewed) is not bool:
        raise CapturePlanError("intercept.reviewed must be boolean")
    if mode not in ("prototype", "reviewed_custom"):
        raise CapturePlanError("intercept.returns must be prototype or reviewed_custom")
    if mode != "prototype" and reviewed is not True:
        raise CapturePlanError("Custom return exposure requires intercept.reviewed: true")
    replacement_tokens = [token for token in scan(replacement) if token[0] != "comment"]
    if mode == "prototype" and (not replacement_tokens or replacement_tokens[0][1] != "return"):
        raise CapturePlanError("Prototype-only interception must begin with return")
    occurrences = [match.start() for match in re.finditer("(?=" + re.escape(marker) + ")", source)]
    if len(occurrences) != 1:
        raise CapturePlanError(f"Interception marker must occur exactly once; found {len(occurrences)}")
    at = occurrences[0]
    first_code = at + len(marker) - len(marker.lstrip())
    last_code = at + len(marker.rstrip())
    if first_code == last_code:
        raise CapturePlanError("Interception marker must contain code")
    for kind, raw, offset in tokens:
        if offset <= first_code < offset + len(raw):
            if kind in ("string", "long", "comment") or offset != first_code:
                raise CapturePlanError("Interception marker starts inside a token, string, or comment")
            break
    for kind, raw, offset in tokens:
        if offset < last_code <= offset + len(raw):
            if kind == "comment" or offset + len(raw) != last_code:
                raise CapturePlanError("Interception marker ends inside a token or comment")
            break
    stripped = ""
    if "strip_tail" in profile:
        tail = profile["strip_tail"]
        _keys(tail, {"suffix"}, "strip_tail")
        stripped = _text(tail.get("suffix"), "strip_tail.suffix")
        if not source.endswith(stripped):
            raise CapturePlanError("Exact strip_tail suffix does not match input")
        if at + len(marker) > len(source) - len(stripped):
            raise CapturePlanError("Interception marker overlaps the stripped tail")
        source = source[:-len(stripped)]
    transformed = source[:at] + replacement + source[at + len(marker):]
    guarded, checkpoints, guard = _guard(transformed, profile.get("guard"))
    include_serializer = profile.get("include_graph_serializer", False)
    if type(include_serializer) is not bool:
        raise CapturePlanError("include_graph_serializer must be boolean")
    files = {"capture.luau": guarded.encode("utf-8")}
    if include_serializer:
        files["serialize_graph.luau"] = resources.files("luraph_lab").joinpath("resources", "graph_serializer.luau").read_bytes()
    result = {
        "schema_version": 1, "operation": "capture-plan", "profile_name": name,
        "input_sha256": digest, "profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
        "input_bytes": len(source_bytes), "executed_input": False,
        "interception": {"occurrences": 1, "source_character_offset": at,
                         "returns": mode, "reviewed_custom": mode == "reviewed_custom" and reviewed},
        "stripped_tail_characters": len(stripped), "inserted_loop_checkpoints": checkpoints,
        "guard": guard,
        "files": {key: {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()} for key, value in files.items()},
        "status": "Plan only. No source was executed or compiled.",
        "warnings": [
            "Capture is NOT a safety sandbox. The loader may execute side effects before interception.",
            "Exact hashes and unique markers verify identity, not harmlessness or semantic correctness.",
            "Guard budgets are cooperative checkpoint limits, not preemptive instruction or wall-clock limits.",
            "Prototype-only is a profile review declaration; inspect the replacement and decoder before execution.",
        ],
    }
    destination = Path(output_dir)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise CapturePlanError("Output directory must be new or empty")
    destination.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        (destination / filename).write_bytes(content)
    (destination / "manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result

"""Bounded, declarative payload transforms. Input Lua is never executed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

MAX_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_LAYERS = 32


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bounded(path: Path, limit: int = MAX_BYTES) -> bytes:
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Input exceeds {limit} bytes")
    return data


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate profile key: {key}")
        result[key] = value
    return result


def _keys(value, allowed, required):
    if not isinstance(value, dict):
        raise ValueError("Profile and layers must be JSON objects")
    if set(value) - set(allowed) or set(required) - set(value):
        raise ValueError(f"Invalid keys; allowed: {sorted(allowed)}, required: {sorted(required)}")


def _integer(value, low=0, high=MAX_BYTES):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"Expected integer in [{low}, {high}]")
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected lowercase SHA-256")
    return value


def load_profile(path: Path):
    profile = json.loads(read_bounded(path, 65536).decode("utf-8"), object_pairs_hook=_object)
    validate_profile(profile)
    return profile


def validate_profile(profile):
    fields = {"schema_version", "name", "input_sha256", "output_sha256", "layers"}
    _keys(profile, fields, fields)
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ValueError("Unsupported unpack profile schema")
    if not isinstance(profile["name"], str) or not profile["name"].strip():
        raise ValueError("Profile name must be nonempty")
    _hash(profile["input_sha256"])
    _hash(profile["output_sha256"])
    if not isinstance(profile["layers"], list) or not 1 <= len(profile["layers"]) <= MAX_LAYERS:
        raise ValueError(f"Expected 1..{MAX_LAYERS} layers")


def transform(data: bytes, layer: dict) -> bytes:
    """Apply one explicit transform, with zero-based byte positions."""
    if len(data) > MAX_BYTES:
        raise ValueError("Layer input is too large")
    if not isinstance(layer, dict):
        raise ValueError("Layer must be an object")
    op = layer.get("op")
    parameters = {
        "base85": {"alphabet"},
        "nibble81-v1": {"salt"},
        "rolling-xor-v1": {"seed"},
        "xor-linear": {"multiplier", "offset"},
        "swap-pairs": {"skip_mod", "skip_remainder"},
        "stride": {"start", "step", "count"},
        "slice": {"start", "length"},
    }
    if not isinstance(op, str) or op not in parameters:
        raise ValueError(f"Unsupported transform: {op!r}")
    required = parameters[op] | {"op"}
    _keys(layer, required | {"output_sha256"}, required)
    if "output_sha256" in layer:
        _hash(layer["output_sha256"])
    if op == "base85":
        alphabet = layer["alphabet"]
        if not isinstance(alphabet, str):
            raise ValueError("base85 alphabet must be an ASCII string")
        alphabet = alphabet.encode("ascii")
        if len(alphabet) != 85 or len(set(alphabet)) != 85 or len(data) % 5:
            raise ValueError("base85 requires 85 unique symbols and complete groups of five")
        lookup = {byte: i for i, byte in enumerate(alphabet)}
        result = bytearray()
        for pos in range(0, len(data), 5):
            value = 0
            for byte in data[pos:pos + 5]:
                if byte not in lookup:
                    raise ValueError(f"Unknown base85 symbol at group offset {pos}")
                value = value * 85 + lookup[byte]
            if value > 0xffffffff:
                raise ValueError("base85 group overflows uint32")
            result.extend(value.to_bytes(4, "big"))
        result = bytes(result)
    elif op == "nibble81-v1":
        salt = _integer(layer["salt"], 0, 0xffffffff)
        if len(data) < 81 or len(set(data[:81])) != 81 or (len(data) - 81) % 2:
            raise ValueError("nibble81 requires an 81-byte unique alphabet and symbol pairs")
        lookup = {byte: i for i, byte in enumerate(data[:81])}
        result = bytearray()
        for i, pos in enumerate(range(81, len(data), 2)):
            if data[pos] not in lookup or data[pos + 1] not in lookup:
                raise ValueError("Unknown nibble81 symbol")
            a = (lookup[data[pos]] - (salt + i * 17 + i // 7 * 11)) % 81
            b = (lookup[data[pos + 1]] - (salt * 3 + i * 31 + i // 5 * 13 + 7)) % 81
            if a >= 16 or b >= 16:
                raise ValueError("Decoded nibble outside 0..15; wrong profile or corrupt payload")
            result.append(a * 16 + b)
        result = bytes(result)
    elif op == "rolling-xor-v1":
        seed = _integer(layer["seed"], 0, 255)
        result = bytearray()
        for i, byte in enumerate(data):
            decoded = byte ^ seed
            result.append(decoded)
            seed = (seed * 73 + decoded + i * 17 + 41) & 255
        result = bytes(result)
    elif op == "xor-linear":
        multiplier = _integer(layer["multiplier"], 0, 255)
        offset = _integer(layer["offset"], 0, 255)
        result = bytes(byte ^ ((i * multiplier + offset) & 255) for i, byte in enumerate(data))
    elif op == "swap-pairs":
        modulus = _integer(layer["skip_mod"], 1, MAX_BYTES)
        remainder = _integer(layer["skip_remainder"], 0, modulus - 1)
        result = bytearray(data)
        for i in range(len(result) // 2):
            if i % modulus != remainder:
                result[2 * i], result[2 * i + 1] = result[2 * i + 1], result[2 * i]
        result = bytes(result)
    elif op == "stride":
        start = _integer(layer["start"], 0, len(data))
        step = _integer(layer["step"], 1, MAX_BYTES)
        count = _integer(layer["count"])
        if count and start + (count - 1) * step >= len(data):
            raise ValueError("Stride exceeds input boundary")
        result = data[start:start + count * step:step]
    else:
        start = _integer(layer["start"], 0, len(data))
        length = _integer(layer["length"], 0, len(data) - start)
        result = data[start:start + length]
    if "output_sha256" in layer and digest(result) != layer["output_sha256"]:
        raise ValueError(f"{op} output SHA-256 mismatch")
    return result


def decode_layers(data: bytes, profile: dict):
    validate_profile(profile)
    if len(data) > MAX_BYTES:
        raise ValueError("Input is too large")
    if digest(data) != profile["input_sha256"]:
        raise ValueError("Input SHA-256 mismatch")
    stages = []
    total = 0
    for i, layer in enumerate(profile["layers"], 1):
        # All current transforms preserve or shrink input size.
        if total + len(data) > MAX_TOTAL_BYTES:
            raise ValueError("Total intermediate byte budget exceeded")
        data = transform(data, layer)
        total += len(data)
        stages.append((f"layer-{i:02d}.bin", data, layer["op"]))
    if digest(data) != profile["output_sha256"]:
        raise ValueError("Final output SHA-256 mismatch")
    return data, stages


def run(input_path: Path, profile_path: Path, output_dir: Path):
    data, stages = decode_layers(read_bounded(input_path), load_profile(profile_path))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Output directory must be empty")
    report = {
        "status": "unpacked", "executed_input": False,
        "output": "payload.bin", "output_bytes": len(data), "output_sha256": digest(data),
        "layers": [{"file": name, "op": op, "bytes": len(blob), "sha256": digest(blob)}
                   for name, blob, op in stages],
        "diagnostics": ["Unpacking does not interpret VM instructions or prove program equivalence."],
    }
    for name, blob, _ in stages:
        (output / name).write_bytes(blob)
    (output / "payload.bin").write_bytes(data)
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report

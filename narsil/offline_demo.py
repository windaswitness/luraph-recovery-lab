"""Author a nested payload from the public synthetic graph, then recover it."""
from __future__ import annotations

import base64
from importlib import resources
import json
from pathlib import Path

from .unpack import digest, transform, run as unpack
from .pipeline import run as recover

ALPHABET85 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_" + chr(96) + "{|}~"


def fixture(payload: bytes):
    """The encoder exists only to make a reproducible, original test fixture."""
    stride = bytearray([0xa5] * (len(payload) * 3))
    stride[0::3] = payload
    stride.extend(b"\0" * (-len(stride) % 4))
    mixed = transform(bytes(stride), {"op": "xor-linear", "multiplier": 13, "offset": 77})
    mixed = transform(mixed, {"op": "swap-pairs", "skip_mod": 3, "skip_remainder": 0})
    encoded = base64.b85encode(mixed)
    rolling, seed = bytearray(), 37
    for i, byte in enumerate(encoded):
        rolling.append(byte ^ seed)
        seed = (seed * 73 + byte + i * 17 + 41) & 255
    alphabet, salt = bytes(range(33, 114)), 19
    packed = bytearray(alphabet)
    for i, byte in enumerate(rolling):
        packed.append(alphabet[((byte >> 4) + salt + i * 17 + i // 7 * 11) % 81])
        packed.append(alphabet[((byte & 15) + salt * 3 + i * 31 + i // 5 * 13 + 7) % 81])
    layers = [
        {"op": "nibble81-v1", "salt": salt},
        {"op": "rolling-xor-v1", "seed": 37},
        {"op": "base85", "alphabet": ALPHABET85},
        {"op": "swap-pairs", "skip_mod": 3, "skip_remainder": 0},
        {"op": "xor-linear", "multiplier": 13, "offset": 77},
        {"op": "stride", "start": 0, "step": 3, "count": len(payload)},
    ]
    current = bytes(packed)
    for layer in layers:
        current = transform(current, layer)
        layer["output_sha256"] = digest(current)
    return bytes(packed), {
        "schema_version": 1, "name": "Authored nested envelope over synthetic column VM graph",
        "input_sha256": digest(packed), "output_sha256": digest(payload), "layers": layers,
    }


def run(output_dir: Path):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Output directory must be empty")
    graph = resources.files("narsil").joinpath("resources/synthetic_capture.json").read_bytes()
    packed, profile = fixture(graph)
    (output / "packed.bin").write_bytes(packed)
    (output / "unpack-profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    unpacked = unpack(output / "packed.bin", output / "unpack-profile.json", output / "unpacked")
    recovered = recover(output / "unpacked/payload.bin", output / "recovered")
    report = {
        "status": "synthetic-demo", "executed_input": False,
        "unpack": unpacked, "recovery": recovered,
        "diagnostics": [
            "Payload is the authored column-vm-v1 graph, not a private buffer VM or native Luau file.",
            "The envelope demonstrates nested unpacking; it does not add a universal VM adapter.",
        ],
    }
    (output / "demo-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report

import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from narsil.offline_demo import ALPHABET85, fixture
from narsil.unpack import decode_layers, digest, load_profile, run, transform


class UnpackTests(unittest.TestCase):
    def test_known_transform_vectors(self):
        self.assertEqual(transform(bytes([0, 1, 2, 255]),
                         {"op": "xor-linear", "multiplier": 3, "offset": 7}),
                         bytes([7, 11, 15, 239]))
        self.assertEqual(transform(bytes([64, 241, 196]),
                         {"op": "rolling-xor-v1", "seed": 1}), b"ABC")
        self.assertEqual(transform(bytes(range(81)) + bytes([0, 7, 32, 53]),
                         {"op": "nibble81-v1", "salt": 0}), b"\0\xff")
        self.assertEqual(transform(b"abcdefg",
                         {"op": "swap-pairs", "skip_mod": 3, "skip_remainder": 0}), b"abdcfeg")
        self.assertEqual(transform(b"a1b2c3", {"op": "stride", "start": 0, "step": 2, "count": 3}), b"abc")
        self.assertEqual(transform(b"abcdef", {"op": "slice", "start": 2, "length": 3}), b"cde")

    def test_base85_matches_independent_standard_library(self):
        plain = bytes(range(256))
        self.assertEqual(transform(base64.b85encode(plain),
                         {"op": "base85", "alphabet": ALPHABET85}), plain)

    def test_nested_roundtrip_binary_and_empty_data(self):
        for plain in (b"", b"\0", bytes(range(256)), b'error("must not execute")'):
            with self.subTest(size=len(plain)):
                data, profile = fixture(plain)
                result, stages = decode_layers(data, profile)
                self.assertEqual(result, plain)
                self.assertEqual(len(stages), 6)

    def test_hash_mismatches_rejected_at_each_boundary(self):
        data, profile = fixture(b"payload")
        for target in ("input_sha256", "output_sha256", "layer"):
            broken = copy.deepcopy(profile)
            if target == "layer":
                broken["layers"][2]["output_sha256"] = "0" * 64
            else:
                broken[target] = "0" * 64
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                decode_layers(data, broken)

    def test_bad_symbols_lengths_and_overflow_rejected(self):
        cases = [
            (b"0000", {"op": "base85", "alphabet": ALPHABET85}),
            (b"~~~~~", {"op": "base85", "alphabet": ALPHABET85}),
            (b":::::", {"op": "base85", "alphabet": ALPHABET85}),
            (b"x" * 81, {"op": "nibble81-v1", "salt": 0}),
            (bytes(range(81)) + bytes([80, 7]), {"op": "nibble81-v1", "salt": 0}),
            (b"abc", {"op": "stride", "start": 0, "step": 3, "count": 2}),
            (b"abc", {"op": "slice", "start": 2, "length": 2}),
        ]
        for data, layer in cases:
            with self.subTest(layer=layer), self.assertRaises(ValueError):
                transform(data, layer)

    def test_unknown_keys_types_operations_rejected(self):
        cases = [
            {"op": "execute", "code": "print('no')"},
            {"op": "xor-linear", "multiplier": True, "offset": 0},
            {"op": "xor-linear", "multiplier": 1, "offset": 0, "typo": 1},
            {"op": "xor-linear", "multiplier": 1},
            {"op": "swap-pairs", "skip_mod": 0, "skip_remainder": 0},
        ]
        for layer in cases:
            with self.subTest(layer=layer), self.assertRaises(ValueError):
                transform(b"abc", layer)

    def test_resource_budget(self):
        data, profile = fixture(b"payload")
        with patch("narsil.unpack.MAX_TOTAL_BYTES", 4), self.assertRaisesRegex(ValueError, "budget"):
            decode_layers(data, profile)
        with patch("narsil.unpack.MAX_BYTES", 4), self.assertRaisesRegex(ValueError, "large"):
            decode_layers(data, profile)

    def test_artifacts_and_no_partial_success_on_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data, profile = fixture(b"\0example\xff")
            source, config = root / "input.bin", root / "profile.json"
            source.write_bytes(data)
            config.write_text(json.dumps(profile))
            report = run(source, config, root / "out")
            self.assertFalse(report["executed_input"])
            self.assertEqual((root / "out/payload.bin").read_bytes(), b"\0example\xff")
            self.assertEqual(report["output_sha256"], digest(b"\0example\xff"))
            with self.assertRaisesRegex(ValueError, "empty"):
                run(source, config, root / "out")
            profile["output_sha256"] = "0" * 64
            config.write_text(json.dumps(profile))
            with self.assertRaises(ValueError):
                run(source, config, root / "broken")
            self.assertFalse((root / "broken/payload.bin").exists())

    def test_duplicate_and_extra_profile_keys_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profile.json"
            path.write_text('{"name":"first","name":"second"}')
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_profile(path)
            _, profile = fixture(b"a")
            profile["execute"] = True
            path.write_text(json.dumps(profile))
            with self.assertRaisesRegex(ValueError, "Invalid keys"):
                load_profile(path)

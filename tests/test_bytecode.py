import struct
import unittest

from narsil.bytecode import Reader, inspect_bytes


def varint(value):
    output = bytearray()
    while value > 127:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


def chunk(constants=b"", constant_count=0, root=0, children=b"\0", debug=False):
    # Authored v6/types3 container; code words are deliberately opaque to this reader.
    strings = b"\x01\x03a\0\xff"
    header = b"\x06\x03" + strings + b"\0\x01"
    proto = b"\x02\0\0\x01\0" + b"\0" + b"\x01" + struct.pack("<I", 0x00010016)
    proto += varint(constant_count) + constants + children + b"\0\x01"
    if debug:
        proto += b"\x01\x00\x00" + struct.pack("<i", 1)
        proto += b"\x01\x01\x01\x00\x01\x00\x00"
    else:
        proto += b"\0\0"
    return header + proto + varint(root)


class BytecodeTests(unittest.TestCase):
    def test_structural_inventory_preserves_binary_strings(self):
        source = chunk()
        info = inspect_bytes(source)
        self.assertEqual(info["bytes_consumed"], len(source))
        self.assertEqual(info["strings"], [{"id": 1, "hex": "6100ff"}])
        self.assertEqual(info["root"], 0)
        self.assertEqual(info["prototypes"][0]["code_words"], 1)
        self.assertFalse(info["executed_input"])

    def test_constants_and_nonfinite_bits_preserved(self):
        number = struct.pack("<d", float("nan"))
        vector = struct.pack("<4f", 1, 2, 3, 4)
        constants = b"\0\x01\x00\x01\x01\x02" + number + b"\x03\x01\x04" + struct.pack("<I", 42)
        constants += b"\x05\x01\x04\x07" + vector
        values = inspect_bytes(chunk(constants, 8))["prototypes"][0]["constants"]
        self.assertEqual(values[1]["value"], False)
        self.assertEqual(values[2]["value"], True)
        self.assertEqual(values[3]["ieee754_le_hex"], number.hex())
        self.assertEqual(values[6]["keys"], [4])
        self.assertEqual(values[7]["ieee754_le_hex"], vector.hex())

    def test_debug_sections_consumed(self):
        info = inspect_bytes(chunk(debug=True))
        self.assertTrue(info["prototypes"][0]["has_debug_info"])
        self.assertTrue(info["prototypes"][0]["has_line_info"])

    def test_every_truncation_rejected(self):
        valid = chunk(debug=True)
        for size in range(len(valid)):
            with self.subTest(size=size), self.assertRaises(ValueError):
                inspect_bytes(valid[:size])

    def test_invalid_versions_references_tags_and_trailing_bytes(self):
        cases = [b"\x07" + chunk()[1:], chunk() + b"\0", chunk(root=1),
                 chunk(b"\x03\x02", 1), chunk(b"\x08", 1), chunk(b"\x06\x00", 1),
                 chunk(b"\x05\x01\x01", 1), chunk(children=b"\x01\x00")]
        for data in cases:
            with self.subTest(data=data.hex()), self.assertRaises(ValueError):
                inspect_bytes(data)

    def test_varint_boundaries_and_invalid_counts(self):
        self.assertEqual(Reader(b"\xff\xff\xff\xff\x0f").varint(), 0xffffffff)
        for data in (b"\x80\0", b"\xff\xff\xff\xff\x10", b"\x80"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                Reader(data).varint()
        with self.assertRaises(ValueError):
            Reader(varint(0xffffffff)).count()

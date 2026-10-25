"""Authored opcode fixtures only; no recovered application data."""
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from narsil.adapters.column_vm_v1 import Capture
from narsil.pipeline import run


def proto(instructions, upvalues=None):
    result = {key: {} for key in (1, 2, 3, 5, 6, 8, 9, 10, 11)}
    result.update({4: 24, 7: 0})
    result[5] = upvalues or {}
    for pc, instruction in enumerate(instructions, 1):
        opcode, operands = instruction
        result[9][pc] = opcode
        for column, value in operands.items():
            result[column][pc] = value
    return result


def graph(root):
    nodes, ids = [], {}

    def value(item):
        if isinstance(item, dict):
            if id(item) not in ids:
                ids[id(item)] = len(nodes)+1
                rows = []
                nodes.append(rows)
                rows.extend([[value(k), value(v)] for k, v in item.items()])
            return {"ref": ids[id(item)]}
        if isinstance(item, bytes):
            return {"hex": item.hex()}
        return item
    reference = value(root)
    return {"root": reference, "nodes": nodes}


class PipelineTests(unittest.TestCase):
    def recover(self, root):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        capture = directory / "capture.json"
        capture.write_text(json.dumps(graph(root)), encoding="utf8")
        result = run(capture, directory / "out")
        code = (directory / "out" / result["artifacts"]["luau"]).read_text(encoding="utf8")
        return result, code

    def test_authored_selfmod_fixture(self):
        fixture = Path(__file__).resolve().parents[1] / "examples" / "synthetic_capture.json"
        with tempfile.TemporaryDirectory() as directory:
            result = run(fixture, directory)
            self.assertEqual(result["stats"]["resolved_islands"], 1)
            self.assertEqual(result["stats"]["prototypes"], 1)
            code = (Path(directory) / result["artifacts"]["luau"]).read_text()
            self.assertIn("return function(", code)
            self.assertIn("if ", code)
            self.assertIn("10", code)
            self.assertNotIn("while pc", code)

    def test_mutable_capture_and_close(self):
        child = proto([(59, {2: 1, 8: 0}), (78, {11: 1})], {1: {1: 0, 3: 1}})
        root = proto([(61, {2: 1, 1: 7}), (0, {2: 2, 6: child}),
                      (43, {8: 1}), (61, {2: 1, 1: 9}), (78, {11: 2})])
        result, code = self.recover(root)
        self.assertEqual(result["stats"]["prototypes"], 2)
        self.assertIn("local v0_1 = {value = nil}", code)
        self.assertIn("v0_1 = {value = v0_1.value}", code)
        self.assertIn("return captured1_0.value", code)
        self.assertIn("end)(v0_1)", code)

    def test_by_value_capture_preserves_false(self):
        child = proto([(35, {2: 0, 11: 1}), (78, {11: 1})], {1: {1: 1, 3: 1}})
        _, code = self.recover(proto([(61, {2: 1, 1: False}), (0, {2: 2, 6: child}),
                                     (61, {2: 1, 1: True}), (78, {11: 2})]))
        self.assertIn("v0_1 = false", code)
        self.assertIn("return captured1_0", code)
        self.assertNotIn(".value", code)

    def test_one_result_call_stays_parenthesized(self):
        _, code = self.recover(proto([(98, {11: 1, 6: b"f"}), (64, {11: 1}), (78, {11: 1})]))
        self.assertIn("return (f())", code)

    def test_dynamic_call_return_preserves_all_values(self):
        _, code = self.recover(proto([(69, {11: 1}), (56, {2: 1, 11: 1, 8: 0}), (38, {11: 1})]))
        self.assertIn("return v0_1()", code)
        self.assertNotIn("return (v0_1())", code)

    def test_fixed_call_return_has_two_destinations(self):
        _, code = self.recover(proto([(69, {11: 1}), (56, {2: 1, 11: 1, 8: 3}), (24, {2: 1, 11: 3})]))
        self.assertIn("v0_1, v0_2 = v0_1()", code)
        self.assertIn("return v0_1, v0_2", code)

    def test_varargs_preserve_open_tail(self):
        _, code = self.recover(proto([(82, {2: 0}), (47, {11: 1}), (38, {11: 1})]))
        self.assertIn("function(...)", code)
        self.assertIn("return ...", code)

    def test_conditional_write_does_not_kill_incoming_value(self):
        # return argument or false: the truthy branch must keep argument.
        _, code = self.recover(proto([(69, {11: 1}), (84, {2: 1, 11: 2}),
                                     (102, {2: 2, 11: 4}), (61, {2: 2, 1: False}), (78, {11: 2})]))
        self.assertIn("v0_2 = v0_1", code)
        self.assertIn("v0_2 = false", code)
        self.assertIn("return v0_2", code)

    def test_boolean_key_rejected_without_integer_collision(self):
        with self.assertRaisesRegex(ValueError, "table keys"):
            Capture({"root": {"ref": 1}, "nodes": [[[True, 1], [1, 2]]]})

    def test_table_key_rejected_explicitly(self):
        with self.assertRaisesRegex(ValueError, "table-valued keys"):
            Capture({"root": {"ref": 1}, "nodes": [[[{"ref": 1}, 2]]]})

    def test_oversized_register_rejected(self):
        with self.assertRaisesRegex(ValueError, "register index"):
            self.recover(proto([(61, {2: 1000000000, 1: 3}), (109, {})]))

    def test_unknown_opcode_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported op"):
            self.recover(proto([(500, {})]))

    def test_dynamic_setlist_rejected(self):
        with self.assertRaisesRegex(ValueError, "dynamic SETLIST"):
            self.recover(proto([(41, {2: 1}), (9, {2: 1, 8: 0}), (78, {11: 1})]))

    def test_invalid_graph_reference_rejected(self):
        with self.assertRaisesRegex(ValueError, "reference"):
            Capture({"root": {"ref": 20}, "nodes": []})

    def test_missing_jump_destination_rejected(self):
        with self.assertRaisesRegex(ValueError, "target 100.*absent"):
            self.recover(proto([(39, {8: 99}), (109, {})]))

    def test_falling_off_instruction_stream_rejected(self):
        with self.assertRaisesRegex(ValueError, "target 2.*absent"):
            self.recover(proto([(61, {2: 1, 1: 3})]))

    def test_numeric_nil_tag_rejected(self):
        with self.assertRaisesRegex(ValueError, "scalar tag"):
            Capture({"root": {"nil": 1}, "nodes": []})

    def test_imports_have_no_filesystem_side_effects(self):
        for name in ("narsil.engine.lift", "narsil.engine.render", "narsil.pipeline"):
            with patch.object(Path, "read_text", side_effect=AssertionError("import read")), \
                 patch.object(Path, "write_text", side_effect=AssertionError("import write")):
                importlib.reload(importlib.import_module(name))

    def test_repeated_runs_are_isolated(self):
        root = proto([(61, {2: 1, 1: 42}), (78, {11: 1})])
        first = self.recover(root)[1]
        second = self.recover(root)[1]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

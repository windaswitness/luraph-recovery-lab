import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from luraph_lab.capture import CapturePlanError, plan_capture


TOY = '''return (function()
    local function decode()
        local rows = {}
        for index = 1, 3 do rows[index] = {index, index * 2} end
        return {instructions = rows, constants = {"sample", false}}
    end
    local function create(prototype)
        return function() return prototype.instructions[1][2] end
    end
    return create(decode())
end)()()
'''


def profile_for(source):
    return {
        'schema_version': 1, 'name': 'authored-toy',
        'input_sha256': hashlib.sha256(source.encode()).hexdigest(),
        'intercept': {'marker': 'return create(decode())', 'replacement': 'return decode()'},
        'strip_tail': {'suffix': '()\n'},
        'guard': {'instruction_limit': 10000, 'time_limit_seconds': 2,
                  'hook_name': '__toy_capture_guard', 'yield_every': 100},
        'include_graph_serializer': True,
    }


class CaptureTests(unittest.TestCase):
    def plan(self, root, source=TOY, profile=None):
        # Exact bytes avoid platform newline translation in the hash fixture.
        (root / 'input.lua').write_bytes(source.encode())
        (root / 'profile.json').write_text(json.dumps(profile or profile_for(source)))
        return plan_capture(root / 'input.lua', root / 'profile.json', root / 'out')

    def test_authored_toy_end_to_end_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.plan(root)
            output = (root / 'out/capture.luau').read_text()
            self.assertFalse(result['executed_input'])
            self.assertEqual(result['interception']['returns'], 'prototype')
            self.assertEqual(result['inserted_loop_checkpoints'], 1)
            self.assertNotIn('return create(decode())', output)
            self.assertIn('return decode()', output)
            self.assertTrue(output.endswith('end)()'))
            self.assertIn('do __toy_capture_guard(); ', output)
            self.assertIn('NOT a sandbox', output)
            self.assertIn('serialize_graph.luau', result['files'])
            self.assertEqual((root / 'input.lua').read_bytes(), TOY.encode())

    def test_exact_hash_and_marker_counts(self):
        scenarios = []
        bad_hash = profile_for(TOY); bad_hash['input_sha256'] = '0' * 64
        scenarios.append((TOY, bad_hash, 'SHA-256 mismatch'))
        missing = profile_for(TOY); missing['intercept']['marker'] = 'absent()'
        scenarios.append((TOY, missing, 'exactly once'))
        duplicate_source = TOY + '-- return create(decode())\n'
        scenarios.append((duplicate_source, profile_for(duplicate_source), 'exactly once'))
        for source, profile, message in scenarios:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with self.assertRaisesRegex(CapturePlanError, message):
                    self.plan(root, source, profile)
                self.assertFalse((root / 'out').exists())

    def test_exact_tail_and_guard_collisions(self):
        for mutate, message in [
            (lambda p: p['strip_tail'].update(suffix='wrong'), 'suffix'),
            (lambda p: p['guard'].update(instruction_limit=0), 'instruction_limit'),
            (lambda p: p['guard'].update(time_limit_seconds=-1), 'time_limit_seconds'),
            (lambda p: p['guard'].update(hook_name='decode'), 'identifier'),
        ]:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                p = profile_for(TOY); mutate(p)
                with self.assertRaisesRegex(CapturePlanError, message):
                    self.plan(Path(directory), profile=p)
        source = 'local __toy_capture_guard=1\n' + TOY
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(CapturePlanError, 'already occurs'):
            self.plan(Path(directory), source)

    def test_custom_exposure_requires_explicit_review(self):
        p = profile_for(TOY)
        p['intercept'].update(returns='reviewed_custom', replacement='return {prototype=decode(), create=create}')
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(CapturePlanError, 'reviewed'):
            self.plan(Path(directory), profile=p)
        p['intercept']['reviewed'] = True
        with tempfile.TemporaryDirectory() as directory:
            result = self.plan(Path(directory), profile=p)
            self.assertTrue(result['interception']['reviewed_custom'])

    def test_comments_and_strings_are_not_guarded(self):
        source = 'local text="do repeat" -- do repeat\n' + TOY
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.plan(root, source)
            text = (root / 'out/capture.luau').read_text()
            self.assertIn('local text="do repeat" -- do repeat', text)
            self.assertEqual(result['inserted_loop_checkpoints'], 1)

    def test_marker_inside_string_is_refused(self):
        source = 'local text="return create(decode())"\nreturn 1\n'
        p = profile_for(source); p.pop('strip_tail')
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(CapturePlanError, 'inside'):
            self.plan(Path(directory), source, p)

    def test_example_profile_matches_public_toy(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            result = plan_capture(root / 'examples/toy_loader.lua',
                                  root / 'examples/capture_profile.example.json', Path(directory) / 'out')
            self.assertFalse(result['executed_input'])

    def test_partial_token_marker_is_refused(self):
        p = profile_for(TOY)
        p['intercept']['marker'] = 'return crea'
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(CapturePlanError, 'inside'):
            self.plan(Path(directory), profile=p)


if __name__ == '__main__':
    unittest.main()

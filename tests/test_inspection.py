import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from luraph_lab.inspection import inspect_file
from luraph_lab.lua_lex import LuaLexError, decode, quote, scan


class LiteralTests(unittest.TestCase):
    def test_every_byte_round_trip(self):
        data = bytes(range(256))
        self.assertEqual(decode(quote(data)), data)
        self.assertTrue(quote(data).isascii())

    def test_supported_escapes_and_unicode(self):
        self.assertEqual(decode(r'''"\000\255\x41\u{1f642}\n\t\\\"\'"'''),
                         b"\x00\xffA" + "🙂".encode() + b"\n\t\\\"'")
        self.assertEqual(decode('"a\\\r\nb\\z \t\r\n c"'), b"a\nbc")
        self.assertEqual(decode('[==[\r\nalpha\r\nbeta\n\rgamma]==]'), b"alpha\nbeta\ngamma")

    def test_malformed_literals_are_rejected(self):
        bad = ['"\\256"', '"\\x1"', '"\\xGG"', '"\\u{}"', '"\\u{110000}"',
               '"\\u{d800}"', '"\\u1234"', '"\\q"', '"a\nb"', '[=[oops]',
               '"a"extra"', '[=[x]=]extra']
        for literal in bad:
            with self.subTest(literal=literal), self.assertRaises(LuaLexError):
                decode(literal)
        self.assertEqual(decode(r'"\q"', permissive_unknown_escapes=True), b'q')
        with self.assertRaises(LuaLexError):
            decode(r'"\999"', permissive_unknown_escapes=True)

    def test_scanner_offsets_and_error_location(self):
        source = '-- header\r\nlocal x = "ok"\nlocal bad = "\\xQ0"'
        with self.assertRaises(LuaLexError) as caught:
            list(scan(source))
        error = caught.exception
        self.assertEqual(error.offset, source.index('\\xQ0'))
        self.assertEqual((error.line, error.column), (3, 14))
        tokens = list(scan('local s="é" --comment\nreturn s'))
        self.assertEqual(tokens[3], ('string', '"é"', 8))
        self.assertEqual(tokens[-1][2], 29)

    def test_comments_long_strings_and_numbers(self):
        tokens = list(scan('--[=[ignored]=]\nlocal x=0xff+0b10+.5e2+0x1.fp2; return [[x]]'))
        self.assertEqual(tokens[0][0], 'comment')
        self.assertEqual([v for k, v, _ in tokens if k == 'number'], ['0xff', '0b10', '.5e2', '0x1.fp2'])
        self.assertEqual(tokens[-1][0], 'long')
        self.assertEqual([v for _, v, _ in scan('1..2')], ['1', '..', '2'])
        for source in ['0x', '0b102', '1e+', '1__2', '`hello`', '"unterminated', '--[=[open']:
            with self.subTest(source=source), self.assertRaises(LuaLexError):
                list(scan(source))


class InspectionTests(unittest.TestCase):
    def test_static_outputs_and_binary_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = bytes(range(256)) * 5
            original = ('-- inert fixture\nlocal data=' + quote(data) + '\nreturn 0x10').encode()
            path = root / 'toy.lua'
            path.write_bytes(original)
            result = inspect_file(path, root / 'out')
            self.assertFalse(result['executed_input'])
            self.assertEqual(result['input_sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(result['large_blobs'], 1)
            self.assertEqual((root / 'out/blob_0000.bin').read_bytes(), data)
            self.assertIn('return 16', (root / 'out/normalized.lua').read_text())
            self.assertEqual(json.loads((root / 'out/strings.json').read_text())[0]['line'], 2)
            self.assertEqual(path.read_bytes(), original)

    def test_failure_does_not_create_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'bad.lua'
            path.write_text('return "\\xGG"')
            with self.assertRaises(LuaLexError):
                inspect_file(path, root / 'out')
            self.assertFalse((root / 'out').exists())

    def test_nonempty_output_and_non_utf8_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'toy.lua'
            path.write_text('return 1')
            with self.assertRaises(ValueError):
                inspect_file(path, root)
            path.write_bytes(b'\xff')
            with self.assertRaisesRegex(ValueError, 'UTF-8'):
                inspect_file(path, root / 'out')


if __name__ == '__main__':
    unittest.main()

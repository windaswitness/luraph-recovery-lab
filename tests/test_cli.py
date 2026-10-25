import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CommandLineTests(unittest.TestCase):
    def invoke(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "luraph_lab", *map(str, arguments)],
            cwd=ROOT, capture_output=True, text=True,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=30,
        )

    def test_help_and_profiles(self):
        help_result = self.invoke("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("capture-plan", help_result.stdout)
        result = self.invoke("profiles")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)[0]["versionGuarantee"])

    def test_static_inspection_does_not_execute_input(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "untrusted.lua"
            source.write_text('error("This must not run")\nreturn "\\065\\000\\255", 0x20\n')
            output = base / "report"
            result = self.invoke("inspect", source, "--out", output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "normalized.lua").is_file())
            self.assertTrue((output / "manifest.json").is_file())
            self.assertIn("32", (output / "normalized.lua").read_text())

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "input.lua"
            source.write_text("return 1")
            output = base / "out"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("original")
            result = self.invoke("inspect", source, "--out", output)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(), "original")
            self.assertFalse((output / "normalized.lua").exists())

    def test_demo_runs_real_pipeline(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "demo"
            result = self.invoke("demo", "--out", output)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertIn("synthetic", report["demo"])
            generated = list(output.rglob("*.luau"))
            self.assertTrue(generated, "The demo must generate Luau, not only a status message")

    def test_unsupported_profile_is_rejected(self):
        result = self.invoke("recover", "anything.json", "--profile", "universal", "--out", "unused")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)

    def test_invalid_capture_is_not_a_success(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "broken.json"
            source.write_text('{"root": {"ref": 9000}, "nodes": []}')
            result = self.invoke("recover", source, "--out", base / "out")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("error:", result.stderr)


if __name__ == "__main__":
    unittest.main()

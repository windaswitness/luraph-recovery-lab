"""File-based command line interface. No Lua execution or network access."""
from __future__ import annotations

import argparse
from importlib import resources
import json
from pathlib import Path
import sys

from . import __version__


PROFILE_METADATA = [{
    "id": "column-vm-v1",
    "status": "experimental",
    "input": "captured table graph; not an obfuscated source file",
    "scope": "one observed column-based VM layout and opcode mapping",
    "versionGuarantee": False,
    "output": "reconstructed Luau requiring behavioral validation",
}]


def _output_directory(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"Output must be a new or empty directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _input_file(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Input file does not exist: {path}")
    return path


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="narsil",
        description="NARSIL: experimental Luraph recovery tools for Lua/Luau. Input Lua is never executed by this CLI.",
    )
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--debug", action="store_true", help="Show Python tracebacks for failures")
    commands = root.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="Normalize literals and inventory strings; no VM recovery")
    inspect.add_argument("input", type=Path)
    inspect.add_argument("--out", type=Path, required=True)

    capture = commands.add_parser("capture-plan", help="Generate a reviewed capture script; do not run it")
    capture.add_argument("input", type=Path)
    capture.add_argument("--profile", type=Path, required=True, help="Exact-source capture profile JSON")
    capture.add_argument("--out", type=Path, required=True)

    recover = commands.add_parser("recover", help="Reconstruct Luau from a compatible captured graph")
    recover.add_argument("input", type=Path, help="Capture JSON, not a Lua source file")
    recover.add_argument("--profile", default="column-vm-v1", choices=[p["id"] for p in PROFILE_METADATA])
    recover.add_argument("--out", type=Path, required=True)

    demo = commands.add_parser("demo", help="Run recovery on the included authored synthetic capture")
    demo.add_argument("--out", type=Path, required=True)
    commands.add_parser("profiles", help="List adapter scope and limitations")
    return root


def dispatch(args: argparse.Namespace) -> dict | list:
    if args.command == "profiles":
        return PROFILE_METADATA
    if args.command == "inspect":
        from .inspection import inspect_file
        source = _input_file(args.input)
        return inspect_file(source, _output_directory(args.out))
    if args.command == "capture-plan":
        from .capture import plan_capture
        source, profile = _input_file(args.input), _input_file(args.profile)
        return plan_capture(source, profile, _output_directory(args.out))
    if args.command == "recover":
        from .pipeline import run
        source = _input_file(args.input)
        return run(source, _output_directory(args.out), profile=args.profile)
    if args.command == "demo":
        from .pipeline import run
        output = _output_directory(args.out)
        fixture = resources.files("narsil").joinpath("resources/synthetic_capture.json")
        with resources.as_file(fixture) as path:
            result = run(path, output, profile="column-vm-v1")
        result["demo"] = "Authored synthetic VM data; no proprietary game source is bundled."
        return result
    raise ValueError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        if args.debug:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

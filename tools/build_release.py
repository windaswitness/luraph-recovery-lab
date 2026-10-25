"""Build a source ZIP from explicit public directories, excluding local data."""
from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

ROOT_FILES = ("README.md", "CONTRIBUTING.md", "LICENSE", "pyproject.toml",
              "MANIFEST.in", ".gitignore", ".gitattributes")
SOURCE_DIRECTORIES = ("luraph_lab", "tests", "examples", "docs", "tools", ".github")
EXCLUDE = {"__pycache__", ".git", ".test-tmp", ".pytest_cache", "private", "captures", "work"}


def source_files(root: Path):
    for name in ROOT_FILES:
        path = root / name
        if path.is_file() and not path.is_symlink():
            yield path
    for directory in SOURCE_DIRECTORIES:
        for path in sorted((root / directory).rglob("*")):
            relative = path.relative_to(root)
            if any(part in EXCLUDE for part in relative.parts):
                continue
            if path.is_file() and not path.is_symlink() and path.suffix not in (".pyc", ".pyo"):
                yield path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error("Output already exists; choose a new ZIP filename")
    files = list(source_files(root))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, Path("luraph-recovery-lab") / path.relative_to(root))
    print(f"Wrote {len(files)} public source files to {output}")


if __name__ == "__main__":
    main()

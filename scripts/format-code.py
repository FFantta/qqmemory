"""Format only owned Python sources, excluding archives, vendors, and build output."""

import argparse
import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def source_files():
    paths = list((ROOT / "qqmemory/qqmemory").glob("*.py"))
    paths += list((ROOT / "qqmemory/tests").glob("*.py"))
    paths += list((ROOT / "qqmemory").glob("run_*.py"))
    paths += list((ROOT / "qqmemory/qzone_memory").glob("*.py"))
    paths += [path for path in (ROOT / "scripts").glob("*.py") if path.name != "qmemory-server.py"]
    return sorted(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write", action="store_true", help="Apply formatting and verify Python ASTs"
    )
    mode.add_argument(
        "--check", action="store_true", help="Check formatting without modifying files"
    )
    args = parser.parse_args()
    paths = source_files()
    before = (
        {path: ast.dump(ast.parse(path.read_text(encoding="utf-8"))) for path in paths}
        if args.write
        else {}
    )
    command = [sys.executable, "-m", "ruff", "format", "--no-cache"]
    if not args.write:
        command.append("--check")
    result = subprocess.run(command + [str(path) for path in paths], cwd=ROOT, check=False)
    if result.returncode:
        return result.returncode
    if args.write:
        changed = [
            path
            for path, tree in before.items()
            if ast.dump(ast.parse(path.read_text(encoding="utf-8"))) != tree
        ]
        if changed:
            raise RuntimeError(
                "Formatting changed Python syntax trees: " + ", ".join(map(str, changed))
            )
        print(f"Verified unchanged Python syntax trees for {len(paths)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

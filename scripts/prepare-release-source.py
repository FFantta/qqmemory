"""Explicit source allowlist for the public release/deployment repository."""

import argparse
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def files():
    paths = []
    paths += sorted((ROOT / "qqmemory/qqmemory").glob("*.py"))
    paths += [ROOT / "qqmemory/qqmemory/ui" / name for name in ("index.html", "app.js", "app.css")]
    paths += sorted((ROOT / "qqmemory/qqmemory/cloud_ui").glob("*"))
    paths += sorted(
        p for p in (ROOT / "qqmemory/qqmemory/templates").iterdir() if p.suffix in (".html", ".js")
    )
    paths += [
        p
        for p in sorted((ROOT / "qqmemory/tests").iterdir())
        if p.suffix in (".py", ".cjs", ".jsonl")
    ]
    paths += [
        ROOT / path
        for path in (
            "README.md",
            "qqmemory/README.md",
            "INSTALL.md",
            "downloads/release.json",
            "scripts/publish-github-release.py",
            "LICENSE",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "THIRD_PARTY_NOTICES.md",
            ".github/ISSUE_TEMPLATE/bug_report.md",
            "qqmemory/run_mac.py",
            "qqmemory/run_cloud.py",
            "qqmemory/pyproject.toml",
            "package.json",
            "package-lock.json",
            ".prettierrc.json",
            ".prettierignore",
            ".editorconfig",
            "ruff.toml",
            "qqmemory/requirements-dev.txt",
            "qqmemory/requirements-build-mac.txt",
            "qqmemory/docs/operations/MAC_INSTALLER.md",
            ".github/workflows/code-format.yml",
            "qqmemory/docs/CODE_READABILITY.md",
            "qqmemory/requirements-lock.txt",
            "qqmemory/requirements-desktop.txt",
            "qqmemory/requirements-cloud.txt",
            "scripts/build-release.py",
            "scripts/build_dmg.py",
            "scripts/dmg-background.swift",
            "scripts/format-code.py",
            "scripts/prepare-release-source.py",
            "scripts/serve-memory.py",
            "scripts/start-web.command",
            "scripts/preview-memory.py",
            "scripts/build-mac.command",
            "scripts/package-friend-release.py",
            "qqmemory/docs/NAMING.md",
            ".github/workflows/build-desktop.yml",
            "render.yaml",
            ".gitignore",
        )
    ]
    return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--icon", action="store_true")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=1000)
    args = parser.parse_args()
    if args.icon:
        print(base64.b64encode((ROOT / "qqmemory/assets/icon.icns").read_bytes()).decode("ascii"))
        return
    paths = files()
    result = [
        dict(
            path=str(p.relative_to(ROOT)),
            mode="100644",
            type="blob",
            content=p.read_text(encoding="utf-8"),
        )
        for p in paths
    ]
    if args.json:
        print(json.dumps(result[args.start : args.start + args.count], ensure_ascii=False))
    else:
        print(
            json.dumps(
                dict(
                    files=len(result),
                    bytes=sum(len(x["content"].encode()) for x in result),
                    paths=[x["path"] for x in result],
                ),
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()

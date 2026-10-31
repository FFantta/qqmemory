"""Explicit source allowlist for the private release/deployment repository."""

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
    paths += sorted((ROOT / "qqmemory/qqmemory/templates").glob("*.html"))
    paths += [
        p
        for p in sorted((ROOT / "qqmemory/tests").iterdir())
        if p.suffix in (".py", ".cjs", ".jsonl")
    ]
    paths += [
        ROOT / path
        for path in (
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
            ".github/workflows/code-format.yml",
            "qqmemory/docs/CODE_READABILITY.md",
            "qqmemory/requirements-lock.txt",
            "qqmemory/requirements-desktop.txt",
            "qqmemory/requirements-cloud.txt",
            "scripts/build-release.py",
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
    result.append(
        dict(
            path="README.md",
            mode="100644",
            type="blob",
            content="""# qqmemory · 空间记忆

Private desktop release and cloud-trial source. No personal archives or local path configuration are included.

- Development: Python uses Ruff and web source uses Prettier with pinned versions. See qqmemory/docs/CODE_READABILITY.md for commands, module responsibilities and review conventions.
- Desktop: install qqmemory/requirements-desktop.txt, run scripts/build-release.py on macOS or Windows.
- Windows: GitHub Actions runs offline regression tests, creates a clean x64 package and runs its packaged offline self-test.
- Cloud: Render blueprint in render.yaml. One Gunicorn worker, eight HTTP threads, one collector at a time. QQ cookies stay in job memory. Private results expire after one hour; users can delete earlier.
- Trial limits: 1200 seconds of text scanning, 1800 seconds total collection, 1200 collection requests, no practical image-count cap, 4 MiB per image; 512 MiB source-image capacity per task. Deep checkpoints can continue after same-account reauthentication. ZIP parts target 64 MiB source images; single-file HTML is available only for archives up to 16 MiB of images. Results can be incomplete.
- Default public trial quota: 20 jobs per UTC day, ten per browser per day including continuation; 4 GiB monthly private-file transfer quota. Do not scale to multiple processes without moving job ownership, quotas and scheduling into a shared service.
- Cloud collection saves text and image references first; social enrichment and bounded image downloads follow. Exact repeated cards and fully covered offset probes are skipped, without treating unknown or empty ranges as covered. Optional details have a bounded pass and remain resumable if unfinished.
- Signed session secret must be stable and at least 32 characters. Use a dedicated data directory. Never reuse a desktop archive root.
- Service restarts interrupt active QQ sessions. Paid deployment uses a 1 GB disk mounted at /var/data; QQMEMORY_CLOUD_ROOT and quota counters live below it. Set QQMEMORY_CLOUD_PERSISTENT=1 only with a real mounted disk. Archives/checkpoints persist across restarts within the one-hour retention period; active QQ login sessions do not. Provider disk snapshots may remain for up to seven days. Temporary data is not a permanent backup.
- The macOS app is ad-hoc signed, not notarized. Windows code signing is not configured. Successful offline self-tests do not replace native-window and real QQ authentication tests on target machines.
""",
        )
    )
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

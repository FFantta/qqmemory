"""Validate existing release assets and optionally publish with authenticated GitHub CLI.

Default is offline validation only. No builds, commits, cloud deploys or installation.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def checked_assets(manifest, directory):
    paths = []
    for item in manifest["releases"]:
        name = item["file"]
        if Path(name).name != name:
            raise ValueError("Release file must be a basename")
        path = directory / name
        if path.stat().st_size != item["size_bytes"]:
            raise ValueError("Unexpected file size: " + name)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(256 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != item["sha256"]:
            raise ValueError("Unexpected SHA-256: " + name)
        paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "downloads/release.json")
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assets = checked_assets(manifest, args.assets.resolve())
    print("Verified " + str(len(assets)) + " release assets for " + manifest["version"])
    if not args.publish:
        print("Validation only. Pass --publish to create a GitHub prerelease.")
        return
    revision = manifest["source_revision"]
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("An exact app source revision is required")
    with tempfile.TemporaryDirectory(prefix="qqmemory-release-notes-") as temp:
        notes = Path(temp) / "notes.md"
        notes.write_text(
            "空间记忆 " + manifest["version"] + " · 朋友测试版\n\n"
            "Mac 打开 DMG 后拖入 Applications；Windows 解压完整 ZIP。"
            "Mac 暂无苹果公证，Windows 暂无发布者签名。"
            "历史重建不等于确认原帖被删除，不能保证取得全部历史或原图。\n\n"
            "[安装说明](https://github.com/FFantta/qqmemory/blob/main/INSTALL.md)\n\n"
            "App 源码提交：`" + revision + "`。校验值见 release.json。\n",
            encoding="utf-8",
        )
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                "v" + manifest["version"],
                *map(str, assets),
                str(args.manifest.resolve()),
                "--repo",
                "FFantta/qqmemory",
                "--target",
                revision,
                "--title",
                "空间记忆 " + manifest["version"],
                "--notes-file",
                str(notes),
                "--prerelease",
            ],
            check=True,
        )


if __name__ == "__main__":
    main()

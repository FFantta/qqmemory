"""Package the verified arm64 app without local configuration or user archives."""

import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("/private/tmp/qqmemory-final/空间记忆.app")
OUTPUT = ROOT / "website/dist/downloads"
README = """空间记忆 0.5.1 · Apple 芯片 Mac 朋友测试版

安装：将“空间记忆.app”拖入“应用程序”，再打开。
仅供 Apple 芯片（M 系列）Mac；本包不是 Intel 版。
当前仅在开发者本机验证，尚未完成另一台干净电脑的安装验收。
应用仅有本地临时签名，没有 Developer ID 签名或苹果公证。
macOS 可能阻止首次启动；确认来源可信后按系统提示在“隐私与安全性”处理。
无需关闭系统安全保护。

首次使用：没有已有档案时，点击“添加账号”，用手机 QQ 扫码并确认。
本地档案可以离线切换；联网更新时重新扫码。
数据默认保存到你自己电脑的 ~/Library/Application Support/qqmemory。
各 QQ 账号分目录保存，卸载 App 不会自动删除归档。
登录凭据只在本次进程内保存，退出 App 后清除。
可导出离线 HTML。不会向 QQ 空间写回内容。
历史重建不等于确认原帖被删除，不能保证找回全部删除内容或完整原图。

本包不包含开发者的本地路径配置和账号归档。
更新应用后请退出旧进程并重新打开。
独立工具，非腾讯官方产品。
"""


def run(*args):
    subprocess.run(args, check=True)


def main():
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(SOURCE))
    info = plistlib.loads((SOURCE / "Contents/Info.plist").read_bytes())
    if info["CFBundleShortVersionString"] != "0.5.1":
        raise RuntimeError("Expected verified 0.5.1 source")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="qqmemory-friend-", dir="/private/tmp") as temp:
        bundle = Path(temp) / "空间记忆朋友测试版"
        bundle.mkdir()
        app = bundle / SOURCE.name
        run("/usr/bin/ditto", "--norsrc", "--noextattr", str(SOURCE), str(app))
        for config in app.rglob("local-config.json"):
            config.unlink()
        forbidden = {"archive.sqlite3", "profile.json", "selected-account.json", "last-error.json"}
        forbidden_dirs = {"local-data", "LocalArchive", "evidence", "exports"}
        for path in app.rglob("*"):
            if path.name in forbidden or (path.is_dir() and path.name in forbidden_dirs):
                raise RuntimeError(f"Unexpected private data path: {path.name}")
        run("/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app))
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(app))
        (bundle / "安装与使用说明.txt").write_text(README, encoding="utf-8")
        archive = OUTPUT / "qqmemory-0.5.1-mac-arm64.zip"
        run(
            "/usr/bin/ditto",
            "-c",
            "-k",
            "--norsrc",
            "--noextattr",
            "--keepParent",
            str(bundle),
            str(archive),
        )
        extracted = Path(temp) / "verified"
        run("/usr/bin/ditto", "-x", "-k", str(archive), str(extracted))
        unpacked = extracted / bundle.name / SOURCE.name
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(unpacked))
        assert not list(unpacked.rglob("local-config.json"))
        report = {
            "version": "0.5.1",
            "architecture": "arm64",
            "file": archive.name,
            "size_bytes": archive.stat().st_size,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "signature": "ad-hoc",
            "notarized": False,
            "clean_machine_tested": False,
        }
        (OUTPUT / "release.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))


if __name__ == "__main__":
    main()

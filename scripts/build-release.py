"""Clean desktop release build. Run on each target OS and architecture."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "qqmemory"))
from qqmemory.version import VERSION, BUILD


def run(*args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "release-artifacts")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    arch = platform.machine().lower()
    if system not in ("Darwin", "Windows"):
        parser.error("Run this build on macOS or Windows")
    if system == "Windows" and arch not in ("amd64", "x86_64"):
        parser.error("Windows release currently requires x64 Python")
    target = ("mac-" + arch) if system == "Darwin" else "windows-x64"
    env = dict(
        os.environ,
        PYTHONPATH=str(ROOT / "qqmemory"),
        PYTHONPYCACHEPREFIX=str(Path(tempfile.gettempdir()) / ("qqmemory-pycache-" + target)),
    )
    with tempfile.TemporaryDirectory(prefix="qqmemory-release-") as temp:
        work = Path(temp)
        env["PYINSTALLER_CONFIG_DIR"] = str(work / "pyinstaller-cache")
        ui = work / "ui"
        ui.mkdir()
        # Explicit allowlist: never package local-config.json or an archive.
        for name in ("index.html", "app.js", "app.css"):
            shutil.copyfile(ROOT / "qqmemory/qqmemory/ui" / name, ui / name)
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--name",
            "空间记忆",
            "--distpath",
            str(work / "dist"),
            "--workpath",
            str(work / "build"),
            "--specpath",
            str(work),
            "--add-data",
            str(ui) + os.pathsep + "qqmemory/ui",
            "--add-data",
            str(ROOT / "qqmemory/qqmemory/templates") + os.pathsep + "qqmemory/templates",
            "--collect-all",
            "webview",
            "--collect-data",
            "tzdata",
        ]
        if system == "Darwin":
            command += [
                "--target-arch",
                arch,
                "--osx-bundle-identifier",
                "local.qqmemory.desktop",
                "--icon",
                str(ROOT / "qqmemory/assets/icon.icns"),
            ]
        command += [str(ROOT / "qqmemory/run_mac.py")]
        run(*command, env=env, cwd=ROOT)
        package = work / "空间记忆"
        package.mkdir()
        if system == "Darwin":
            app = work / "dist/空间记忆.app"
            info = app / "Contents/Info.plist"
            values = plistlib.loads(info.read_bytes())
            values.update(CFBundleShortVersionString=VERSION, CFBundleVersion=BUILD)
            info.write_bytes(plistlib.dumps(values))
            run("/usr/bin/codesign", "--force", "--deep", "--sign", "-", app)
            run("/usr/bin/codesign", "--verify", "--deep", "--strict", app)
            run("/usr/bin/ditto", "--norsrc", "--noextattr", app, package / app.name)
        else:
            shutil.copytree(work / "dist/空间记忆", package / "空间记忆")
        smoke = work / "packaged-smoke.json"
        executable = (
            package / "空间记忆.app/Contents/MacOS/空间记忆"
            if system == "Darwin"
            else package / "空间记忆/空间记忆.exe"
        )
        run(executable, "--self-test-output", smoke, env=env, timeout=90)
        result = json.loads(smoke.read_text(encoding="utf-8"))
        if (
            not result.get("ok")
            or result["version"] != VERSION
            or result["architecture"].lower() != arch
        ):
            raise RuntimeError("Packaged smoke test failed")
        forbidden = {
            "local-config.json",
            "archive.sqlite3",
            "profile.json",
            "selected-account.json",
            "last-error.json",
        }
        for path in package.rglob("*"):
            if path.name in forbidden or path.name in (
                "local-data",
                "LocalArchive",
                "evidence",
                "exports",
            ):
                raise RuntimeError("Private data in release: " + path.name)
        data_path = (
            "~/Library/Application Support/qqmemory"
            if system == "Darwin"
            else "%LOCALAPPDATA%\\qqmemory"
        )
        instructions = f"""空间记忆 {VERSION} · {target} 测试版

macOS：将空间记忆.app 拖到应用程序后打开。
Windows：解压整个 ZIP 后，打开 空间记忆/空间记忆.exe；请保留同目录的依赖文件。
Windows 需要 Microsoft Edge WebView2 Runtime（https://developer.microsoft.com/microsoft-edge/webview2/）。
首次为空档案，点击“添加账号”，用手机 QQ 扫码确认。更新已有档案也需要扫码。
本地数据默认保存在 {data_path}，各 QQ 账号独立目录。
退出旧版本后再打开更新包。安装包不含私人归档或本机路径配置。
macOS 仅本地临时签名，未经苹果公证；Windows 未做发布者代码签名。
如系统提示来源未知，请先确认来源；不需要关闭系统安全保护。
历史重建不等于确认原帖被删除，不能保证恢复全部历史或原图。非腾讯官方产品。
"""
        (package / "安装与使用说明.txt").write_text(instructions, encoding="utf-8")
        archive = output / f"qqmemory-{VERSION}-{target}.zip"
        if system == "Darwin":
            run(
                "/usr/bin/ditto",
                "-c",
                "-k",
                "--norsrc",
                "--noextattr",
                "--keepParent",
                package,
                archive,
            )
            extracted = work / "verified"
            run("/usr/bin/ditto", "-x", "-k", archive, extracted)
            run(
                "/usr/bin/codesign",
                "--verify",
                "--deep",
                "--strict",
                extracted / "空间记忆/空间记忆.app",
            )
        else:
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
                for path in sorted(package.rglob("*")):
                    if path.is_file():
                        zipped.write(path, path.relative_to(package.parent))
        manifest = dict(
            version=VERSION,
            architecture=arch,
            platform=target,
            file=archive.name,
            sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            size_bytes=archive.stat().st_size,
            signed="ad-hoc" if system == "Darwin" else False,
            notarized=False,
            packaged_core_tested=True,
            native_window_tested=False,
        )
        archive.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(json.dumps(manifest))


if __name__ == "__main__":
    main()

"""Create a drag-to-Applications DMG from an already verified macOS app."""

import argparse
import plistlib
from pathlib import Path
import subprocess
import tempfile


def run(*args):
    result = subprocess.run([str(a) for a in args], capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def build_dmg(app, output, instructions):
    app, output = Path(app).resolve(), Path(output).resolve()
    if not app.is_dir() or app.name != "空间记忆.app":
        raise ValueError("Expected an existing .app bundle")
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", app)
    with tempfile.TemporaryDirectory(prefix="qqmemory-dmg-") as temp:
        work = Path(temp)
        stage = work / "stage"
        stage.mkdir()
        run("/usr/bin/ditto", "--norsrc", "--noextattr", app, stage / app.name)
        (stage / "Applications").symlink_to("/Applications")
        (stage / "安装与使用说明.txt").write_text(instructions, encoding="utf-8")
        (stage / ".background").mkdir()
        run(
            "/usr/bin/swift",
            "-module-cache-path",
            work / "swift-cache",
            Path(__file__).with_name("dmg-background.swift"),
            stage / ".background/install.png",
        )
        from dmgbuild import build_dmg as create_image
        from ds_store import DSStore

        create_image(
            str(output),
            "空间记忆 安装向导",
            settings={
                "files": [str(stage / app.name), str(stage / "安装与使用说明.txt")],
                "symlinks": {"Applications": "/Applications"},
                "background": str(stage / ".background/install.png"),
                "window_rect": ((120, 100), (720, 502)),
                "icon_size": 96,
                "text_size": 14,
                "default_view": "icon-view",
                "show_status_bar": False,
                "show_pathbar": False,
                "show_toolbar": False,
                "icon_locations": {
                    app.name: (180, 210),
                    "Applications": (540, 210),
                    "安装与使用说明.txt": (640, 400),
                },
            },
        )
        run("/usr/bin/hdiutil", "verify", output)
        attached = plistlib.loads(
            run("/usr/bin/hdiutil", "attach", output, "-readonly", "-plist", "-nobrowse")
        )
        mount = next(
            Path(item["mount-point"])
            for item in attached["system-entities"]
            if "mount-point" in item
        )
        try:
            run("/usr/bin/codesign", "--verify", "--deep", "--strict", mount / app.name)
            if (mount / "Applications").readlink() != Path("/Applications"):
                raise RuntimeError("Invalid Applications shortcut")
            with DSStore.open(str(mount / ".DS_Store"), "r") as store:
                options = store["."]["icvp"]
                if store["安装与使用说明.txt"]["Iloc"] != (640, 400):
                    raise RuntimeError("Installation guide position was not saved")
            if options.get("backgroundType") != 2 or options.get("iconSize") != 96:
                raise RuntimeError("Finder background/icon settings were not saved")
        finally:
            run("/usr/bin/hdiutil", "detach", mount)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--instructions", type=Path, required=True)
    args = parser.parse_args()
    print(build_dmg(args.app, args.output, args.instructions.read_text(encoding="utf-8")))

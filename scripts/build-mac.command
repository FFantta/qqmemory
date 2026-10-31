#!/bin/zsh
set -e
cd -- "${0:A:h:h}"
export PYTHONPYCACHEPREFIX="${TMPDIR:-/tmp}/qqmemory-build-cache"
export PYTHONPATH="$PWD/qqmemory"
./runtime/qmemory-venv/bin/python -m compileall -f -q qqmemory/qqmemory
./runtime/qmemory-venv/bin/python -m PyInstaller --noconfirm --windowed --name 空间记忆 --osx-bundle-identifier local.qqmemory.desktop --icon "$PWD/qqmemory/assets/icon.icns" --distpath /private/tmp/qqmemory-final --workpath qqmemory/build-mac-final --specpath qqmemory --add-data "$PWD/qqmemory/qqmemory/ui:qqmemory/ui" --collect-all webview qqmemory/run_mac.py
./runtime/qmemory-venv/bin/python - <<'PYINFO'
import plistlib
from pathlib import Path
path=Path('/private/tmp/qqmemory-final/空间记忆.app/Contents/Info.plist')
value=plistlib.loads(path.read_bytes())
value.update(CFBundleShortVersionString='0.5.1',CFBundleVersion='9')
path.write_bytes(plistlib.dumps(value))
PYINFO
/usr/bin/codesign --force --deep --sign - /private/tmp/qqmemory-final/空间记忆.app
/usr/bin/codesign --verify --deep --strict /private/tmp/qqmemory-final/空间记忆.app
if [[ -d qqmemory/dist-mac/空间记忆.app ]]; then
  build_backup=$(/usr/bin/mktemp -d /private/tmp/qqmemory-previous.XXXXXX)
  /bin/mv qqmemory/dist-mac/空间记忆.app "$build_backup/空间记忆.app"
fi
/usr/bin/ditto --norsrc --noextattr /private/tmp/qqmemory-final/空间记忆.app qqmemory/dist-mac/空间记忆.app
/usr/bin/xattr -dr com.apple.FinderInfo qqmemory/dist-mac/空间记忆.app 2>/dev/null || true
/usr/bin/xattr -dr com.apple.ResourceFork qqmemory/dist-mac/空间记忆.app 2>/dev/null || true
/usr/bin/codesign --verify --deep --strict qqmemory/dist-mac/空间记忆.app

# Mac 拖拽安装包

Mac 发布构建现在生成 DMG；Windows 继续生成 ZIP。DMG 内含原应用、指向 `/Applications` 的快捷方式、安装说明和 Finder 背景。用户把应用拖入 Applications，再从应用程序启动；复制进度由 macOS 显示。背景箭头是静态引导，不是自动安装动画。

首次打开若提示无法验证开发者，应先尝试打开，再进入“系统设置 → 隐私与安全性”，核对应用和下载来源后选择“仍要打开”。不要求允许任何来源、不修改 Gatekeeper、不移除 quarantine。当前 App 仍为临时签名，未完成 Developer ID 签名或苹果公证。

完整发布沿用 `scripts/build-release.py`。Mac 构建主机需要 Xcode Command Line Tools（Swift/AppKit）、hdiutil，并先安装 `pip install -r qqmemory/requirements-build-mac.txt`。通过 dmgbuild 及 ds-store/mac-alias 生成 Finder 布局，不要求 Finder 自动化权限。镜像创建、挂载或布局验证失败时构建会失败，不会悄悄退回未配置镜像。

对已验证 App 单独重打外层安装包：

```sh
python scripts/build_dmg.py --app '/path/空间记忆.app' \
  --instructions '/path/安装与使用说明.txt' \
  --output '/path/qqmemory-0.5.3-mac-arm64.dmg'
```

脚本不覆盖已有输出，复制时不修改原 App。生成后验证 DMG 校验和，重新只读挂载，校验包内严格签名、Applications 快捷方式和 Finder 布局文件。原 App 的版本、构建号和源码溯源保留。重新包装不能算重新完成真实 QQ 登录、干净系统安装或 Gatekeeper 全流程验收。

公开发布时更新官网 Mac 下载扩展名、文件大小与 SHA-256，保留旧 ZIP 分享链接。安装包中的源码提交指向 App 本体；仅重打 DMG 外层不代表重新构建 App。

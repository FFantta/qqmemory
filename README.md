# 空间记忆 · qqmemory

用自己的手机 QQ 扫码，把当前可见的 QQ 空间内容与仍可取得的历史互动线索整理成本地档案，导出可离线浏览的网页。

[官网与下载](https://qqmemory.com/) · [问题反馈](https://github.com/FFantta/qqmemory/issues) · [MIT 许可证](LICENSE)

当前源码为 **0.5.6 / Build 15**，桌面安装包正在构建验证；已发布安装包及校验值以[下载清单](downloads/release.json)为准。项目处于朋友测试阶段。提供 Apple 芯片 Mac、Intel Mac 和 Windows x64 安装包，以及有限额的云端体验。

## 直接下载安装包

普通用户及代为安装的 Agent 请优先下载成品，不需要克隆仓库、安装 Python 或编译。

| 你的电脑 | 安装包 |
| --- | --- |
| Apple 芯片 Mac（M 系列） | [下载 DMG](https://qqmemory.com/downloads/qqmemory-0.5.3-mac-arm64.dmg) |
| Intel 芯片 Mac | [下载 DMG](https://qqmemory.com/downloads/qqmemory-0.5.3-mac-x86_64.dmg) |
| Windows x64（Intel / AMD 64 位） | [下载 ZIP](https://qqmemory.com/downloads/qqmemory-0.5.3-windows-x64.zip) |

[安装说明与 Agent 指引](INSTALL.md) · [机器可读下载清单](downloads/release.json) · [GitHub Releases](https://github.com/FFantta/qqmemory/releases)

可将仓库链接和这句话交给 Agent：

> 帮我下载空间记忆。我只需要安装使用，不需要从源码运行。请先确认我的电脑系统和芯片，再从 README 或下载清单选择对应安装包，下载后核对 SHA-256，并说明安装步骤。

如果 Agent 运行在云端，它的操作系统不代表你的电脑；无法确定时应询问你。只能聊天或不能写入本地文件的 Agent 应提供下载链接，由你点击下载。

## 0.5.6 更新

- 修正更新备份时扫码窗口被旧任务状态关闭的问题，扫码前可调整采集与图片下载设置。
- 图片补全单独操作，提供稳定、标准和较快的下载速度选项。
- 离线档案与桌面 App 统一布局，分类、搜索、有图筛选和年份联动，使用当前账号头像和名称。
- 云端体验可边采集边保存图片、实时预览；先保存可用图片，高清检查可单独发起。
- 图片清晰度明确标注，不把可用预览图片当作原图；云端状态提示更简洁。

## 能做什么

- 备份当前可见说说，保存文字、照片及可取得的评论、点赞、头像和 QQ 表情。
- 从“与我相关”等历史互动通知中整理说说、日志和互动线索。
- 提供当前内容备份、标准找回和支持断点的深度找回。
- 本地多账号档案自由切换；添加账号或联网更新时扫码，更新账号需要匹配。
- 导出离线 HTML；大档案按图片体积分包，需下载所有分包并合并目录。
- 仅执行读取与归档，不向 QQ 空间发布、修改或删除内容。

“历史重建”不等于确认原帖被删除，无法保证取得全部历史、删除内容或全部原图。无法确认发布时间时显示“≈ 最早互动”；扫描计划百分比也不是历史恢复比例。

## 下载安装

普通用户从[官网下载](https://qqmemory.com/#download)，无需安装 Python。

- **macOS**：打开 DMG，将“空间记忆”拖到 Applications，复制完成后从“应用程序”打开。若系统阻止首次打开，先尝试打开一次，再到“系统设置 → 隐私与安全性”，确认来源可信后选择“仍要打开”。无需关闭系统安全保护。
- **Windows x64**：解压完整 ZIP，运行其中的“空间记忆.exe”，保留同目录依赖文件；需要 Microsoft Edge WebView2 Runtime。
- 更新前先退出旧版本。Mac 当前为临时签名，尚未完成 Developer ID 签名和苹果公证；Windows 尚无发布者代码签名。干净 Intel/Windows 系统的完整扫码流程仍待进一步验证。

## 从源码运行

需要 Python 3.11+；桌面原生窗口在 macOS/Windows 上使用 pywebview。以下命令从仓库根目录执行：

```sh
git clone https://github.com/FFantta/qqmemory.git
cd qqmemory
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r qqmemory/requirements-desktop.txt
python qqmemory/run_mac.py
```

Windows 激活虚拟环境使用 `.venv\Scripts\activate`，再执行对应的 `python` 命令。`run_mac.py` 是目前沿用的跨平台桌面入口文件名。应用启动后由用户主动添加账号或更新，不自动开始扫码和下载。

新档案默认保存在平台应用数据目录的 `qqmemory` 下；已有 `SpaceMemory` 档案仍会识别，不自动搬动。显式配置支持 `QQMEMORY_DATA_DIR`，旧配置兼容规则见[命名约定](qqmemory/docs/NAMING.md)。不要把自己的数据目录放入版本库。

### 离线开发示例

无需 QQ 登录即可验证导入、搜索与导出；`demo.jsonl` 是合成数据：

```sh
python -m pip install -e ./qqmemory
qqmemory --archive /tmp/qqmemory-demo init
qqmemory --archive /tmp/qqmemory-demo import-jsonl qqmemory/tests/demo.jsonl
qqmemory --archive /tmp/qqmemory-demo list --search 回忆
qqmemory --archive /tmp/qqmemory-demo export /tmp/qqmemory-demo-export
```

导出目录必须尚不存在，且不能位于活动归档内。Windows 请将 `/tmp/...` 换为自己的临时目录。

## 云端实时采集

云端 0.5.5 支持边扫描边下载，并在当前浏览器中按页预览已取得的正文、评论和已保存图片。预览只展示已落地内容，不返回 QQ 原始媒体链接。

普通采集遇到首个有效图片即保存，标记“可用图片 · 高清待检查”，不为比较多个版本而重复下载。完成或暂停保存后，可选择“检查并补全高清”，使用同一 QQ 重新扫码，仅检查媒体；检查完成仍不保证取得原图。离线导出保留图片清晰度状态。未调度或下载失败的图片留在数据库中，后续可继续。

## 云端自托管

云端是独立 Flask/Gunicorn 入口，依赖见 `qqmemory/requirements-cloud.txt`，部署示例见 [render.yaml](render.yaml)。按需自托管；示例配置包含付费实例及持久磁盘，部署前确认服务商收费。

- 必须设置稳定、随机、至少 32 字符的 `QQMEMORY_CLOUD_SECRET`；不要提交或打印真实密钥。
- 使用独立的 `QQMEMORY_CLOUD_ROOT`，不能指向桌面主档案。持久模式还需实际挂载磁盘，并设置 `QQMEMORY_CLOUD_PERSISTENT` 和 `QQMEMORY_CLOUD_DISK_MOUNT`。
- 当前仅支持一个 Gunicorn worker、八个线程和同时一个采集任务；扩展多进程前需要先拆分任务所有权、配额与调度。

```sh
python -m pip install -r qqmemory/requirements-cloud.txt
# 先在运行环境中安全设置 QQMEMORY_CLOUD_SECRET 和 QQMEMORY_CLOUD_ROOT。
gunicorn --chdir qqmemory --workers 1 --threads 8 --timeout 60 --bind 127.0.0.1:8000 run_cloud:app
```

默认每轮文字扫描约 20 分钟，总采集约 30 分钟、1200 次请求；单任务图片约 512 MiB。结果最多保留一小时，可主动删除。持久存储只保证保留期内跨重启保存；QQ 凭据仅在任务内存中，重启会中断采集，继续需同一浏览器和同一 QQ 重新扫码。服务商快照可能保留更久，不能承诺一小时后所有副本全部消失。

## 开发与构建

```sh
python -m pip install -r qqmemory/requirements-dev.txt
PYTHONPATH=qqmemory python -m unittest discover -s qqmemory/tests -q
node qqmemory/tests/test-ui-requests.cjs
node qqmemory/tests/test-ui-accounts.cjs
node qqmemory/tests/test-ui-cloud-progress.cjs
node qqmemory/tests/test-ui-offline.cjs
npm ci --ignore-scripts
python scripts/format-code.py --check
npm run check:format:web
```

Windows 可先用 PowerShell `$env:PYTHONPATH="qqmemory"` 设置包搜索路径。格式工具版本固定；维护源码不压缩为一行。职责与阅读顺序见[代码可读性说明](qqmemory/docs/CODE_READABILITY.md)。云端路由、任务管理与配额目前仍集中在 `cloud_app.py`，前端也尚未完成组件拆分。

发布使用 `scripts/build-release.py`，需要 `GITHUB_SHA` 或 `QQMEMORY_SOURCE_REVISION` 指向精确源码提交；脚本会检查包内版本、执行离线自检并排除私人配置。Mac 另需 Xcode Command Line Tools，以及 `qqmemory/requirements-build-mac.txt` 中的构建依赖，详见 [DMG 构建说明](qqmemory/docs/operations/MAC_INSTALLER.md)。Windows 构建见 GitHub Actions。旧的本机辅助脚本不作为推荐发布入口。

## 隐私与贡献

只使用本工具自己的扫码流程操作有权访问的账号。归档包含你和他人的私人内容，请妥善保管，不要上传 Cookie、二维码、QQ 号、原始响应、数据库、照片或个人导出文件到公开 Issue。

反馈 Bug、提交 PR 前阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题见 [SECURITY.md](SECURITY.md)。

项目自有源码采用 [MIT](LICENSE) 许可；第三方依赖与 QQ 媒体、商标等保留各自权利，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本项目非腾讯官方产品，与腾讯无隶属关系。

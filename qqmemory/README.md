# 空间记忆 · Python 应用核心

桌面入口为 `run_mac.py`（macOS / Windows，pywebview），云端入口为 `run_cloud.py`（Flask / Gunicorn）。SQLite 保存本地档案，离线导出为独立 HTML。官网使用 Vue，与应用核心分别构建和发布。

完整下载、安装、开发命令和限制请阅读仓库根目录的 [README](../README.md) 和 [安装说明](../INSTALL.md)。当前桌面发布版本 0.5.6 / Build 15；安装包以根目录 `downloads/release.json` 为准。

## 核心目录

- `qqmemory/`：采集、媒体保存、SQLite 存储、桌面与云端服务。
- `qqmemory/ui/`：桌面界面。
- `qqmemory/cloud_ui/`：云端体验界面。
- `qqmemory/templates/`：离线档案 HTML 与筛选脚本，无需联网。
- `tests/`：合成数据、离线回归与界面逻辑检查。

运行、测试和构建命令从仓库根目录执行。不要将 QQ 凭据、原始响应、数据库、照片和私人导出上传到版本库。历史重建不代表确认原帖删除，也不保证恢复全部历史或原图。

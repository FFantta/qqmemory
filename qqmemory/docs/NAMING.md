# qqmemory 命名约定

GitHub 仓库 `FFantta/qqmemory`；源码目录 `qqmemory/`，Python 包 `qqmemory`，命令 `qqmemory`，配置前缀 `QQMEMORY_`，中文应用名仍为“空间记忆”。

云端默认根路径 `/var/data/qqmemory-cloud`；持久磁盘上的旧目录在启动时迁移，并创建旧路径兼容链接。浏览器会话 Cookie 改为 `qqmemory_cloud`，旧签名 Cookie 可读并换发新名称。已有稳定密钥不轮换。

桌面新档案默认根目录为平台应用数据目录下的 `qqmemory`；已有 SpaceMemory 档案继续使用，避免生成空档案。旧 SPACE_MEMORY_ 环境变量仅作为兼容回退，QQMEMORY_ 优先。macOS bundle ID 使用 `local.qqmemory.desktop`。

旧源码路径本地保留符号链接，旧 import 路径作为兼容入口。历史运维记录、已发布 ZIP 链接、现有公网云端地址不作全局替换。

# 代码可读性与维护

源码保持可读，不将压缩后的一行文件作为维护源。HTML、CSS、JavaScript 使用 Prettier，Python 使用 Ruff formatter。两个工具的版本固定在 package-lock.json 和 requirements-dev.txt，避免不同机器反复改动格式。

## 日常命令

在仓库根目录执行：

```sh
python -m pip install -r qqmemory/requirements-dev.txt
npm ci --ignore-scripts
python scripts/format-code.py --write
npm run format:web
python scripts/format-code.py --check
npm run check:format:web
```

GitHub 的 Code readability 工作流只检查格式，不自动修改或发布代码。

## 阅读顺序

| 职责 | 入口 |
| --- | --- |
| 桌面账号、扫码与 HTTP API | qqmemory/mac_app.py |
| 云端任务、所有权、配额与下载 | qqmemory/cloud_app.py |
| 环境变量与旧配置兼容 | qqmemory/config.py |
| 采集阶段和文字优先流水线 | qqmemory/trial.py |
| 历史查询计划、分页与断点 | qqmemory/deep_history.py |
| QQ 协议及响应解析 | qqmemory/online.py |
| SQLite 写入与展示数据 | qqmemory/storage.py、read_model.py、timeline.py |
| 图片候选、并发与质量 | photo_slots.py、parallel.py、media.py、quality.py |
| 离线数据导出 | qqmemory/exporting.py、large_export.py |
| 离线网页模板 | qqmemory/templates/offline.html |
| 桌面网页 | qqmemory/ui/index.html、app.css、app.js |
| 云端网页 | qqmemory/cloud_ui/index.html、app.css、app.js |

上表路径以源码父目录 qqmemory/ 为基准。

## 写代码时的约定

- 每个语句单独成行；嵌套逻辑使用清晰缩进，不用分号把整个分支挤在一起。
- 使用具体的变量与函数名；已有稳定接口的改名应单独处理，避免混在纯格式提交中。
- 注释解释原因、数据边界和特殊约束，不重复描述显而易见的赋值。
- 网页结构、样式和交互分别维护。离线模板独立于数据库导出代码；动态归档内容只插入 ARCHIVE_CARDS 标记。
- 云端存储说明使用固定模板标记，不能依赖整段文案逐字匹配，避免换行后说明失效。
- 为函数拆分选择明确的职责边界，不为减少行数增加无意义的包装函数。
- 不在说明或日志中记录 Cookie、会话密钥、私人归档或原始响应正文。

## 验证

纯 Python 格式化比较格式化前后的 AST；模板抽离与文案标记改动单独验证。回归测试检查采集、账号隔离、暂停、断点、导出图片与表情，以及持久存储说明；Windows 构建运行打包后的离线自检。

格式工具不等于完整的结构重构。复杂模块后续应按明确问题逐项拆分，并用行为测试验证，避免一次性改动采集逻辑。

## 规范来源

- Ruff：https://github.com/astral-sh/ruff
- Prettier：https://github.com/prettier/prettier

# AI Daily Digest

一个面向 AI/LLM 资讯的每日流水线：并发采集 HuggingFace Papers、arXiv、GitHub
Trending、RSS、Hacker News、Lobsters、Stack Exchange、Reddit、X 与中文公开平台，
通过 OpenAI 兼容接口生成中文摘要，最后输出 HTML 日报。

## 初始化

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

CI 或需要完全复现当前验证环境时，改用 `requirements.lock`。

在 `.env` 中配置 `LLM_API_KEY`。模型、来源、板块和新鲜度阈值位于
`config.yaml`。

Reddit、X 和中文社区扩展来源分别由 `last30days-skill` 与
`last30days-skill-cn` 提供。本机已安装时会自动发现
`~/.codex/skills/last30days-en` 和 `~/.codex/skills/last30days-cn`；也可以用
`LAST30DAYS_EN_SKILL_DIR`、`LAST30DAYS_CN_SKILL_DIR` 指向 skill 目录。
未安装或单一平台不可用时只跳过对应来源，不会中断整份日报。

X 在云端需要额外凭据，推荐在 `.env`（本地）或 GitHub Actions Secrets（云端）
配置 `XAI_API_KEY`；也支持 `XQUIK_API_KEY`。两者都未配置时 X 会自动跳过，
Reddit 和其他社区仍会正常采集。日报的 `LLM_API_KEY` 不会传给第三方采集脚本。

## 使用

```powershell
# 配置、模板和凭据健康检查（不访问网络）
.venv\Scripts\python.exe -m src.main --check

# 不调用 LLM，验证采集与渲染
.venv\Scripts\python.exe -m src.main --no-llm

# 完整日报
.venv\Scripts\python.exe -m src.main

# 历史日期；不支持历史回放的数据源会明确跳过，且不会覆盖 latest.html
.venv\Scripts\python.exe -m src.main --date 2026-07-10

# 测试
.venv\Scripts\python.exe -m pytest
```

输出位于 `output/YYYY-MM-DD.html`。只有当天报告会更新 `output/latest.html` 和
供静态站点使用的 `output/index.html`。
应用日志保存在 `logs/run.log`，按 5 MB 自动轮转并保留 5 份。
最近一次运行的机器可读状态保存在 `output/run-status.json`。

Hacker News 自帖会直接使用帖子正文；高热外链会在通过公网 URL 安全检查后提取
文章正文。无法获得足够正文的条目会被跳过，避免生成“来源信息不足”的空洞卡片。
模型生成的点评会经过低价值表达过滤；页面每个板块默认展示前 4 条，其余内容可以
按需展开。相同模型、链接和正文的摘要会缓存 30 天，降低重复调用成本；批量摘要
失败时会自动拆分重试，只让最终失败的单条内容降级为原文。

## Windows 定时任务

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Time 08:00
```

注册脚本会提前检查虚拟环境、`.env` 和时间格式；定时入口在抓取前执行健康检查。

## GitHub Actions 云端定时任务

仓库根目录的 `.github/workflows/ai-daily-digest.yml` 会在每天北京时间 08:00
自动运行，也支持在 Actions 页面手动触发。任务安装锁定依赖、生成日报，并把
`output/` 发布到 GitHub Pages，因此本机休眠或关机不会影响执行。固定主页始终
显示最新一期；`archive.html` 提供历史入口，云端会滚动保留最近 31 天的日报。

历史文件保存在保留期为 31 天的 GitHub Actions Artifact 中。每次运行会恢复
上一份归档、加入当天日报并清理过期文件；仓库本身保持只读，不会自动产生提交。
摘要缓存也保存在这份 Artifact 中，因此云端每天运行时可以跨任务复用。

首次启用需要在 GitHub 仓库中完成以下设置：

1. 在 `Settings → Secrets and variables → Actions` 新建仓库 Secret
   `LLM_API_KEY`。
2. 在 `Settings → Pages` 把 `Build and deployment` 的 Source 设为
   `GitHub Actions`。
3. 如需 X 内容，在 `Settings → Secrets and variables → Actions` 新建
   `XAI_API_KEY`（推荐）或 `XQUIK_API_KEY`；未配置时仅跳过 X。

云任务会按固定提交下载两个社区采集引擎，不会跟随上游 `main` 分支自动漂移。

日报页面可以公开访问，但 API key 只在 Actions 运行时注入，不会进入仓库或
Pages 产物。GitHub 的定时任务可能因平台负载延迟几分钟；也可随时手动运行。

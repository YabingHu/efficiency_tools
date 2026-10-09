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

Reddit、YouTube、Bluesky 和中文社区扩展来源分别由 `last30days-skill` 与
`last30days-skill-cn` 提供。本机已安装时会自动发现
`~/.codex/skills/last30days-en` 和 `~/.codex/skills/last30days-cn`；也可以用
`LAST30DAYS_EN_SKILL_DIR`、`LAST30DAYS_CN_SKILL_DIR` 指向 skill 目录。
未安装或单一平台不可用时只跳过对应来源，不会中断整份日报。

X 默认通过开源 `twscrape` 直接采集，不需要付费 API Key。需要自己的 X 登录
会话；本地配置方法见下文。缺少会话时只跳过 X。旧 `last30days` 的付费 X 后端
已从默认来源列表移除，不会自动回退到付费接口。
日报的 `LLM_API_KEY` 和新 X 会话环境变量不会传给第三方采集脚本。
YouTube 优先使用项目锁定的 `yt-dlp` 采集公开视频信息；若本机或云端 IP 被
YouTube 机器人验证拦截，可配置 `SCRAPECREATORS_API_KEY` 作为备用通道。
Bluesky 需配置 `BLUESKY_HANDLE` 与 `BLUESKY_APP_PASSWORD`，未配置时自动跳过。

业界动态中的 Anthropic、Qwen、DeepSeek 和 Kimi 直接读取各自官方发布页面。
Anthropic 不再依赖社区维护的 RSS 镜像；Qwen 也不使用已经长期停更的旧博客 RSS。

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
3. 如需免费 X 采集，在同一页面新建两个 **Repository secrets**：
   `X_AUTH_TOKEN` 填浏览器的 `auth_token` 值，`X_CT0` 填 `ct0` 值。
   工作流仅在生成日报步骤注入这两个 Secrets；本地会话不会自动同步到 GitHub。
   不要使用 Variables，也不要上传 `.private/` 会话文件。
4. 如需 Bluesky 内容，新建 `BLUESKY_HANDLE` 和 `BLUESKY_APP_PASSWORD`；
   App Password 不要使用主账号密码。
5. 如需在云端稳定采集 YouTube，可新建 `SCRAPECREATORS_API_KEY`；不配置时
   仍会尝试免费的 `yt-dlp` 通道，遇到平台机器人验证则只跳过 YouTube。

云任务会按固定提交下载两个社区采集引擎，不会跟随上游 `main` 分支自动漂移。

本地修改需提交并推送到 `main`，云端才会使用新采集器与工作流。设置好两个 X
Secrets 后，可在 Actions → AI Daily Digest → Run workflow 手动验证，查看生成
日报步骤中的 `X 免费采集` 状态及数量。`ok` 表示有采集结果，最终是否展示仍由
去重与选稿决定；`missing_credentials` 表示 Secrets 未注入，`failed` / `partial`
则需检查登录会话或云端网络。失败不会阻止其他来源生成日报。

日报页面可以公开访问，但 API key 只在 Actions 运行时注入，不会进入仓库或
Pages 产物。GitHub 的定时任务可能因平台负载延迟几分钟；也可随时手动运行。

## 免费 X 采集

在本地终端执行（不需要向助手提供密码或 Cookies）：

```powershell
# 交互式保存登录会话，输入内容不会显示
.venv\Scripts\python.exe -m src.x_setup

# 单独验证 X；不会调用 LLM，不会覆盖日报或消耗付费 X API
.venv\Scripts\python.exe -m src.x_setup --check
```

浏览器登录 `https://x.com` 后，打开开发者工具 F12 → Application（应用）→
Cookies → `https://x.com`，将 `auth_token` 和 `ct0` 的 **Value 值**分别粘贴
到命令提示中。无需复制全部 Cookie，也无需提供账号密码。

会话保存在 `.private/x-cookies.json`，运行时数据库为 `.private/x-accounts.db`。
整个 `.private/` 已被 Git 忽略，不在 Pages 的 `output/` 或归档的 `history/` 中。
不要分享、提交或公开这些文件。环境变量 `X_AUTH_TOKEN` + `X_CT0` 优先于本地文件，
两项必须同时设置；如 `.env` 中已有旧值，请清除或更新，避免覆盖新保存的会话。

`sources.x_twscrape` 控制账号名单、搜索词、48 小时窗口和数量限制。默认串行采集
8 个账号，每个查询最多读取 5 条、整次最多保留 40 条；这些账号可按兴趣更换。
原文、作者、发布时间和互动数进入海外社区板块，复用现有摘要与跨天去重。
目前不承诺历史日期回放，历史报告会明确跳过 X。

`output/run-status.json` 的 `source_status.x_twscrape` 提供状态：

- `ok` / `empty`：查询完成，有结果 / 本次未找到符合时间窗口的帖子。
- `missing_credentials` / `invalid_credentials`：未配置或配置格式不正确。
- `partial` / `failed`：超时、限流、登录失效、网络或依赖异常；保留已收到的条目。
- `disabled` / `historical_unsupported`：关闭来源或历史报告不支持。

状态中的 `errors` 仅包含错误类型，不回显凭据或原始响应。登录失效后，在浏览器
重新登录，再运行配置命令；云端则更新两个 Secrets。限流时停止本轮请求，不自动
扩容账号或切换代理。免费通道依赖非官方接口，接口变化可能需要更新依赖。

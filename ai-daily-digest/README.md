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
失败时会自动拆分重试。海外社区使用 1~2 句、约 40~90 字的简体中文速读，
英文摘要会重新生成，最终失败时明确提示摘要暂不可用；其他板块仍可降级为原文。
遇到 HTTP 401/403/404 等鉴权或模型配置错误时停止本轮摘要请求，避免无效拆分重试。
空响应或输出达到 token 上限时直接拆分批次，不再重复请求原批次。默认每批 3 条，
整个摘要阶段受 `llm.total_timeout_seconds` 限制（默认 900 秒），请求超时和重试等待
也受剩余预算约束。预算耗尽后保留缓存及本轮已完成摘要，其余条目使用降级展示，
继续渲染、归档与发布。`run-status.json` 的 `summary_status` 记录摘要成功数、降级数
及是否耗尽预算；数量以摘要阶段的候选为准，之后仍会经过质量筛选。

中英文社区条目须在原始标题或正文中包含明确的 AI 相关信息；来源名、链接、
账号句柄及模型生成的摘要不作为相关性依据。社区板块不适用“至少保留一条”的
保底策略，没有合格内容时显示空状态。中文搜索结果提供有效发布日期时，
还会校验是否位于配置的采集时间范围内；日期缺失的条目仍须通过相关性与质量筛选。

页面顶部统一为「今日必读」，从最终入选正文的文章中按质量和板块覆盖选取最多
5 条，直接复用文章标题、摘要与来源，不再额外生成重复的「今日要点 / 今日主线」。
标题可打开原文；「查看摘要」定位正文，并自动切换论文标签页、展开隐藏卡片。

社区与 GitHub 的原始素材还须满足 `quality.min_source_chars` 的长度硬门槛：
默认社区至少 60 个非空白字符、GitHub 至少 160 个；标题复读、互动统计模板及
模型生成的长摘要都不能补足素材。GitHub 不再用无关热榜项目补满数量，会为最多
`sources.github.content_fetch_limit` 个匹配候选并发补读 README 与最新 Release，
补读失败时保留已有素材，再由质量筛选决定是否展示。

「今日必读」默认要求质量分至少 65、原始素材至少 160 个非空白字符，且具有可用摘要；
缺少细节或摘要降级的条目不会入选，合格内容不足时可少于 5 条。
门槛由 `must_read` 配置。论文摘要按问题、关键方法与结果、适用限制组织，
保留实验条件并明确归因；GitHub 的性能宣称同样保留项目方口径。

中文板块为「中文开发者实践」，最多展示 3 条，暂无合格内容时隐藏板块及导航入口。
默认分别搜索 Claude Code 实测、Qwen 本地部署与智能体踩坑；可修改
`sources.last30days.chinese.queries`（最多 3 条，独立并发查询），或不配置查询数组而
回退到 `topic`。`practice_only` 默认开启：原始内容需包含实测、对比、部署或排障信号，
并提供配置、日志、硬件、耗时等具体线索，单纯概念科普和只有标题的内容不会入选。
有实践选题但素材薄弱的候选会补读公开原文，最多补读 `content_fetch_limit` 个链接
（默认 4 个、最多 3 个并发，连接/读取超时为 5/10 秒），沿用公网地址和响应大小限制。

中文引擎的 `timeout_seconds` 控制整个搜索进程的全局时限，父进程另留 10 秒退出缓冲；
旧 `request_timeout_seconds` 不再传给上游的全局超时参数。适配器保留头条 `abstract`、
知乎 `excerpt`、B站 `description` 和微博 `text`，并按链接去重，避免上游查询内序号
在多查询之间冲突。`run-status.json` 的 `source_status.last30days_chinese` 提供
每个平台的原始条数、适配后条数、广告/无关/过期/非实践过滤数量及每次查询状态。
其中 `accepted` 尚未经过流水线的素材长度、质量与跨天去重，最终展示数量以页面为准；
`missing_engine`、`failed`、`partial` 与正常无结果的 `empty` 分别记录，不回显上游错误正文。
`content_fetch` 记录补读尝试与成功数；平台 `errors` 只保留 HTTP 状态码等固定类别，
补充上游仅在 stderr 报错的情况。`empty` 表示引擎未返回候选，不能证明平台访问正常。

中文引擎通过项目内的 `src/cn_engine_runner.py` 加载兼容层，本地和云端使用相同处理，
不依赖修改被忽略的外部 skill 文件。头条的 `data: null` 会记录 `empty_data`，
有效的空列表仍视为正常无结果；微博跳转访客登录页记录 `login_required`。
`non_json_response`、`invalid_response` 和 `search_results_unavailable` 分别表示
非 JSON 响应、数据结构异常和备用搜索没有返回结果结构。诊断不包含 Cookie、
响应正文或原始异常消息。平台拒绝访问不会因兼容处理而自动恢复。

「中文媒体」的量子位来源会在摘要前补读 `.article` 正文，每次最多 6 条、3 个并发，
连接和读取超时分别为 5/10 秒；失败时保留原有 RSS 摘要。上限由
`sources.rss.content_fetch_limit` 和 `content_workers` 控制，单个 feed 使用
`fetch_content` 与 `content_selector` 开启和指定正文容器。
`run-status.json` 的 `source_status.rss.feeds` 记录逐源状态、补读数量和 RSS 全文数量。
RSS 若只提供搜索页链接且没有有效文章地址，卡片会展开已经收到的 RSS 全文，
并标注「原文链接暂不可用」，避免将搜索页作为原文入口。历史报告随页面保留全文，
不依赖额外文件；源站正常提供文章地址时仍使用文章链接。

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

## 中文作者订阅

微博“宝玉xp”、知乎“苏剑林”已通过 `sources.cn_authors` 接入中文开发者实践板块，
只保留最近 48 小时、具有 AI 实践依据的内容，复用日报去重和质量筛选。
头条候选继续由原搜索通道发现，新入口负责补读正文；不会使用固定旧文章填充。
安装、登录及云端专用 Secret 配置见[中文来源接入说明](docs/chinese-source-pilot.md)。

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

云端使用 X 首页初始化请求签名。固定依赖 `twscrape==0.20.1` 原本使用
`x.com/tesla`，实测 GitHub Actions 对该路径收到 403，而同会话访问首页并采集成功。
兼容适配只替换这一初始化地址，不改搜索接口或登录配置；默认 HTTP 客户端即可使用。
需要单独排查时，运行 Actions 中的 **X Collector Check**，只检查 X，不调用 LLM
或发布日报；该工作流中的 curl 客户端仅用于兼容性对比。

`output/run-status.json` 的 `source_status.x_twscrape` 提供状态：

- `ok` / `empty`：采集到结果 / 本次未保留帖子；`empty` 本身不能证明登录会话有效。
- `missing_credentials` / `invalid_credentials`：未配置或配置格式不正确。
- `partial` / `failed`：超时、限流、登录失效、网络或依赖异常；保留已收到的条目。
- `disabled` / `historical_unsupported`：关闭来源或历史报告不支持。

Actions 的 `Generate daily digest` 步骤搜索 `X 采集诊断`，可查看同一组诊断信息。
`attempted_queries` / `completed_queries` 是尝试和完成的查询数；`received_items` 是
采集库返回的条数，`discarded_items` 是因时间、转推、重复或字段校验未保留的条数。
失败时还会输出 `failure_stage` 和 `account_diagnostic`：

- `authentication_failed`：X 返回认证失败（32）；更新同一次登录的两个 Cookie。
- `access_denied`：X 返回访问受限（326）；在浏览器检查账号验证或限制提示。
- `rate_limit_reported`：X 返回限流错误（88）；稍后重试并检查账号状态。
- `account_inactive`：采集库停用了会话，但未保存可识别的错误原因。
- `account_cooldown`：临时冷却，附 UTC 截止时间 `cooldown_until`；限流、网络或
  其他请求失败均可能触发，不能直接断言 Cookie 失效或 GitHub IP 被封。
- `unknown` / `unavailable`：没有可识别的账号状态线索 / 诊断读取失败。

`upstream_events` 保留触发错误的固定事件类别，补充冷却状态无法提供的原因：
`logged_out_web_page` 表示签名初始化收到未登录页面（不直接等同于 Cookie 过期）；
`rate_limit_response` 表示收到限流响应；`network_retries_exhausted` /
`connection_retries_exhausted` 表示网络重试耗尽；`web_signing_parse_failed` 表示
页面签名解析失败。HTML/Cloudflare 拒绝、异常 HTTP 状态及未知请求异常也有独立分类。
这些事件不会包含原始消息，未识别的日志直接丢弃；没有事件不代表没有上游错误。
`upstream_errors` 进一步提供白名单异常类型、已知出错阶段，以及异常携带的 HTTP
状态码和接口类别。例如 `HttpStatusError` + `web_page_fetch` + `403` 表示
初始化网页请求被拒绝，不能误判为搜索限流；`TypeError` 等则提示代码或依赖异常。
不输出异常消息、调用栈、完整 URL、请求头或响应正文。

状态中的 `errors` 仅包含错误类型；账号诊断只输出固定类别、已知错误码、布尔值和时间，
不回显账号、Cookie、异常正文或原始响应。诊断不会重新登录或清除限流锁。登录失效后，在浏览器
重新登录，再运行配置命令；云端则更新两个 Secrets。限流时停止本轮请求，不自动
扩容账号或切换代理。免费通道依赖非官方接口，接口变化可能需要更新依赖。

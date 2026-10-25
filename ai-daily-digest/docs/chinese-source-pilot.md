# 中文作者订阅与头条正文补读

每日采集通过 `cn_authors` 入口订阅少量作者，复用现有中文开发者实践的 AI 相关性、
广告过滤、实践依据、质量门槛和跨天去重。诊断命令独立运行，不调用 LLM 或发布日报。
使用固定版本的
[MediaCrawler](https://github.com/NanmiCoder/MediaCrawler/tree/8f583999006d5b692272c608440e193ca282e73b)
微博/知乎客户端，以及
[NewsCrawler](https://github.com/NanmiCoder/NewsCrawler/tree/25fb3b4a20186905f5ce38f7a7f854050d402253)
头条正文解析器。MediaCrawler 的许可为 NON-COMMERCIAL LEARNING LICENSE 1.1，
用于个人、非商业的少量来源订阅。

2026-10-25 本机实测：微博宝玉xp 第一页取得 5 条当天动态，已排除 2025 年旧置顶；
头条测试文章经正常 Chrome 加载后提取正文 8,104 字，直接 HTTP 请求拿到的是校验页。
知乎本人登录后成功返回苏剑林 3 条回答和 2 篇文章，均有标题、原文链接、发布时间
及文本；文章文本分别为 1,849 字、3,505 字。样本中最新文章发表于北京时间
2026-10-20 00:32:29，近 48 小时无新内容，状态为 `empty_recent`。接口已通过验证，
本轮不将旧内容送入早报候选。

首批作者：微博[宝玉xp](https://weibo.com/u/1727858283)，偏 AI 编程工具和实践；
知乎[苏剑林](https://www.zhihu.com/people/su-jian-lin-22)，偏模型原理和工程分析。
知乎主页来自其[知乎官方圆桌嘉宾链接](https://www.zhihu.com/roundtable/infra)。

## 安装和检查

```powershell
.venv/Scripts/python.exe scripts/setup_cn_sources.py
.external-skills/cn-pilot-venv/Scripts/python.exe -m src.cn_pilot doctor
.venv/Scripts/python.exe -m src.cn_sources_setup --check
```

依赖安装到独立环境；使用本机已安装的 Chrome。知乎客户端所需 Node 优先从 PATH
查找，缺少时复用 Playwright 自带的 Node。`doctor` 检查版本和客户端导入，
并不代表平台授权或采集已通过。Linux 的独立解释器位于
`.external-skills/cn-pilot-venv/bin/python`；Actions 自动安装依赖和 Chrome。

## 登录并取样

```powershell
.external-skills/cn-pilot-venv/Scripts/python.exe -m src.cn_pilot login --platform weibo
.external-skills/cn-pilot-venv/Scripts/python.exe -m src.cn_pilot collect --platform weibo
.external-skills/cn-pilot-venv/Scripts/python.exe -m src.cn_pilot login --platform zhihu
.external-skills/cn-pilot-venv/Scripts/python.exe -m src.cn_pilot collect --platform zhihu
```

`login` 打开独立 Chrome 窗口，等待本人正常登录，最长 15 分钟。检测到登录 Cookie
后保存并关闭窗口；`session_saved` 仅代表本地存在会话，随后仍需 `collect` 验证接口。
无需复制 Cookie。遇到验证页面由本人操作；采集失败后停止，不轮换账号或代理。

微博只请求作者动态第一页，最多导出 5 条；知乎只请求回答和文章各一页，分别
3 条、2 条，请求之间间隔 2 秒。避开上游会遍历全部历史的 creator 主循环。
只导出最近 48 小时内发布的内容，排除旧置顶和缺少时间的条目。
不采集评论或下载媒体。生产采集对第一页中 AI 相关长帖最多额外补读 3 次，每次间隔
2 秒；遇到补读失败即停止补读。仅保留通过实践筛选的最多 5 条，整次采集最多
90 秒，外部工作进程硬超时 100 秒。原有微博/知乎匿名关键词搜索已从配置中停用。

## 头条正文

```powershell
.external-skills/cn-pilot-venv/Scripts/python.exe -m src.cn_pilot toutiao --url https://www.toutiao.com/article/7660109634812559924/
```

这是旧文章的解析测试，不能当作当天新闻。仅接受 `www.toutiao.com/article/数字`
的 HTTPS 链接，HTTP 禁用重定向，单次请求 15 秒且响应不超过 2 MiB。没有正文时
使用独立 Chrome 正常加载一次，等待正文最多 15 秒；仍是校验页则停止。
明确覆盖上游
默认 Cookie 为空，不复用仓库中的共享凭据。此工具不提供头条关键词搜索。

## 结果与后续接入

会话目录 `.private/cn-pilot/profiles/平台` 和样本 `.private/cn-pilot/平台-samples.json`
均被 Git 忽略，不进入 Pages 或日报归档。状态文件与终端仅输出固定状态、数量、
异常类型；丢弃上游原始输出，避免错误响应或调用栈回显请求凭据。
`平台-probe-samples.json` 另存最多 5 条、不按时间窗过滤的接口验证样本，供检查作者
更新频率和正文质量；这些历史样本不能作为当天候选。

`ok` 表示保留了近期内容，`empty_recent` 表示接口返回有效内容、但近期窗口内没有
可保留条目；状态同时提供 `received_items`、`valid_items` 和样本的
`latest_published_at`（UTC）。`empty` 表示没有解析出有效条目；
`login_required` 表示需要本机登录，`failed` 表示本轮未通过。旧样本不代表本轮成功。

## GitHub Actions

日更工作流安装独立环境，并仅向生成步骤注入专用仓库 Secret `CN_BROWSER_STATE`。
它是仅包含微博、知乎站点 Cookie 的可移植浏览器状态，不包含浏览历史、密码或其他
网站会话。必须由本人明确授权后配置到目标仓库；原始文件留在被忽略的 `.private/`。
刷新会话时，先运行上面的登录命令，再导出：

```powershell
.external-skills/cn-pilot-venv/Scripts/python.exe -m src.cn_sources_setup --export-state
```

产物为 `.private/cn-pilot/cloud-state.b64`，只用于更新当前仓库的对应 Secret，
不要提交或加入 Pages 产物。站点会话失效后标记 `login_required` 或 `failed`，
跳过该来源；不会自动轮换账号。缺少独立环境也只跳过该来源，不阻止其他板块出报。

手动运行 **AI Daily Digest** 时勾选 `cn_source_check_only`，即可只检查云端中文作者
订阅，不调用 LLM、不更新 Pages。正常日更在 `run-status.json.source_status.cn_authors`
记录每位作者返回数、近期条数、选稿数及过滤原因，便于区分接口故障、无更新和未入选。
头条补读单独记录于 `source_status.toutiao_content`；头条搜索若没有发现有效候选，
本轮不会启动浏览器补读。历史回补不会使用当前作者时间线。

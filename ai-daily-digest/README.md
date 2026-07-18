# AI Daily Digest

一个面向 AI/LLM 资讯的每日流水线：并发采集 HuggingFace Papers、arXiv、GitHub
Trending、RSS、Hacker News、Lobsters 和 Stack Exchange，通过 OpenAI 兼容接口
生成中文摘要，最后输出 HTML 日报。

## 初始化

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

CI 或需要完全复现当前验证环境时，改用 `requirements.lock`。

在 `.env` 中配置 `LLM_API_KEY`。模型、来源、板块和新鲜度阈值位于
`config.yaml`。

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

首次启用需要在 GitHub 仓库中完成两项设置：

1. 在 `Settings → Secrets and variables → Actions` 新建仓库 Secret
   `LLM_API_KEY`。
2. 在 `Settings → Pages` 把 `Build and deployment` 的 Source 设为
   `GitHub Actions`。

日报页面可以公开访问，但 API key 只在 Actions 运行时注入，不会进入仓库或
Pages 产物。GitHub 的定时任务可能因平台负载延迟几分钟；也可随时手动运行。

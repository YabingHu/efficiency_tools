# Efficiency Tools

个人效能工具集合。

## 项目列表

| 项目 | 描述 | 技术栈 |
|------|------|--------|
| [workbench](./workbench) | 工作台 — 四象限任务管理、每日任务、团队任务跟进 | React + Vite |
| [ai-daily-digest](./ai-daily-digest) | AI 每日早报 — 抓取 LLM 领域资讯，生成中文摘要早报 HTML | Python |

---

## workbench · 工作台

> 基于史蒂芬·科维「四象限」时间管理理论的个人 & 团队效能管理工具

### 功能

**四象限**
- 按「紧急 × 重要」分四个象限管理任务
- 支持象限间拖拽移动、象限内拖拽排序
- 任务支持标题、描述、截止日期，逾期自动标红
- 一键隐藏已完成任务

**每日任务**
- 固定的每日习惯/例行任务，每天自动重置
- 进度条实时显示今日完成比例
- 支持拖拽排序

**团队任务**
- 按团队成员分组管理任务
- 支持「分配给他们」和「需要跟进」两种类型
- Assigned 类型支持 Milestone 子步骤，带进度条
- 点击状态 badge 循环切换：待开始 → 进行中 → 等待回复 → 已完成

**通用**
- 跨象限全局搜索
- 浏览器推送通知（今日到期任务提醒）
- 数据导出 / 导入（JSON 备份）
- 今日完成任务计数
- 所有数据存储于本地 `localStorage`，无需后端

### 快速开始

```bash
cd workbench
npm install
npm run dev
```

打开 http://localhost:5173 即可使用。

### 技术栈

- **React 19** + **Vite**
- **@dnd-kit** — 拖拽排序
- **localStorage** — 数据持久化
- **Inter** — 字体

---

## ai-daily-digest · AI 每日早报

> 每天定时抓取大模型领域资讯，调用大模型生成中文摘要与点评，输出 HTML 早报

### 功能

- 多源抓取：HuggingFace Daily Papers、arXiv、GitHub Trending、公司博客 RSS、Hacker News
- 调用 OpenAI 兼容接口批量生成中文摘要、一句话点评与重要度评分
- 跨板块去重，按重要度 / 热度排序渲染
- Jinja2 渲染为 HTML 早报，输出 `output/YYYY-MM-DD.html`（同时复制为 `latest.html`）
- 单源抓取失败不影响整体流程

### 快速开始

```powershell
cd ai-daily-digest

# 1. 安装依赖
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 配置 API key
copy .env.example .env    # 然后编辑 .env 填入 LLM_API_KEY

# 3. 手动运行
.venv\Scripts\python.exe -m src.main

# 仅测试抓取与渲染（不调用大模型，无需 key）
.venv\Scripts\python.exe -m src.main --no-llm

# 4. 注册每日定时任务（默认每天 08:00，错过自动补跑）
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Time 08:00
```

生成结果在 `output/YYYY-MM-DD.html`，最新一期同时复制为 `output/latest.html`。

配置见 `config.yaml`（数据源、板块开关与条数、模型 base_url / 模型名、RSS 源列表）。

### 技术栈

- **Python** + `openai` 兼容接口
- **feedparser** / **BeautifulSoup** — RSS 与网页抓取
- **Jinja2** — HTML 渲染

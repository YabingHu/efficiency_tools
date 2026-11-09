# NoteSync

NoteSync 是一个把 Git 操作隐藏在后台的 Markdown/图片同步工具。你照常使用
Obsidian、Typora 或 VS Code 编辑本地文件，NoteSync 自动完成提交、拉取和推送。

## 当前 MVP 能做什么

- 监听本地笔记目录，文件停止变化几秒后自动同步
- 定时获取其他电脑上传的新内容
- 支持 Markdown、图片和任意普通附件
- 完整保留 GitHub 版本历史
- 两台设备同时修改同一文件时不静默覆盖，自动产生冲突副本
- 创建每日、周度和月度周期笔记，并自动打开 Markdown 文件
- 现代化本机网页界面，自动适配深浅色并显示同步状态和错误信息
- 只依赖 Python 3.9+、Tk 和 Git，不依赖第三方 Python 包

## 创建周期笔记

打开“新增笔记”页面，选择一个基准日期，然后创建：

- 每日笔记：`周期笔记/每日/年/月/YYYY-MM-DD.md`
- 周度笔记：`周期笔记/周度/ISO年/YYYY-Www.md`
- 月度笔记：`周期笔记/月度/年/YYYY-MM.md`

周度笔记会预先生成周一至周日的二级标题；月度笔记会根据月份实际天数生成
每天的二级标题，例如：

```markdown
# 2026 年 11 月

## 2026-11-01 星期日

## 2026-11-02 星期一
```

同一个周期的文件已经存在时，NoteSync 只会打开现有文件，不会覆盖已有内容。
“保存目录”可以修改为笔记库内的其他相对路径。

## 首次使用

1. 在 GitHub 创建一个**私有空仓库**，不要勾选自动创建 README。
2. 配置本机访问 GitHub。推荐使用 SSH，并确认下面的命令能够认证：

   ```bash
   ssh -T git@github.com
   ```

3. 启动 NoteSync（启动后会自动打开本机网页界面）：

   ```bash
   cd note-sync
   PYTHONPATH=src python3 -m notesync
   ```

   在 macOS 上也可以直接双击 `run-macos.command`；Windows 可以双击
   `run-windows.bat`（需要已安装 Python 3.9 或更高版本）。

   网页只监听本机 `127.0.0.1`，并使用每次启动时随机生成的访问令牌保护操作
   接口，不会把笔记目录公开到局域网或互联网。旧的 Tk 原生界面仍可备用：

   ```bash
   PYTHONPATH=src python3 -m notesync --native
   ```

4. 选择笔记目录，填写仓库地址，例如：

   ```text
   git@github.com:your-name/notes.git
   ```

5. 点击“保存并启动”。在其他电脑上重复安装和配置，指向同一个仓库即可。

也可以在没有图形界面的环境中同步一次：

```bash
PYTHONPATH=src python3 -m notesync --once \
  --folder /path/to/notes \
  --remote git@github.com:your-name/notes.git \
  --device my-laptop
```

## 冲突处理

如果两台电脑离线时同时修改了 `工作记录.md`，当前电脑的版本保留在原文件中，
远端版本会保存为类似下面的文件：

```text
工作记录.conflict-remote-on-MacBook-20261107-153012.md
```

两个版本都会继续上传，不会丢失。你可以比较后手动合并并删除不需要的副本。

## 注意事项

- 不要让 Obsidian Sync、坚果云、Dropbox 等同时同步同一个目录。
- 后台同步不会弹出 Git 密码输入框；请提前配置 SSH Key 或系统凭据管理器。
- 首版会追踪目录中的所有普通文件。缓存、数据库或超大文件请写入 `.gitignore`。
- Git 会永久保留历史中的图片，大量大图会使仓库逐渐变大；日常截图建议先压缩。
- NoteSync 会忽略 `.DS_Store`、`Thumbs.db`、`Desktop.ini` 和 `.notesync/`。

## 测试

```bash
cd note-sync
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

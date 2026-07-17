@echo off
rem LLM 每日早报 - 定时任务入口
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] 缺少 .venv，请先安装依赖。
  exit /b 2
)
if not exist ".env" (
  echo [ERROR] 缺少 .env，请从 .env.example 复制并配置 API key。
  exit /b 3
)
".venv\Scripts\python.exe" -m src.main --check
if errorlevel 1 exit /b %errorlevel%
".venv\Scripts\python.exe" -m src.main
exit /b %errorlevel%

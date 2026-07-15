@echo off
rem LLM 每日早报 - 定时任务入口
cd /d "%~dp0.."
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m src.main >> "logs\task.log" 2>&1

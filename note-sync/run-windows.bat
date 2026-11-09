@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PYTHONPATH=%SCRIPT_DIR%src"
python -m notesync
if errorlevel 1 pause

@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "D:\Project\MSCodeBase"
"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence\venv\Scripts\python.exe" install.py > "C:\temp\install.log" 2>&1
echo Exit code: %ERRORLEVEL% >> "C:\temp\install.log"

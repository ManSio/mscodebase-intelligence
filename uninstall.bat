@echo off
chcp 65001 >nul
echo Uninstalling...
taskkill /f /im python.exe /fi "WINDOWTITLE eq mscodebase*" >nul 2>&1
taskkill /f /im python.exe /fi "WINDOWTITLE eq main*" >nul 2>&1
taskkill /f /im llama-server.exe >nul 2>&1
taskkill /f /im onnx_server.exe >nul 2>&1
timeout /t 2 /nobreak >nul
for /l %i in (1,1,3) do (rd /s /q "C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence" 2>nul & if not exist "C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence" goto DEL)
echo Failed. Restart PC and run again.
goto END
:DEL
echo Removed.
:END
pause >nul

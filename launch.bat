@echo off
echo Iniciando la aplicacion...
SET PATH=%~dp0python;%PATH%
timeout /t 2 /nobreak
start "" "http://127.0.0.1:8050"
"%~dp0python\python.exe" "%~dp0app.py"
pause
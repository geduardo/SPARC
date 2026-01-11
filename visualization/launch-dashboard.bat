@echo off
REM SPARC Dashboard Launcher

cd /d "%~dp0"

echo Starting SPARC Dashboard...
echo Press Ctrl+C to stop the server
echo.

REM Open dashboard in browser after delay
start "" /b cmd /c "ping -n 3 127.0.0.1 >nul && start http://localhost:8080/dashboard.html"

REM Start server
python -m http.server 8080

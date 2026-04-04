@echo off
REM Start Redis (Docker) then run the one-shot parallel pipeline from project root.
setlocal
cd /d "%~dp0.."
where docker >nul 2>&1
if errorlevel 1 (
  echo Docker not found. Install Docker Desktop or start Redis manually on port 6379.
  exit /b 1
)
docker compose up -d
if errorlevel 1 exit /b 1
python main.py %*
exit /b %ERRORLEVEL%

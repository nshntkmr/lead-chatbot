@echo off
REM One-click start on Windows. First run creates a virtual environment and installs packages.
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv || goto :err
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt || goto :err
)
if not exist .env (
  copy .env.example .env >nul
  echo Created .env - open it and paste your ANTHROPIC_API_KEY, then run start.bat again.
  notepad .env
  exit /b
)
echo Starting on http://localhost:8000
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000
exit /b
:err
echo Setup failed. Make sure Python 3.10+ is installed and on PATH.
pause

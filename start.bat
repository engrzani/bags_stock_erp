@echo off
echo ============================================
echo   Bags Stock ERP - Starting Application
echo ============================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

REM Install dependencies if needed
echo Installing required packages...
pip install -r requirements.txt --quiet

echo.
echo Starting server...
echo Open your browser and go to: http://localhost:5000
echo Press CTRL+C to stop the server
echo.
python app.py
pause

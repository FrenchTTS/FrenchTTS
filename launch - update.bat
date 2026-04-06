@echo off
title FrenchTTS - Launch Updater Development Version
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ERROR: Python cannot be found.
    echo  Install Python 3.10+ from https://python.org
    echo  Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo  Installation of dependencies...
python -m pip install -r requirements.txt -q --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  ERROR during dependency installation.
    echo  Relaunch as administrator if the issue persists.
    echo.
    pause
    exit /b 1
)

echo  Launching updater...
python main.py --update

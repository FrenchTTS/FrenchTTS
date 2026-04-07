@echo off
title FrenchTTS - Build EXE
cd /d "%~dp0"

echo Installation of dependencies...
python -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo ERROR during dependency installation.
    pause
    exit /b 1
)

echo Installation of PyInstaller...
python -m pip install pyinstaller --disable-pip-version-check
if errorlevel 1 (
    echo ERROR during PyInstaller installation.
    pause
    exit /b 1
)

echo Cleaning up old builds...
if exist build        rmdir /s /q build
if exist dist         rmdir /s /q dist
if exist FrenchTTS.spec del /q FrenchTTS.spec

if not exist versions mkdir versions

:: Inject the current git SHA into core/version.py so the exe shows
:: "prod-XXXXXXX" instead of "prod-dev".  Falls back to "dev" gracefully
:: if git is unavailable (the constants.py guard will then show "dev-latest").
for /f "delims=" %%i in ('git rev-parse --short HEAD 2^>nul') do set GIT_SHA=%%i
if not defined GIT_SHA set GIT_SHA=dev
(echo BUILD_ID = "%GIT_SHA%") > core\version.py
echo Build ID: %GIT_SHA%

echo Construction of the executable...
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name FrenchTTS ^
    --icon img\icon.ico ^
    --add-data "img;img" ^
    --add-data "versions;versions" ^
    --collect-all customtkinter ^
    --collect-all pystray ^
    --collect-all PIL ^
    --collect-all faster_whisper ^
    --collect-all ctranslate2 ^
    --hidden-import pystray._win32 ^
    --hidden-import sounddevice ^
    --hidden-import miniaudio ^
    --hidden-import aiohttp ^
    --hidden-import certifi ^
    --hidden-import numpy ^
    --hidden-import keyboard ^
    main.py

set BUILD_RESULT=%errorlevel%

:: Always restore core/version.py so the working tree stays clean.
(echo BUILD_ID = "dev") > core\version.py

if %BUILD_RESULT% neq 0 (
    echo.
    echo ERROR during build. See logs above.
    pause
    exit /b 1
)

echo.
echo Build complete. Executable: dist\FrenchTTS.exe  ^(build ID: %GIT_SHA%^)
echo Config saved in: %%APPDATA%%\FrenchTTS\config.json
pause

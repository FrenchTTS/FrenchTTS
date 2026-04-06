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

echo Construction of the executable...
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name FrenchTTS ^
    --icon img\icon.ico ^
    --add-data "img;img" ^
    --collect-all customtkinter ^
    --collect-all pystray ^
    --collect-all PIL ^
    --hidden-import pystray._win32 ^
    --hidden-import sounddevice ^
    --hidden-import miniaudio ^
    --hidden-import aiohttp ^
    --hidden-import certifi ^
    --hidden-import numpy ^
    --hidden-import keyboard ^
    main.py

if errorlevel 1 (
    echo.
    echo ERROR during build. See logs above.
    pause
    exit /b 1
)

echo.
echo Build complete. Executable: dist\FrenchTTS.exe
echo Config saved in: %%APPDATA%%\FrenchTTS\config.json
pause

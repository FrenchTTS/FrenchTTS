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
if exist build              rmdir /s /q build
if exist dist               rmdir /s /q dist
if exist installer\build    rmdir /s /q installer\build
if exist installer\dist     rmdir /s /q installer\dist
if exist FrenchTTS.spec     del /q FrenchTTS.spec

if not exist versions mkdir versions

:: Inject the current git SHA into core/version.py so the exe shows
:: "prod-XXXXXXX" instead of "prod-dev".  Falls back to "dev" gracefully
:: if git is unavailable (the constants.py guard will then show "dev-latest").
for /f "delims=" %%i in ('git rev-parse --short HEAD 2^>nul') do set GIT_SHA=%%i
if not defined GIT_SHA set GIT_SHA=dev
(echo BUILD_ID = "%GIT_SHA%") > core\version.py
echo Build ID: %GIT_SHA%

:: -----------------------------------------------------------------------
:: Step 1 — Build FrenchTTS.exe (main application)
:: -----------------------------------------------------------------------
echo.
echo [1/3] Building FrenchTTS.exe...
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
git checkout -- core\version.py 2>nul || (echo BUILD_ID = "dev") > core\version.py

if %BUILD_RESULT% neq 0 (
    echo.
    echo ERROR during FrenchTTS.exe build. See logs above.
    pause
    exit /b 1
)

:: Write the build ID alongside FrenchTTS.exe so the installer can display
:: version info ("prod-XXXXXXX → prod-YYYYYYY") without reading the exe.
echo %GIT_SHA%> dist\build_id.txt

:: -----------------------------------------------------------------------
:: Step 2 — Build FrenchTTSUninstaller.exe (tiny, no UI framework)
:: Must be built before the installer so it can be bundled inside it.
:: -----------------------------------------------------------------------
echo.
echo [2/3] Building FrenchTTSUninstaller.exe...
python -m PyInstaller ^
    --clean ^
    installer\uninstaller.spec ^
    --distpath dist ^
    --workpath build\uninstaller

if errorlevel 1 (
    echo.
    echo ERROR during FrenchTTSUninstaller.exe build. See logs above.
    pause
    exit /b 1
)

:: -----------------------------------------------------------------------
:: Step 3 — Build FrenchTTSInstaller.exe (bundles FrenchTTS.exe + uninstaller)
:: -----------------------------------------------------------------------
echo.
echo [3/3] Building FrenchTTSInstaller.exe...
if not exist installer\dist mkdir installer\dist

python -m PyInstaller ^
    --clean ^
    installer\installer.spec ^
    --distpath installer\dist ^
    --workpath installer\build

if errorlevel 1 (
    echo.
    echo ERROR during FrenchTTSInstaller.exe build. See logs above.
    pause
    exit /b 1
)

echo.
echo Build complete.
echo   App:         dist\FrenchTTS.exe
echo   Uninstaller: dist\FrenchTTSUninstaller.exe
echo   Version:     dist\build_id.txt  (%GIT_SHA%^)
echo   Installer:   installer\dist\FrenchTTSInstaller.exe  (build ID: %GIT_SHA%^)
echo Config saved in: %%APPDATA%%\FrenchTTS\config.json
pause

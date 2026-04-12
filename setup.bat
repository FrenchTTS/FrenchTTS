@echo off
title FrenchTTS - Setup
cd /d "%~dp0"

echo.
echo  === FrenchTTS - Installation de l'environnement ===
echo.

:: --- Python ---
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERREUR] Python introuvable.
    echo  Installez Python 3.10+ depuis https://python.org
    echo  et cochez "Add Python to PATH" lors de l'installation.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  Python : %%v

:: --- Dependances du projet ---
echo.
echo  Installation des dependances (requirements.txt)...
python -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  [ERREUR] Echec de l'installation des dependances.
    echo  Relancez en administrateur si le probleme persiste.
    echo.
    pause
    exit /b 1
)

:: --- PyInstaller ---
echo.
echo  Installation de PyInstaller...
python -m pip install pyinstaller --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  [ERREUR] Echec de l'installation de PyInstaller.
    pause
    exit /b 1
)

echo.
echo  Environnement pret. Vous pouvez maintenant utiliser :
echo    launch.bat            - lancer l'app en dev
echo    launch - update.bat   - simuler une mise a jour
echo    test - installer.bat  - tester l'installateur compile
echo    build.bat             - compiler les .exe de release
echo.
pause

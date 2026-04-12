@echo off
title FrenchTTS - Dev
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERREUR] Python introuvable. Lancez setup.bat d'abord.
    echo.
    pause
    exit /b 1
)

echo  Lancement de l'application (mode dev)...
echo  Le splash de mise a jour est bypasse, l'app s'ouvre directement.
echo.
python main.py
if errorlevel 1 (
    echo.
    echo  [ERREUR] L'application s'est arretee avec une erreur.
    pause
)

@echo off
title FrenchTTS - Dev (simulation mise a jour)
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERREUR] Python introuvable. Lancez setup.bat d'abord.
    echo.
    pause
    exit /b 1
)

echo  Lancement avec simulation de mise a jour...
echo  Le splash simule un telechargement sans toucher aucun .exe.
echo  (flag --update bypasse l'API GitHub et anime la barre de progression)
echo.
python main.py --update
if errorlevel 1 (
    echo.
    echo  [ERREUR] L'application s'est arretee avec une erreur.
    pause
)

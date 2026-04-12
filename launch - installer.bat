@echo off
title FrenchTTS - Test Installateur
cd /d "%~dp0"

echo.
echo  === FrenchTTS - Test de l'installateur ===
echo.

set INSTALLER=installer\dist\FrenchTTSInstaller.exe

if not exist "%INSTALLER%" (
    echo  [ERREUR] %INSTALLER% introuvable.
    echo  Lancez build.bat pour compiler l'installateur d'abord.
    echo.
    pause
    exit /b 1
)

echo  Que voulez-vous tester ?
echo.
echo    [1] Premier install  (aucun argument)
echo        Extrait FrenchTTS.exe vers %%LOCALAPPDATA%%\FrenchTTS\
echo        Cree un raccourci Bureau et lance l'application.
echo.
echo    [2] Mode mise a jour  (--pid 0 --target dist\FrenchTTS.exe)
echo        PID 0 = WaitForSingleObject retourne immediatement.
echo        Copie le .exe bundle sur dist\FrenchTTS.exe puis le relance.
echo        Utile pour verifier que la copie et le relaunch fonctionnent.
echo.
set /p CHOIX= Choix (1 ou 2) :

if "%CHOIX%"=="1" goto INSTALL
if "%CHOIX%"=="2" goto UPDATE
echo  Choix invalide.
pause
exit /b 1

:INSTALL
echo.
echo  Lancement en mode premier install...
start "" "%INSTALLER%"
goto END

:UPDATE
if not exist "dist\FrenchTTS.exe" (
    echo.
    echo  [ERREUR] dist\FrenchTTS.exe introuvable.
    echo  Ce mode remplace dist\FrenchTTS.exe - compilez l'app d'abord.
    pause
    exit /b 1
)
echo.
echo  Lancement en mode mise a jour (cible : dist\FrenchTTS.exe)...
start "" "%INSTALLER%" --pid 0 --target "%~dp0dist\FrenchTTS.exe"

:END
echo  Fait.
echo.

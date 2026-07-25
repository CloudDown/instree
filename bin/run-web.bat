@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
title Instree Web

echo.
echo   Instree Web
echo   -----------
echo   Usage: bin\run-web.bat
echo          bin\run-web.bat --ngrok
echo.

if not exist "pyproject.toml" (
    echo [ERREUR] Lance bin\run-web.bat depuis la racine du projet Instree.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\instree-web.exe" (
    echo [..] Installation manquante — lance d'abord bin\run-desktop.bat une fois.
    call "%~dp0run-desktop.bat"
)

if not exist ".venv\Scripts\instree-web.exe" (
    echo [ERREUR] instree-web introuvable apres installation.
    pause
    exit /b 1
)

if defined INSTREE_HOME (
    echo [OK] Instree Web — donnees dans %INSTREE_HOME%
) else if exist "serveur\" (
    echo [OK] Instree Web — donnees dans %CD%\serveur\
) else (
    echo [OK] Instree Web — donnees dans %CD%\var\web\
)
".venv\Scripts\instree-web.exe" %*
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" pause
exit /b %ERR%

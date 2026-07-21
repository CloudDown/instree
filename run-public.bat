@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Instree Public

echo.
echo   Instree (public)
echo   ----------------
echo.

if not exist "pyproject.toml" (
    echo [ERREUR] Lance run-public.bat depuis la racine du projet Instree.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\instree.exe" (
    echo [..] Installation manquante — lance d'abord run.bat une fois.
    call run.bat
)

if not exist ".venv\Scripts\instree.exe" (
    echo [ERREUR] instree introuvable apres installation.
    pause
    exit /b 1
)

echo [OK] Mode public — donnees dans %CD%\serveur\
".venv\Scripts\instree.exe" serve --public %*
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" pause
exit /b %ERR%

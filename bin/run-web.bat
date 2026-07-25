@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
title Instree Web

echo.
echo   Instree Web
echo   -----------
echo   Usage: bin\run-web.bat              ^(ngrok, defaut^)
echo          bin\run-web.bat --no-ngrok   ^(LAN seulement^)
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
    echo [OK] Instree Web — donnees dans %INSTREE_HOME% ^(hors git^)
) else (
    echo [OK] Instree Web — donnees dans %CD%\var\web\ ^(hors git^)
)

set "USE_NGROK=1"
set "ARGS="
:parse_args
if "%~1"=="" goto run
if /i "%~1"=="--no-ngrok" set "USE_NGROK=0" & shift & goto parse_args
if /i "%~1"=="--lan" set "USE_NGROK=0" & shift & goto parse_args
set "ARGS=%ARGS% %1"
shift
goto parse_args

:run
if "%USE_NGROK%"=="1" (
    ".venv\Scripts\instree-web.exe" --ngrok %ARGS%
) else (
    ".venv\Scripts\instree-web.exe" %ARGS%
)
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" pause
exit /b %ERR%

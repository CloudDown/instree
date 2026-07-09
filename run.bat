@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Instree

echo.
echo  Instree - installation et lancement
echo  ===================================
echo.

if not exist "config\instree.toml" (
    echo [ERREUR] config\instree.toml introuvable.
    echo          Lance ce fichier depuis la racine du projet Instree.
    echo.
    pause
    exit /b 1
)

if not exist "data" mkdir "data"

if not exist "config\instree.local.toml" (
    if exist "config\instree.local.toml.example" (
        copy /Y "config\instree.local.toml.example" "config\instree.local.toml" >nul
        echo [OK] config\instree.local.toml cree - configure ta session dans Settings.
        echo.
    )
)

set "PYCMD="
py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>nul && set "PYCMD=py -3.11"
if not defined PYCMD py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>nul && set "PYCMD=py -3.12"
if not defined PYCMD py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>nul && set "PYCMD=py -3"
if not defined PYCMD python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>nul && set "PYCMD=python"

if not defined PYCMD (
    echo [ERREUR] Python 3.11+ introuvable.
    echo.
    echo Installe Python 3.11 ou plus recent :
    echo   https://www.python.org/downloads/
    echo   ou : winget install Python.Python.3.11
    echo.
    echo Coche "Add python.exe to PATH" pendant l'installation.
    echo.
    pause
    exit /b 1
)

echo [OK] Python : %PYCMD%
for /f "delims=" %%V in ('%PYCMD% -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2^>nul') do echo      Version %%V
echo.

if exist ".venv\Scripts\instree.exe" goto :launch

echo -- Premiere installation --
echo.

where uv >nul 2>&1
if not errorlevel 1 (
    echo [..] Installation avec uv...
    uv sync
    if not errorlevel 1 goto :check_install
    echo [AVERTISSEMENT] uv sync a echoue, repli sur pip...
)

if not exist ".venv\Scripts\python.exe" (
    echo [..] Creation de l'environnement virtuel...
    %PYCMD% -m venv .venv
    if errorlevel 1 (
        echo [ERREUR] Impossible de creer .venv
        pause
        exit /b 1
    )
)

echo [..] Installation des dependances avec pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip wheel setuptools
if errorlevel 1 (
    echo [ERREUR] Mise a jour de pip echouee
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 (
    echo [ERREUR] Installation du projet echouee
    pause
    exit /b 1
)

:check_install
if not exist ".venv\Scripts\instree.exe" (
    echo [ERREUR] instree.exe introuvable apres installation.
    pause
    exit /b 1
)

echo.
echo [OK] Installation terminee.
echo.

:launch
echo -- Interface web --
echo.
echo  Ouvre http://127.0.0.1:8765 dans ton navigateur
echo  Ctrl+C pour arreter le serveur
echo.

start "" "http://127.0.0.1:8765"

".venv\Scripts\instree.exe" serve %*
set "EXIT_CODE=%ERRORLEVEL%"

if %EXIT_CODE% neq 0 (
    echo.
    echo [ERREUR] Le serveur s'est arrete avec le code %EXIT_CODE%
    pause
)

endlocal
exit /b %EXIT_CODE%

@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Instree

echo.
echo   Instree
echo   -------
echo.

if not exist "config\instree.toml" (
    echo [ERREUR] Lance run.bat depuis la racine du projet Instree.
    pause
    exit /b 1
)

if not exist "data" mkdir "data"

if not exist "config\instree.local.toml" (
    if exist "config\instree.local.toml.example" (
        copy /Y "config\instree.local.toml.example" "config\instree.local.toml" >nul
        echo [OK] Config locale creee.
    )
)

call :refresh_path
call :find_python
if defined PYEXE goto :have_python

echo [..] Python introuvable — installation automatique...
call :install_python
call :refresh_path
call :find_python

if not defined PYEXE (
    echo [ERREUR] Impossible d'installer Python automatiquement.
    echo          Installe Python 3.11+ depuis https://www.python.org/downloads/
    echo          ^(coche "Add python.exe to PATH"^) puis relance run.bat
    pause
    exit /b 1
)

:have_python
for /f "delims=" %%V in ('"!PYEXE!" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2^>nul') do set "PYVER=%%V"
echo [OK] Python !PYVER!

if exist ".venv\Scripts\instree.exe" goto :launch

echo [..] Premiere installation des dependances...

where uv >nul 2>&1
if errorlevel 1 (
    call :try_install_uv
    call :refresh_path
)

where uv >nul 2>&1
if not errorlevel 1 (
    uv sync
    if not errorlevel 1 goto :check_install
    echo [..] uv sync a echoue, repli sur pip...
)

if not exist ".venv\Scripts\python.exe" (
    "!PYEXE!" -m venv .venv
    if errorlevel 1 (
        echo [ERREUR] Creation du venv impossible.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -e .
if errorlevel 1 (
    echo [ERREUR] Installation des dependances echouee.
    pause
    exit /b 1
)

:check_install
if not exist ".venv\Scripts\instree.exe" (
    echo [ERREUR] instree.exe introuvable apres installation.
    pause
    exit /b 1
)
echo [OK] Installation terminee.

:launch
echo.
echo   http://127.0.0.1:8765
echo   Ctrl+C pour arreter
echo.
start "" "http://127.0.0.1:8765"
".venv\Scripts\instree.exe" serve %*
set "EXIT_CODE=!ERRORLEVEL!"
if not "!EXIT_CODE!"=="0" (
    echo.
    echo [ERREUR] Serveur arrete ^(code !EXIT_CODE!^).
    pause
)
exit /b !EXIT_CODE!

:: ---------- helpers ----------

:refresh_path
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%LOCALAPPDATA%\Programs\Python\Launcher;%USERPROFILE%\.local\bin;%PATH%"
for /f "skip=2 tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do if not "%%B"=="" set "PATH=%%B;!PATH!"
for /f "skip=2 tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do if not "%%B"=="" set "PATH=%%B;!PATH!"
exit /b 0

:find_python
set "PYEXE="
for %%L in (3.12 3.11 3) do (
    if not defined PYEXE (
        for /f "delims=" %%P in ('py -%%L -c "import sys; print(sys.executable)" 2^>nul') do (
            "%%P" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
            if not errorlevel 1 set "PYEXE=%%P"
        )
    )
)
if not defined PYEXE (
    for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
        "%%P" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
        if not errorlevel 1 set "PYEXE=%%P"
    )
)
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if defined PYEXE (
    "!PYEXE!" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
    if errorlevel 1 set "PYEXE="
)
exit /b 0

:install_python
where winget >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] winget introuvable — impossible d'installer Python auto.
    exit /b 1
)
echo [..] winget install Python.Python.3.12 ...
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity
if errorlevel 1 (
    echo [..] Essai Python 3.11...
    winget install -e --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity
)
timeout /t 3 /nobreak >nul
exit /b 0

:try_install_uv
where winget >nul 2>&1
if not errorlevel 1 (
    winget install -e --id astral-sh.uv --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity >nul 2>&1
)
exit /b 0

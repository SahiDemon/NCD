@echo off
setlocal EnableDelayedExpansion
title  NDC  -  Nexus Download Collection
color 0B

echo.
echo   ==========================================
echo    Nexus Download Collection  -  Launcher
echo   ==========================================
echo.

:: ── Step 1: Find Python ───────────────────────────────────────────────────
set PYTHON=

:: Try 'python' on PATH
python --version >nul 2>&1
if %errorlevel%==0 (
    set PYTHON=python
    goto :found_python
)

:: Try 'python3' on PATH
python3 --version >nul 2>&1
if %errorlevel%==0 (
    set PYTHON=python3
    goto :found_python
)

:: Try common install locations
for %%P in (
    "%LocalAppData%\Programs\Python\Python313\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
) do (
    if exist %%P (
        set PYTHON=%%~P
        goto :found_python
    )
)

:: ── Python not found: try winget, then manual ─────────────────────────────
echo   [!] Python is not installed on this PC.
echo.
echo   Attempting auto-install via winget (Windows Store)...
echo.

winget install --id Python.Python.3.13 -e --source winget --accept-package-agreements --accept-source-agreements
if %errorlevel%==0 (
    echo.
    echo   [OK] Python installed. Restarting launcher...
    echo.
    :: Refresh PATH by reopening this script
    start "" "%~f0"
    exit
)

:: winget failed — send user to download manually
echo.
echo   =====================================================
echo    Could not auto-install Python.
echo    Please install it manually:
echo.
echo      https://www.python.org/downloads/
echo.
echo    Tick "Add Python to PATH" during install,
echo    then double-click Run NDC.bat again.
echo   =====================================================
echo.
pause
exit /b 1

:found_python
echo   [OK] Python found: %PYTHON%

:: ── Step 2: Ensure pip is available ─────────────────────────────────────
echo   Checking pip...
%PYTHON% -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   [!] pip not found. Bootstrapping...
    %PYTHON% -m ensurepip --upgrade
    if %errorlevel% neq 0 (
        echo.
        echo   [ERROR] Could not install pip automatically.
        echo   Run this command manually in a terminal:
        echo     python -m ensurepip --upgrade
        echo.
        pause
        exit /b 1
    )
)
echo   [OK] pip ready.

:: ── Step 3: Ensure required packages are installed ───────────────────────
echo   Checking dependencies...

set MISSING=0

%PYTHON% -c "import requests" >nul 2>&1
if %errorlevel% neq 0 (
    echo   Installing: requests
    %PYTHON% -m pip install requests -q
    set MISSING=1
)

%PYTHON% -c "import browser_cookie3" >nul 2>&1
if %errorlevel% neq 0 (
    echo   Installing: browser-cookie3
    %PYTHON% -m pip install browser-cookie3 -q
    set MISSING=1
)

%PYTHON% -c "import curl_cffi" >nul 2>&1
if %errorlevel% neq 0 (
    echo   Installing: curl-cffi
    %PYTHON% -m pip install curl-cffi -q
    set MISSING=1
)

%PYTHON% -c "import rich" >nul 2>&1
if %errorlevel% neq 0 (
    echo   Installing: rich
    %PYTHON% -m pip install rich -q
    set MISSING=1
)

if %MISSING%==1 (
    echo   [OK] Dependencies installed.
) else (
    echo   [OK] All dependencies present.
)

:: ── Step 4: Launch NDC ───────────────────────────────────────────────────
echo.
echo   Starting NDC...
echo.
%PYTHON% "%~dp0ndc.py"

echo.
pause

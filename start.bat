@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul 2>&1
title Miyora - Launcher

rem Always run from the directory containing this BAT file.
pushd "%~dp0"
if errorlevel 1 goto :folder_error

echo ===================================
echo           Miyora Launcher
echo ===================================
echo.
echo [INFO] Project folder: "%CD%"

rem The Python core is the primary Miyora application.
if exist "main.py" goto :run_python
if exist "app.py" goto :run_python

rem Also support unpacking the project inside one extra directory.
for /d %%D in (*) do (
    if exist "%%~fD\main.py" (
        pushd "%%~fD"
        goto :run_python
    )
)
echo [ERROR] main.py not found.
echo [INFO] Download the complete Miyora repository, not only start.bat.
goto :failed

:run_python
set "PYTHON_CMD="
where py.exe >nul 2>&1
if errorlevel 1 goto :check_python_exe
py -3 -c "import sys" >nul 2>&1
if errorlevel 1 goto :check_python_exe
set "PYTHON_CMD=py -3"
goto :launch

:check_python_exe
where python.exe >nul 2>&1
if errorlevel 1 goto :install_python
python -c "import sys" >nul 2>&1
if errorlevel 1 goto :install_python
set "PYTHON_CMD=python"
goto :launch

:install_python
echo [INFO] Python not found. Trying winget installation...
where winget.exe >nul 2>&1
if errorlevel 1 goto :no_python
winget install --id Python.Python.3.13 --exact --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :no_python
echo [INFO] Python installation completed. Restart launcher to refresh PATH.
goto :failed

:no_python
echo [ERROR] Python is required: https://www.python.org/downloads/windows/
goto :failed

:launch
rem Port 0 asks Windows to allocate an available local port.
set "PORT=0"
set "HOST=127.0.0.1"
echo [INFO] Starting Miyora...
echo [INFO] Browser will open automatically.
echo [INFO] Keep this window open while using Miyora.
echo.
if exist "main.py" (
    %PYTHON_CMD% -u "main.py"
) else (
    %PYTHON_CMD% -u "app.py"
)
echo.
echo [ERROR] Miyora process exited. Exit code: %ERRORLEVEL%
goto :failed

:folder_error
echo [ERROR] Could not open the project folder.
goto :failed

:failed
echo.
echo [INFO] This window will stay open until you press a key.
pause
exit /b 1

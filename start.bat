@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul 2>&1
title Miyora Launcher
pushd "%~dp0"
if errorlevel 1 goto :folder_error
echo ===================================
echo           Miyora Launcher
echo ===================================
echo.
echo [INFO] Project folder: "%CD%"

if exist "main.py" goto :locate_python
for /d %%D in (*) do (
  if exist "%%~fD\main.py" (
    pushd "%%~fD"
    goto :locate_python
  )
)
echo [ERROR] main.py not found. Download the entire repository.
goto :failed

:locate_python
set "PYTHON_EXE="
rem Prefer actual executables. The Windows py launcher may have stale registry entries.
for /f "delims=" %%P in ('where python.exe 2^>nul') do (
  if not defined PYTHON_EXE call :probe "%%~fP"
)
rem Also check commonly installed per-user Python locations on any Windows drive.
if not defined PYTHON_EXE (
  for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if not defined PYTHON_EXE call :probe "%%~fD\python.exe"
  )
)
if not defined PYTHON_EXE (
  for /d %%D in ("%ProgramFiles%\Python3*") do (
    if not defined PYTHON_EXE call :probe "%%~fD\python.exe"
  )
)
if defined PYTHON_EXE goto :launch
echo [WARN] No working Python interpreter found.
where winget.exe >nul 2>&1
if errorlevel 1 goto :no_python
echo [INFO] Installing Python 3.13 via winget...
winget install --id Python.Python.3.13 --exact --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :no_python
rem Recheck the executable directly; PATH may not be refreshed yet.
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python313*") do (
  if not defined PYTHON_EXE call :probe "%%~fD\python.exe"
)
if not defined PYTHON_EXE (
  echo [INFO] Python installed. Close and reopen this launcher.
  goto :failed
)
goto :launch

:probe
if not exist "%~1" exit /b 0
"%~1" -c "import sys; assert sys.version_info >= (3, 9); print(sys.executable)" >nul 2>&1
if not errorlevel 1 set "PYTHON_EXE=%~1"
exit /b 0

:launch
echo [INFO] Python: "%PYTHON_EXE%"
set "PORT=0"
set "HOST=127.0.0.1"
echo [INFO] Starting Miyora...
echo [INFO] Keep this window open. Stop with Ctrl+C.
echo.
"%PYTHON_EXE%" -u "main.py"
set "MIYORA_EXIT=%ERRORLEVEL%"
echo.
echo [ERROR] Miyora stopped with exit code %MIYORA_EXIT%.
goto :failed

:no_python
echo [ERROR] Python unavailable. Install Python from https://www.python.org/downloads/windows/
goto :failed

:folder_error
echo [ERROR] Cannot open the project directory.
:failed
echo.
echo [INFO] Press any key to close this window.
pause
exit /b 1

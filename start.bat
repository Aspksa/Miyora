@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title Miyora Launcher
pushd "%~dp0" || goto :fail

echo ===================================
echo          Miyora Launcher
echo ===================================
echo.

rem Keep delayed expansion disabled: paths containing !, ^, &, ( and ) are safer.
rem Use quoted paths and PowerShell for Unicode-safe port detection.
where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Windows PowerShell is required.
  goto :fail
)

rem Python may be installed as py.exe or python.exe.
call :check_python
if errorlevel 1 (
  echo [INFO] Python was not found. Installing Python 3.13 via winget...
  where winget.exe >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] winget is missing. Install Python from https://www.python.org/downloads/windows/
    goto :fail
  )
  winget install --id Python.Python.3.13 --exact --source winget --accept-package-agreements --accept-source-agreements --silent
  if errorlevel 1 (
    echo [ERROR] Python installation failed. Check winget output above.
    goto :fail
  )
  rem A newly installed Python may not be in this process PATH yet.
  call :check_python
  if errorlevel 1 (
    echo [INFO] Python installed, but PATH may need a new terminal session.
    echo [INFO] Restart this launcher after signing out and back in if Python is required.
  )
)

where node.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js is missing. Install Node.js LTS from https://nodejs.org/
  goto :fail
)
where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm.cmd is missing. Repair your Node.js installation.
  goto :fail
)
if not exist "package.json" (
  echo [ERROR] package.json not found in the project directory.
  echo [INFO] Add the Miyora application files first.
  goto :fail
)

if not exist "node_modules\" (
  echo [INFO] Installing npm dependencies...
  call npm.cmd install
  if errorlevel 1 goto :fail
)

rem Bind to port 0 and let Windows select an available TCP port.
rem There is a small race between releasing the socket and app startup.
set "MIYORA_PORT="
for /f "usebackq delims=" %%P in (`powershell.exe -NoProfile -NonInteractive -Command "$l=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,0); try { $l.Start(); $l.LocalEndpoint.Port } finally { $l.Stop() }"`) do set "MIYORA_PORT=%%P"
if not defined MIYORA_PORT (
  echo [ERROR] Could not select a free port.
  goto :fail
)
set "PORT=%MIYORA_PORT%"
set "HOST=127.0.0.1"
echo [INFO] Selected port: %MIYORA_PORT%
echo [INFO] Starting application...
echo [INFO] URL: http://127.0.0.1:%MIYORA_PORT%/
echo.

rem --port and --host are supported by Vite. Other dev scripts may need adjustment.
call npm.cmd run dev -- --host 127.0.0.1 --port %MIYORA_PORT% --strictPort
if errorlevel 1 goto :fail
popd
exit /b 0

:check_python
where py.exe >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys; print(sys.version)" >nul 2>&1
  if not errorlevel 1 exit /b 0
)
where python.exe >nul 2>&1
if not errorlevel 1 (
  python -c "import sys; print(sys.version)" >nul 2>&1
  if not errorlevel 1 exit /b 0
)
exit /b 1

:fail
echo.
echo [ERROR] Miyora could not start. See details above.
pause
popd
exit /b 1

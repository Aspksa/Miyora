@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title Miyora Launcher
set "ROOT=%~dp0"
pushd "%ROOT%"
if errorlevel 1 goto :folder_error

echo ===================================
echo          Miyora Launcher
echo ===================================
echo.

rem Find a known app entry point in the launcher folder or one level below.
set "APP_DIR="
set "APP_KIND="
call :detect "."
if defined APP_KIND goto :found
for /d %%D in (*) do (
  if not defined APP_KIND call :detect "%%~fD"
)
:found
if not defined APP_KIND goto :missing_app
pushd "%APP_DIR%"
if errorlevel 1 goto :failed
echo [INFO] Application directory found.
echo [INFO] Type: %APP_KIND%

if /i "%APP_KIND%"=="python" goto :python_app
if /i "%APP_KIND%"=="node" goto :node_app
goto :failed

:node_app
where node.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js is missing: https://nodejs.org/
  goto :failed
)
where npm.cmd >nul 2>&1
if errorlevel 1 goto :failed
if not exist "node_modules\" (
  call npm.cmd install
  if errorlevel 1 goto :failed
)
call :select_port
if not defined MIYORA_PORT goto :failed
set "PORT=%MIYORA_PORT%"
set "HOST=127.0.0.1"
echo [INFO] Selected port: %MIYORA_PORT%
rem The port flags below apply to Vite dev scripts.
call npm.cmd run dev -- --host 127.0.0.1 --port %MIYORA_PORT% --strictPort
if errorlevel 1 goto :failed
goto :success

:python_app
call :python_check
if not errorlevel 1 goto :python_ready
echo [INFO] Installing Python via winget...
where winget.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] winget unavailable. Install Python from https://www.python.org/downloads/windows/
  goto :failed
)
winget install --id Python.Python.3.13 --exact --source winget --accept-package-agreements --accept-source-agreements --silent
if errorlevel 1 goto :failed
call :python_check
if errorlevel 1 (
  echo [ERROR] Python installed but is not visible yet. Restart Windows terminal and retry.
  goto :failed
)
:python_ready
if exist "requirements.txt" (
  call :python_exec -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
)
call :select_port
if not defined MIYORA_PORT goto :failed
set "PORT=%MIYORA_PORT%"
set "HOST=127.0.0.1"
echo [INFO] Selected port: %MIYORA_PORT%
if exist "main.py" (
  call :python_exec "main.py"
) else (
  call :python_exec "app.py"
)
if errorlevel 1 goto :failed
goto :success

:detect
if exist "%~1\package.json" (
  set "APP_DIR=%~1"
  set "APP_KIND=node"
  exit /b 0
)
if exist "%~1\main.py" (
  set "APP_DIR=%~1"
  set "APP_KIND=python"
  exit /b 0
)
if exist "%~1\app.py" (
  set "APP_DIR=%~1"
  set "APP_KIND=python"
)
exit /b 0

:python_check
where py.exe >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 exit /b 0
)
where python.exe >nul 2>&1
if not errorlevel 1 (
  python -c "import sys" >nul 2>&1
  if not errorlevel 1 exit /b 0
)
exit /b 1

:python_exec
where py.exe >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 (
    py -3 %*
    exit /b %errorlevel%
  )
)
python %*
exit /b %errorlevel%

:select_port
set "MIYORA_PORT="
for /f "delims=" %%P in ('powershell.exe -NoProfile -NonInteractive -Command "$l=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,0);try{$l.Start();$l.LocalEndpoint.Port}finally{$l.Stop()}"') do set "MIYORA_PORT=%%P"
exit /b 0

:missing_app
echo [ERROR] No application entry point found.
echo [INFO] Checked this directory and immediate subdirectories for:
echo [INFO] package.json, main.py, or app.py
echo [INFO] The GitHub repository currently contains only README.md and start.bat.
echo [INFO] Add the actual Miyora source code to run it.
goto :failed_root

:folder_error
echo [ERROR] Cannot open the launcher directory.
pause
exit /b 1

:failed
echo.
echo [ERROR] Application could not start.
popd
:failed_root
echo [INFO] Review the messages above.
pause
popd
exit /b 1

:success
popd
popd
exit /b 0

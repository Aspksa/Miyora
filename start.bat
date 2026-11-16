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
if not exist "launcher.ps1" (
  echo [ERROR] launcher.ps1 is missing. Download the complete Miyora repository.
  goto :failed
)
where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Windows PowerShell is required.
  goto :failed
)
if /I "%~1"=="--doctor" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1" -Doctor
) else (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1"
)
set "MIYORA_EXIT=%ERRORLEVEL%"
if "%MIYORA_EXIT%"=="0" (
  popd
  exit /b 0
)
echo.
echo [ERROR] Miyora failed. See launcher-diagnostic.txt.
goto :failed

:folder_error
echo [ERROR] Cannot access launcher directory.
:failed
echo.
echo [INFO] Press any key to close this window.
pause
exit /b 1

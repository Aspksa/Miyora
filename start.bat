@echo off
setlocal
chcp 65001 >nul
title Miyora Launcher
cd /d "%~dp0"

echo === Miyora Launcher ===

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js is not installed or is not in PATH.
  goto :fail
)
where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm is not installed or is not in PATH.
  goto :fail
)
if not exist "package.json" (
  echo [ERROR] package.json not found in "%CD%".
  echo Add the application source files before launching.
  goto :fail
)
if not exist "node_modules\" (
  echo Installing dependencies...
  call npm install
  if errorlevel 1 goto :fail
)
echo Starting Miyora...
call npm run dev
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Miyora could not start. See the message above.
pause
exit /b 1

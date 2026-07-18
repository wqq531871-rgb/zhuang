@echo off
chcp 65001 >nul
setlocal EnableExtensions

set PROJECT_DIR=%~dp0..\..
for %%I in ("%PROJECT_DIR%") do set PROJECT_DIR=%%~fI

set APP_ENTRY=%PROJECT_DIR%\ui\realtime_dashboard_runner.py

set PY_EXE=
where py >nul 2>&1 && set PY_EXE=py -3
if not defined PY_EXE (
  where python >nul 2>&1 && set PY_EXE=python
)
if not defined PY_EXE (
  echo [ERROR] Python not found on PATH.
  pause
  exit /b 1
)

if not exist "%APP_ENTRY%" (
  echo [ERROR] App entry not found: %APP_ENTRY%
  pause
  exit /b 1
)

cd /d "%PROJECT_DIR%"
%PY_EXE% "%APP_ENTRY%" --project "%PROJECT_DIR%"
pause
endlocal

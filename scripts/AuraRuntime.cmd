@echo off
setlocal
set "AURA_ROOT=%~dp0"
set "AURA_RUNNER=%AURA_ROOT%scripts\run_runtime.ps1"
if not exist "%AURA_RUNNER%" set "AURA_RUNNER=%AURA_ROOT%run_runtime.ps1"

cd /d "%AURA_ROOT%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%AURA_RUNNER%"
set AURA_EXIT_CODE=%ERRORLEVEL%

if not "%AURA_EXIT_CODE%"=="0" (
  echo.
  echo Aura Runtime exited with code %AURA_EXIT_CODE%.
  echo Review the messages above, then press any key to close this window.
  pause >nul
  exit /b %AURA_EXIT_CODE%
)

exit /b 0

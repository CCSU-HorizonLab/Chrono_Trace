@echo off
setlocal

cd /d "%~dp0"

echo ==> Chrono Trace one-click packaging
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0build_release.ps1" %*
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% EQU 0 (
    echo Packaging completed successfully.
) else (
    echo Packaging failed with exit code %EXIT_CODE%.
)

pause
exit /b %EXIT_CODE%

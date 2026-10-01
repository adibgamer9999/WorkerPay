@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo              WORKERPAY - WINDOWS LOCAL BUILDER
 echo ============================================================
echo.
echo This builder does not require Python to already be on PATH.
echo It can find a supported Python, use WinGet, or create a
 echo private Python runtime automatically.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_windows.ps1"
if errorlevel 1 (
    echo.
    echo ============================================================
    echo                       BUILD FAILED
    echo ============================================================
    echo.
    echo See BUILD_LOG.txt for the exact failure.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo                      BUILD SUCCESS
 echo ============================================================
echo.
echo Your real application is:
echo     dist\WorkerPay\WorkerPay.exe
echo.
echo Portable release:
echo     release\WorkerPay-Portable.zip
echo.
start "" "%~dp0dist\WorkerPay\WorkerPay.exe"
endlocal

@echo off
chcp 65001 >nul
echo =================================================================
echo   run_scan.bat -- Needful Things
echo =================================================================
echo.

cd /d "%~dp0"
python scan_critical_deps.py

echo.
pause

@echo off
chcp 65001 >nul
echo =================================================================
echo   run_scan.bat -- needfull things
echo =================================================================
echo.

cd /d "%~dp0"
python scan_critical_deps.py

echo.
pause

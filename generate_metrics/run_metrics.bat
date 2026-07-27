@echo off
chcp 65001 >nul
echo =================================================================
echo   run_metrics.bat — Garmin Local Archive
echo =================================================================
echo.

cd /d "%~dp0"
generate_metrics.py

echo.
pause

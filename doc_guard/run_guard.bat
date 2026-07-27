@echo off
chcp 65001 >nul
echo =================================================================
echo   run_guard.bat — Garmin Local Archive
echo =================================================================
echo.

cd /d "%~dp0"
python doc_guard.py

echo.
pause

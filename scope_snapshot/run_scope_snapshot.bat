@echo off
chcp 65001 >nul
echo =================================================================
echo   run_scope_snapshot.bat — Needful Things
echo =================================================================
echo.

cd /d "%~dp0"
python scope_snapshot.py

echo.
pause

@echo off
setlocal
title LocalTranslate — Quality Test
echo.
echo  LocalTranslate — Quality Test Runner
echo.

:: Python check
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found.
    pause
    exit /b 1
)

:: Server check
curl -s --max-time 3 http://127.0.0.1:8000/config >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] LocalTranslate server not reachable.
    echo  Start translator.bat first, then re-run this script.
    echo.
    pause
    exit /b 1
)

:: Run
cd /d "%~dp0"
python test.py

pause

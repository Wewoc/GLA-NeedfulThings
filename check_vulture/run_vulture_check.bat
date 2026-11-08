@echo off
chcp 65001 >nul
title check_vulture -- Needful Things

echo.
echo ================================================================
echo   check_vulture -- Dead Code Finder
echo ================================================================
echo.

cd /d "%~dp0"

:: Needs vulture in the python that runs this: pip install vulture
:: Pass --target-version vX.Y.Z to record a target version in the result.

python check_vulture.py %*

echo.
pause

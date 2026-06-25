@echo off
chcp 65001 >nul
title build_dep_map -- needfull things

echo.
echo ================================================================
echo   build_dep_map -- Dependency Map Generator
echo ================================================================
echo.

cd /d "%~dp0"

:: Optional: --baseline path to an earlier dep_map_records.json
:: Example: python build_dep_map.py --baseline output\2026-06-23_Run-01\dep_map_records.json
::
:: Without --baseline: no delta, absolute output + snapshot only
:: With --baseline:    delta is computed and written as dep_map_delta.md

python build_dep_map.py %*
if errorlevel 1 (
    echo.
    echo ERROR: build_dep_map.py exited with an error.
    pause
    exit /b 1
)

echo.
echo Output written to: output\
echo.
pause

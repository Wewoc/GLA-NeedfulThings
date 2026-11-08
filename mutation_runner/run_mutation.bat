@echo off
chcp 65001 >nul
title mutation_runner -- Needful Things

echo.
echo ================================================================
echo   mutation_runner -- Mutation Test Runner (Cosmic Ray)
echo ================================================================
echo.

cd /d "%~dp0"

:: Uses venv\Scripts\python.exe if there is a venv next to this file
:: (create it with: python -m venv venv, then: venv\Scripts\pip install cosmic-ray==8.7.0),
:: otherwise the python on PATH, which must have cosmic-ray installed.
::
:: Arguments are passed through. Examples:
::   run_mutation.bat --only my_module
::   run_mutation.bat --resume results\2026-01-01_120000
::   run_mutation.bat --stage2 results\2026-01-01_120000 --jobs 3

set PY=python
if exist "venv\Scripts\python.exe" set PY=venv\Scripts\python.exe

%PY% run_mutation.py %*
if errorlevel 1 (
    echo.
    echo ERROR: run_mutation.py exited with an error.
    pause
    exit /b 1
)

echo.
echo Output written to: results\
echo.
pause

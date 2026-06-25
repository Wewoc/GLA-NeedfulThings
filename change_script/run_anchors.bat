@echo off
setlocal enabledelayedexpansion

echo =================================================================
echo   run_anchors.bat -- needfull things
echo =================================================================
echo.

:: Directory of this script
set "SCRIPT_DIR=%~dp0"
set "DELIVERY=%SCRIPT_DIR%anchor_delivery.md"

:: ── Step 1: Delete old anchor_delivery.md ─────────────────────────
if exist "%DELIVERY%" (
    del "%DELIVERY%"
    echo [1/3] Old anchor_delivery.md deleted.
) else (
    echo [1/3] No anchor_delivery.md found -- skipped.
)

:: ── Step 2: Rename newest anchor_delivery_*.md ────────────────────
echo [2/3] Looking for newest anchor_delivery_*.md ...

set "NEWEST_FILE="
set "NEWEST_TIME=0"

for %%F in ("%SCRIPT_DIR%anchor_delivery_*.md") do (
    set "CURR=%%~tF"
    :: %%~tF returns "DD.MM.YYYY HH:MM" -- reformat to YYYYMMDDHHM for comparison
    set "D=%%~tF"
    :: Parse date: DD.MM.YYYY HH:MM
    set "DAY=!D:~0,2!"
    set "MON=!D:~3,2!"
    set "YR=!D:~6,4!"
    set "HR=!D:~11,2!"
    set "MN=!D:~14,2!"
    set "STAMP=!YR!!MON!!DAY!!HR!!MN!"

    if "!STAMP!" gtr "!NEWEST_TIME!" (
        set "NEWEST_TIME=!STAMP!"
        set "NEWEST_FILE=%%F"
    )
)

if "!NEWEST_FILE!"=="" (
    echo.
    echo ERROR: No anchor_delivery_*.md found in %SCRIPT_DIR%.
    echo Copy the file into this directory and try again.
    echo.
    pause
    exit /b 1
)

echo     Found: !NEWEST_FILE!
copy "!NEWEST_FILE!" "%DELIVERY%" >nul
echo     Copied to anchor_delivery.md
echo.

:: ── Step 3: Run apply_anchors.py ──────────────────────────────────
echo [3/3] Running apply_anchors.py ...
echo.
python "%SCRIPT_DIR%apply_anchors.py"
set "APPLY_RESULT=%ERRORLEVEL%"
echo.

if %APPLY_RESULT% neq 0 (
    echo =================================================================
    echo   apply_anchors.py reported errors.
    echo =================================================================
    echo.
    pause
    exit /b %APPLY_RESULT%
)

echo =================================================================
echo   Done.
echo =================================================================
echo.
pause
endlocal

@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   netz2_diagnostics - Diagnostic Batch Run
echo ============================================================
echo.
echo   Runs all run_netz2*.py scripts in this folder in sequence
echo   against a shared, freshly assigned report folder.
echo.

set /p VERSION="Version (e.g. 1658): "

if "%VERSION%"=="" (
    echo.
    echo Error: no version entered. Aborting.
    pause
    exit /b 1
)

set "SCRIPT_DIR=%~dp0"
set "OUTPUT_ROOT=%SCRIPT_DIR%output"

if not exist "%OUTPUT_ROOT%" mkdir "%OUTPUT_ROOT%"

rem ── determine the running number from existing v<VERSION>_NN folders ──────
rem     Trick "1<NUMPART> - 100": avoids set /a misinterpreting numbers with
rem     a leading zero (e.g. "08") as octal - only correct for two-digit NN
rem     (01-99), see format below.
set MAXNUM=0
for /d %%D in ("%OUTPUT_ROOT%\v%VERSION%_*") do (
    set "DIRNAME=%%~nxD"
    set "NUMPART=!DIRNAME:v%VERSION%_=!"
    set /a NUMVAL=1!NUMPART! - 100 2>nul
    if !NUMVAL! gtr !MAXNUM! set MAXNUM=!NUMVAL!
)

set /a NEXTNUM=MAXNUM+1
if !NEXTNUM! lss 10 (
    set "NETZ2_REPORT_ID=v%VERSION%_0!NEXTNUM!"
) else (
    set "NETZ2_REPORT_ID=v%VERSION%_!NEXTNUM!"
)

echo.
echo   Report ID : %NETZ2_REPORT_ID%
echo   Folder    : %OUTPUT_ROOT%\%NETZ2_REPORT_ID%
echo.

mkdir "%OUTPUT_ROOT%\%NETZ2_REPORT_ID%"

rem ── netz2_delta.py: hash comparison of the six Net-2 core modules against ─
rem     the last netz2_diagnostics run. Deliberately NOT picked up by the
rem     run_netz2*.py glob below (filename doesn't start with "run_netz2") -
rem     it's not another diagnostic scenario, it's the pre-check for one.
rem     Own, explicit call before the scenario loop.
echo.
echo ------------------------------------------------------------
echo   Starting netz2_delta.py
echo ------------------------------------------------------------
python "%SCRIPT_DIR%netz2_delta.py"
if errorlevel 1 (
    echo.
    echo   ✗  netz2_delta.py exited with an error - see output above.
)

rem ── run all run_netz2*.py scripts in this folder in sequence ──────────────
set SCRIPT_COUNT=0
for %%F in ("%SCRIPT_DIR%run_netz2*.py") do (
    set /a SCRIPT_COUNT+=1
    echo.
    echo ------------------------------------------------------------
    echo   Starting %%~nxF
    echo ------------------------------------------------------------
    python "%%F"
    if errorlevel 1 (
        echo.
        echo   ✗  %%~nxF exited with an error - see output above.
    )
)

if %SCRIPT_COUNT%==0 (
    echo.
    echo   ✗  No run_netz2*.py script found next to run_netz2_all.bat.
)

echo.
echo ============================================================
echo   Done. Reports under: %OUTPUT_ROOT%\%NETZ2_REPORT_ID%
echo ============================================================
echo.

endlocal
pause

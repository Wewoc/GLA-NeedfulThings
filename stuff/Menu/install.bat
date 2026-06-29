@echo off
chcp 65001 >nul
title install -- needfull things / menu

set "MENU_DIR=%~dp0"
if "%MENU_DIR:~-1%"=="\" set "MENU_DIR=%MENU_DIR:~0,-1%"

echo.
echo install.bat -- needfull things / menu
echo Context menu integration for Windows Explorer
echo.
echo Menu directory: %MENU_DIR%
echo.

:: Python writes the .reg file so batch never touches the percent signs
python "%~dp0write_reg.py" "%MENU_DIR%"
if %errorlevel% neq 0 (
    echo ERROR: write_reg.py failed.
    pause
    exit /b 1
)

echo [+] Merge folder to MD
echo [+] Generate folder tree
echo [+] Count project stats
echo [+] Count chat stats
echo [+] Anonymize JSONs here
echo.
echo Done. Re-open Explorer to see the new entries.
echo Entries appear under "Weitere Optionen anzeigen" (Win11 classic menu).
echo.
pause

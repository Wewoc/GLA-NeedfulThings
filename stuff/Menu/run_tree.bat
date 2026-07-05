@echo off
chcp 65001 >nul
set "MENU_DIR=%~dp0"
if "%MENU_DIR:~-1%"=="\" set "MENU_DIR=%MENU_DIR:~0,-1%"
set "TARGET=%~1"

echo.
echo Generate folder tree -- needfull things
echo Folder: %TARGET%
echo.

tree /f /a "%TARGET%" > "%TARGET%\struktur.md"

echo Done. Output: %TARGET%\struktur.md
echo.
pause

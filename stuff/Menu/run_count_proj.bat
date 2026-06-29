@echo off
chcp 65001 >nul
set "MENU_DIR=%~dp0"
if "%MENU_DIR:~-1%"=="\" set "MENU_DIR=%MENU_DIR:~0,-1%"
set "TARGET=%~1"

echo.
echo Count project stats -- needfull things
echo Folder: %TARGET%
echo.

python "%MENU_DIR%\..\count_project.py" "%TARGET%"

echo.
pause

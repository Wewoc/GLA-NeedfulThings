@echo off
title backup
echo ====================================================
echo   backup_to_onedrive running...
echo ====================================================
echo.

:: Starts the Python script
python backup_to_onedrive.py

echo.
echo ====================================================
echo   Done.
echo ====================================================
echo.
pause
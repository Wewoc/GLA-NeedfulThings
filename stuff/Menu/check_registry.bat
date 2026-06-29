@echo off
chcp 65001 >nul
echo.
echo Checking registry entries...
echo.

reg query "HKCU\Software\Classes\Directory\shell\NeedfulMerge" >nul 2>&1
if %errorlevel%==0 (echo [OK] NeedfulMerge found) else (echo [!!] NeedfulMerge MISSING)

reg query "HKCU\Software\Classes\Directory\shell\NeedfulTree" >nul 2>&1
if %errorlevel%==0 (echo [OK] NeedfulTree found) else (echo [!!] NeedfulTree MISSING)

reg query "HKCU\Software\Classes\Directory\shell\NeedfulCountProj" >nul 2>&1
if %errorlevel%==0 (echo [OK] NeedfulCountProj found) else (echo [!!] NeedfulCountProj MISSING)

reg query "HKCU\Software\Classes\Directory\shell\NeedfulCountChats" >nul 2>&1
if %errorlevel%==0 (echo [OK] NeedfulCountChats found) else (echo [!!] NeedfulCountChats MISSING)

reg query "HKCU\Software\Classes\Directory\shell\NeedfulAnon" >nul 2>&1
if %errorlevel%==0 (echo [OK] NeedfulAnon found) else (echo [!!] NeedfulAnon MISSING)

echo.
echo Full command values:
echo.
reg query "HKCU\Software\Classes\Directory\shell\NeedfulMerge\command"
echo.
pause

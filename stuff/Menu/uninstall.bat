@echo off
chcp 65001 >nul
title uninstall -- needfull things / menu

echo.
echo uninstall.bat -- needfull things / menu
echo Removes context menu entries from Windows Explorer
echo.

reg delete "HKCU\Software\Classes\Directory\shell\NeedfulMerge" /f >nul 2>&1
echo [-] Merge folder to MD

reg delete "HKCU\Software\Classes\Directory\shell\NeedfulTree" /f >nul 2>&1
echo [-] Generate folder tree

reg delete "HKCU\Software\Classes\Directory\shell\NeedfulCountProj" /f >nul 2>&1
echo [-] Count project stats

reg delete "HKCU\Software\Classes\Directory\shell\NeedfulCountChats" /f >nul 2>&1
echo [-] Count chat stats

reg delete "HKCU\Software\Classes\Directory\shell\NeedfulAnon" /f >nul 2>&1
echo [-] Anonymize JSONs here

echo.
echo Done. All needfull things menu entries removed.
echo.
pause

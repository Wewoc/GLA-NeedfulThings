@echo off
setlocal enabledelayedexpansion
title LibreTranslate Setup
echo.
echo  LibreTranslate – Setup
echo  ----------------------
echo.

:: Docker pruefen
docker --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Docker not found.
    echo  Please install Docker Desktop: https://www.docker.com/products/docker-desktop
    echo.
    pause
    exit /b 1
)

echo  Docker found. Pulling LibreTranslate image...
echo  (This may take a few minutes on first run)
echo.
docker pull libretranslate/libretranslate
echo.

:: Anwendungsfall auswaehlen
echo  Select your primary use case:
echo.
echo  [1] DE ^<^> EN only          (fast startup, ~300 MB)
echo  [2] DE ^<^> EN + West Europe  (DE EN FR ES IT PT NL, ~1.5 GB)
echo  [3] All available languages  (~10 GB, slow first start)
echo  [4] Custom                   (enter language codes manually)
echo.
set /p choice=Your choice (1-4): 

if "%choice%"=="1" goto choice1
if "%choice%"=="2" goto choice2
if "%choice%"=="3" goto choice3
if "%choice%"=="4" goto choice4
echo  Invalid choice. Exiting.
pause
exit /b 1

:choice1
set LANGS=de,en
set LABEL=DE + EN
goto run

:choice2
set LANGS=de,en,fr,es,it,pt,nl
set LABEL=DE EN FR ES IT PT NL
goto run

:choice3
set LANGS=
set LABEL=All languages
goto run

:choice4
echo.
echo  Enter language codes separated by commas (e.g. de,en,fr,ja)
echo  Available codes: de en fr es it pt nl pl ru zh ja
echo.
set /p LANGS=Language codes: 
set LABEL=Custom
goto run

:run

echo.
echo  Selected: !LABEL!
echo  Starting LibreTranslate to download language models...
echo  (First run downloads models — this may take several minutes)
echo.

:: Gewaehlte Sprachen speichern fuer start.bat
echo !LANGS!> libretranslate_langs.txt

:: Alten Container entfernen falls vorhanden
docker rm -f localtranslate-libre >nul 2>&1

:: Starten mit oder ohne --load-only
if "!LANGS!"=="" (
    docker run --name localtranslate-libre -p 5000:5000 libretranslate/libretranslate
) else (
    docker run --name localtranslate-libre -p 5000:5000 libretranslate/libretranslate --load-only !LANGS!
)

echo.
echo  Setup complete. LibreTranslate is ready.
echo  Enable it in config.yaml: libretranslate_enabled: true
echo.
pause
@echo off
setlocal enabledelayedexpansion
title LocalTranslate
echo.
echo  LocalTranslate – Starte...
echo.

:: Python pruefen
python --version >nul 2>&1
if errorlevel 1 (
    echo  [FEHLER] Python nicht gefunden.
    echo  Bitte Python installieren: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Docker pruefen
:check_docker
docker --version >nul 2>&1
if errorlevel 1 (
    echo  [WARNUNG] Docker nicht erreichbar – LibreTranslate nicht verfuegbar.
    echo  Bitte Docker Desktop starten.
    echo.
    echo  [R] Erneut versuchen   [S] Ueberspringen
    set /p docker_choice=Auswahl: 
    if /i "!docker_choice!"=="r" goto check_docker
    if /i "!docker_choice!"=="s" goto docker_done
    goto check_docker
)
echo  Docker online.
:docker_done
echo.

:: Ollama pruefen
:check_ollama
curl -s --max-time 3 http://localhost:11434 >nul 2>&1
if errorlevel 1 (
    echo  [WARNUNG] Ollama nicht erreichbar.
    echo  Bitte Ollama Desktop App starten.
    echo.
    echo  [R] Erneut versuchen   [S] Ueberspringen
    set /p ollama_choice=Auswahl: 
    if /i "!ollama_choice!"=="r" goto check_ollama
    if /i "!ollama_choice!"=="s" goto ollama_done
    goto check_ollama
)
echo  Ollama online.
:ollama_done
echo.

:: Dependencies installieren falls noetig
echo  Pruefe Abhaengigkeiten...
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo  Installiere Abhaengigkeiten...
    pip install fastapi uvicorn httpx pyyaml python-dotenv lara-sdk --quiet
)

:: LibreTranslate starten falls aktiviert
findstr /i "libretranslate_enabled: true" config.yaml >nul 2>&1
if not errorlevel 1 (
    echo  LibreTranslate enabled – starting Docker container...
    docker --version >nul 2>&1
    if errorlevel 1 (
        echo  [WARNING] Docker not found – LibreTranslate will not be started.
    ) else (
        set LIBRE_LANGS=
        if exist libretranslate_langs.txt (
            set /p LIBRE_LANGS=<libretranslate_langs.txt
        )
        docker start localtranslate-libre >nul 2>&1
        if errorlevel 1 (
            docker rm -f localtranslate-libre >nul 2>&1
            if "%LIBRE_LANGS%"=="" (
                docker run -d --name localtranslate-libre -p 5000:5000 libretranslate/libretranslate >nul 2>&1
            ) else (
                docker run -d --name localtranslate-libre -p 5000:5000 libretranslate/libretranslate --load-only %LIBRE_LANGS% >nul 2>&1
            )
        )
        echo  LibreTranslate running in background on http://localhost:5000
    )
    echo.
)

:: Starten
echo  Starte Server...
echo.
python app.py

pause

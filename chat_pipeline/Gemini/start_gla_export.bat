@echo off
echo ============================================================
echo Gemini GLA-Exporter — Setup
echo ============================================================
echo.

:: Kill any running Chrome instances
echo [1/3] Closing Chrome...
taskkill /F /IM chrome.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

:: Start Chrome with debug port
echo [2/3] Starting Chrome with debug port...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\ChromeDebug --no-first-run "https://gemini.google.com/app"

echo.
echo Waiting 5 seconds for Chrome to load...
timeout /t 5 /nobreak >nul

:: Start the exporter script
echo [3/3] Starting GLA-Exporter...
echo.
cd /d %~dp0
python gemini_exporter_gla.py

pause

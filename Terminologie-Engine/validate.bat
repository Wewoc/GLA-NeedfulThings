@echo off
title Terminologie-Engine — Validierung
echo.
echo  Terminologie-Engine — Pass 3 Uebersetzungsvalidierung
echo  Modell: aya-expanse:latest
echo.

cd /d "%~dp0"

python filter_terminology.py --dir "..\terminology" --validate --model aya-expanse:latest

echo.
pause
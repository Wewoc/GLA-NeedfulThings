#!/bin/bash
echo ""
echo " LocalTranslate – Starte..."
echo ""

# Python pruefen
if ! command -v python3 &> /dev/null; then
    echo " [FEHLER] Python3 nicht gefunden."
    exit 1
fi

# Dependencies installieren
echo " Pruefe Abhaengigkeiten..."
pip3 show fastapi > /dev/null 2>&1 || pip3 install fastapi uvicorn httpx pyyaml python-dotenv lara-sdk --quiet

# LibreTranslate aktiviert? → Opt-in abfragen
USE_LIBRE=false
if grep -qi "libretranslate_enabled: true" config.yaml; then
    read -p " LibreTranslate (Docker) verwenden? [j/N] " libre_choice
    if [[ "$libre_choice" =~ ^[Jj]$ ]]; then
        USE_LIBRE=true
    else
        echo " LibreTranslate wird uebersprungen."
    fi
    echo ""
fi

# Docker pruefen (nur wenn LibreTranslate gewuenscht)
if [ "$USE_LIBRE" = true ]; then
    check_docker() {
        command -v docker &> /dev/null && docker info > /dev/null 2>&1
    }

    while ! check_docker; do
        echo " [WARNUNG] Docker nicht erreichbar – LibreTranslate nicht verfuegbar."
        echo " Bitte Docker Desktop starten."
        echo " [R] Erneut versuchen   [S] Ueberspringen"
        read -p " Auswahl: " docker_choice
        if [[ "$docker_choice" =~ ^[Ss]$ ]]; then
            USE_LIBRE=false
            break
        fi
    done
    if [ "$USE_LIBRE" = true ] && check_docker; then
        echo " Docker online."
    fi
    echo ""
fi

# Ollama pruefen
check_ollama() {
    curl -s --max-time 3 http://localhost:11434 > /dev/null 2>&1
}

while ! check_ollama; do
    echo " [WARNUNG] Ollama nicht erreichbar. Bitte Ollama starten."
    echo " [R] Erneut versuchen   [S] Ueberspringen"
    read -p " Auswahl: " ollama_choice
    if [[ "$ollama_choice" =~ ^[Ss]$ ]]; then
        break
    fi
done
if check_ollama; then
    echo " Ollama online."
fi
echo ""

# LibreTranslate starten falls aktiviert und gewuenscht
if [ "$USE_LIBRE" = true ]; then
    echo " LibreTranslate enabled – starting Docker container..."
    if ! command -v docker &> /dev/null; then
        echo " [WARNING] Docker not found – LibreTranslate will not be started."
    else
        LIBRE_LANGS=""
        if [ -f libretranslate_langs.txt ]; then
            LIBRE_LANGS=$(cat libretranslate_langs.txt | tr -d '[:space:]')
        fi
        docker start localtranslate-libre > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            docker rm -f localtranslate-libre > /dev/null 2>&1
            if [ -z "$LIBRE_LANGS" ]; then
                docker run -d --name localtranslate-libre -p 5000:5000 libretranslate/libretranslate > /dev/null 2>&1
            else
                docker run -d --name localtranslate-libre -p 5000:5000 libretranslate/libretranslate --load-only "$LIBRE_LANGS" > /dev/null 2>&1
            fi
        fi
        echo " LibreTranslate running in background on http://localhost:5000"
    fi
    echo ""
fi

echo " Starte Server..."
echo ""
python3 app.py
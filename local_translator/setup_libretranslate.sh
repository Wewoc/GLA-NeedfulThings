#!/bin/bash
echo ""
echo " LibreTranslate – Setup"
echo " ----------------------"
echo ""

# Docker pruefen
if ! command -v docker &> /dev/null; then
    echo " [ERROR] Docker not found."
    echo " Please install Docker: https://docs.docker.com/get-docker/"
    echo ""
    exit 1
fi

echo " Docker found. Pulling LibreTranslate image..."
echo " (This may take a few minutes on first run)"
echo ""
docker pull libretranslate/libretranslate
echo ""

# Anwendungsfall auswaehlen
echo " Select your primary use case:"
echo ""
echo "  [1] DE <> EN only          (fast startup, ~300 MB)"
echo "  [2] DE <> EN + West Europe  (DE EN FR ES IT PT NL, ~1.5 GB)"
echo "  [3] All available languages  (~10 GB, slow first start)"
echo "  [4] Custom                   (enter language codes manually)"
echo ""
read -p " Your choice (1-4): " choice

case "$choice" in
    1)
        LANGS="de,en"
        LABEL="DE + EN"
        ;;
    2)
        LANGS="de,en,fr,es,it,pt,nl"
        LABEL="DE EN FR ES IT PT NL"
        ;;
    3)
        LANGS=""
        LABEL="All languages"
        ;;
    4)
        echo ""
        echo " Enter language codes separated by commas (e.g. de,en,fr,ja)"
        echo " Available codes: de en fr es it pt nl pl ru zh ja"
        echo ""
        read -p " Language codes: " LANGS
        LABEL="Custom"
        ;;
    *)
        echo " Invalid choice. Exiting."
        exit 1
        ;;
esac

echo ""
echo " Selected: $LABEL"
echo " Starting LibreTranslate to download language models..."
echo " (First run downloads models — this may take several minutes)"
echo ""

# Sprachen speichern fuer start.sh
echo "$LANGS" > libretranslate_langs.txt

# Alten Container entfernen
docker rm -f localtranslate-libre > /dev/null 2>&1

# Starten
if [ -z "$LANGS" ]; then
    docker run --name localtranslate-libre -p 5000:5000 libretranslate/libretranslate
else
    docker run --name localtranslate-libre -p 5000:5000 libretranslate/libretranslate --load-only "$LANGS"
fi

echo ""
echo " Setup complete. LibreTranslate is ready."
echo " Enable it in config.yaml: libretranslate_enabled: true"
echo ""
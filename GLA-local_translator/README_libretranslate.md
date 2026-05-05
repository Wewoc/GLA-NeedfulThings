# LibreTranslate — Local Setup

LibreTranslate is a free, open-source machine translation API that runs entirely
on your machine. No cloud, no API key required, no data leaving the house.

This guide covers setup for use with LocalTranslate.

---

## Requirements

- **Windows (recommended):** Docker Desktop
- **Linux/Mac:** Python 3.8+ or Docker

---

## Option A — Docker (recommended on Windows)

The simplest and most reliable way on Windows.

### 1. Install Docker Desktop
Download and install from: https://www.docker.com/products/docker-desktop

### 2. Pull and run LibreTranslate

Load specific languages only (faster startup, less disk space):
```bat
docker run -ti --rm -p 5000:5000 libretranslate/libretranslate --load-only de,en,fr,es,it
```

Or load all available languages (~10 GB, takes a while on first run):
```bat
docker run -ti --rm -p 5000:5000 libretranslate/libretranslate
```

### 3. Keep it running in the background (optional)
```bat
docker run -d --restart unless-stopped -p 5000:5000 libretranslate/libretranslate --load-only de,en,fr,es,it
```
`--restart unless-stopped` auto-starts the container on system boot.

### 4. Verify
Open http://localhost:5000 in your browser — you should see the LibreTranslate UI.

---

## Option B — pip (Linux/Mac, or Windows with Python 3.8–3.10)

```bash
pip install libretranslate
libretranslate --load-only de,en,fr,es,it
```

> **Note:** Native Windows installation is known to be difficult on Python 3.11+.
> Use Docker on Windows unless you specifically need pip.

---

## Language Codes

| Language | Code |
|----------|------|
| German | `de` |
| English | `en` |
| French | `fr` |
| Spanish | `es` |
| Italian | `it` |
| Portuguese | `pt` |
| Dutch | `nl` |
| Polish | `pl` |
| Russian | `ru` |
| Chinese | `zh` |
| Japanese | `ja` |

Only install languages you actually need — each model is ~100–300 MB.

---

## Configure LocalTranslate

Once LibreTranslate is running, enable it in `config.yaml`:

```yaml
libretranslate_url: "http://localhost:5000"
libretranslate_api_key: ""       # leave empty for local instance
libretranslate_enabled: true
```

The **★ LibreTranslate** button in the footer will show:
- `★ LibreTranslate` — online and language pair available
- `★ LibreTranslate (offline)` — service not running
- `★ LibreTranslate (DE not installed)` — language model missing

---

## Setup Script

Run `setup_libretranslate.bat` (Windows) or `bash setup_libretranslate.sh` (Linux/Mac) once to download language models and create the Docker container.

The script will:
1. Check for Docker
2. Pull the LibreTranslate image
3. Ask which languages to install
4. Download models and start the container

After setup, use `translator.bat` to start everything — it will automatically start the LibreTranslate container if `libretranslate_enabled: true` is set in `config.yaml`.

> **Important:** Never delete the `localtranslate-libre` container in Docker Desktop — only stop it. Deleting requires running `setup_libretranslate.bat` again to re-download all models.

---

## Notes

- First run downloads language models — this can take several minutes
- Subsequent starts are fast (models are cached by Docker)
- LibreTranslate quality is lower than DeepL or Lara for most language pairs
- Best suited as a fallback or for languages not covered by other engines
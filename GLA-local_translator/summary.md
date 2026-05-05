## File: .\.env.example

# LocalTranslate – Credentials Template
# Kopieren nach .env und Werte eintragen

DEEPL_API_KEY=your-deepl-key-here

LARA_ACCESS_KEY_ID=your-lara-key-id-here
LARA_ACCESS_KEY_SECRET=your-lara-secret-here

---

## File: .\app.py

"""
LocalTranslate – FastAPI Backend
"""

import json
import os
import re
import webbrowser
from datetime import datetime
from pathlib import Path
from threading import Thread

import httpx
import uvicorn
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Config laden ──────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.yaml"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

load_dotenv(Path(__file__).parent / ".env")

cfg = load_config()

OLLAMA_URL   = cfg.get("ollama_url", "http://localhost:11434")
OLLAMA_MODEL = cfg.get("ollama_model", "mistral")
_active_model = OLLAMA_MODEL   # mutable runtime model
DEEPL_KEY    = os.getenv("DEEPL_API_KEY", "")
DEEPL_FREE   = cfg.get("deepl_free_tier", True)
LIBRE_URL    = cfg.get("libretranslate_url", "http://localhost:5000")
LIBRE_KEY    = cfg.get("libretranslate_api_key", "")
LIBRE_ON     = cfg.get("libretranslate_enabled", False)
MYMEMORY_ON  = cfg.get("mymemory_enabled", True)
MYMEMORY_MAIL= cfg.get("mymemory_email", "")
LARA_ID          = os.getenv("LARA_ACCESS_KEY_ID", "")
LARA_SECRET      = os.getenv("LARA_ACCESS_KEY_SECRET", "")
LARA_ON          = cfg.get("lara_enabled", False)
LARA_DAILY_LIMIT = cfg.get("lara_daily_limit", 5000)
EXPORT_DIR       = Path(cfg.get("export_dir", "./exports"))
FILENAME_PFX = cfg.get("filename_prefix", "translation")
LANGUAGES    = cfg.get("languages", {"Deutsch": "DE", "Englisch": "EN"})
DEFAULT_SRC  = cfg.get("default_source_lang", "DE")
DEFAULT_TGT  = cfg.get("default_target_lang", "EN")
DEBOUNCE_SEC     = cfg.get("debounce_seconds", 1.5)
OLLAMA_CHUNK_SIZE = cfg.get("ollama_chunk_size", 6000)
DEEPL_CHUNK_SIZE  = 4900
MYMEMORY_CHUNK_SIZE = 480

EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# ── FastAPI Setup ──────────────────────────────────────────────────────────────

app = FastAPI(title="LocalTranslate")

app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

INDEX_PATH = Path(__file__).parent / "index.html"

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(INDEX_PATH.read_text(encoding="utf-8"))

# ── Modelle ───────────────────────────────────────────────────────────────────

class TranslateRequest(BaseModel):
    text: str
    source_lang: str
    target_lang: str
    engine: str = "ollama"   # "ollama" | "deepl"

class ExportRequest(BaseModel):
    source_text: str
    target_text: str
    source_lang: str
    target_lang: str

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

LANG_NAMES = {v: k for k, v in LANGUAGES.items()}

def lang_name(code: str) -> str:
    return LANG_NAMES.get(code.upper(), code)

def split_chunks(text: str, limit: int) -> list[str]:
    """Text in Chunks aufteilen — Absätze zusammenfassen bis Limit, dann neuer Chunk."""
    if len(text) <= limit:
        return [text]

    # Kleine Einheiten sammeln (Absatz → Zeile → Satz → hart)
    units = []
    for para in text.split("\n\n"):
        if not para.strip():
            continue
        if len(para) <= limit:
            units.append(para)
        else:
            for line in para.split("\n"):
                if not line.strip():
                    continue
                if len(line) <= limit:
                    units.append(line)
                else:
                    for sentence in line.split(". "):
                        if not sentence.strip():
                            continue
                        if len(sentence) <= limit:
                            units.append(sentence)
                        else:
                            for i in range(0, len(sentence), limit):
                                units.append(sentence[i:i+limit])

    # Einheiten zu Chunks zusammenfassen bis Limit erreicht
    chunks = []
    current = ""
    for unit in units:
        separator = "\n\n" if current else ""
        if len(current) + len(separator) + len(unit) <= limit:
            current += separator + unit
        else:
            if current:
                chunks.append(current)
            current = unit
    if current:
        chunks.append(current)

    return chunks

async def translate_ollama(text: str, source_lang: str, target_lang: str, context: str = "") -> str:
    src = lang_name(source_lang)
    tgt = lang_name(target_lang)
    context_hint = (
        f"For continuity, the previous passage ended with:\n{context}\n\n"
        if context else ""
    )
    prompt = (
        f"{context_hint}"
        f"Translate the following text from {src} to {tgt}. "
        f"Output only the translation, no explanations, no extra text.\n\n{text}"
    )
    payload = {
        "model": _active_model,
        "prompt": prompt,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=180.0)) as client:
        try:
            r = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
            r.raise_for_status()
            return r.json().get("response", "").strip()
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Ollama nicht erreichbar. Läuft 'ollama serve'?")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ollama Fehler: {e}")

async def translate_libretranslate(text: str, source_lang: str, target_lang: str) -> str:
    if not LIBRE_ON:
        raise HTTPException(status_code=400, detail="LibreTranslate nicht aktiviert.")
    payload = {
        "q": text,
        "source": source_lang.lower(),
        "target": target_lang.lower(),
        "format": "text",
    }
    if LIBRE_KEY:
        payload["api_key"] = LIBRE_KEY
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(f"{LIBRE_URL}/translate", json=payload)
            r.raise_for_status()
            return r.json().get("translatedText", "").strip()
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="LibreTranslate nicht erreichbar.")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LibreTranslate Fehler: {e}")

async def translate_mymemory(text: str, source_lang: str, target_lang: str) -> str:
    if not MYMEMORY_ON:
        raise HTTPException(status_code=400, detail="MyMemory nicht aktiviert.")
    params = {
        "q": text,
        "langpair": f"{source_lang.upper()}|{target_lang.upper()}",
    }
    if MYMEMORY_MAIL:
        params["de"] = MYMEMORY_MAIL
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.get("https://api.mymemory.translated.net/get", params=params)
            r.raise_for_status()
            data = r.json()
            if data.get("responseStatus") != 200:
                raise HTTPException(status_code=502, detail=f"MyMemory: {data.get('responseDetails', 'Fehler')}")
            return data["responseData"]["translatedText"].strip()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"MyMemory Fehler: {e}")

LARA_USAGE_FILE = Path(__file__).parent / "lara_usage.json"

def get_lara_usage() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        data = json.loads(LARA_USAGE_FILE.read_text(encoding="utf-8"))
        if data.get("date") != today:
            return {"date": today, "chars": 0}
        return data
    except Exception:
        return {"date": today, "chars": 0}

def add_lara_usage(chars: int):
    usage = get_lara_usage()
    usage["chars"] += chars
    LARA_USAGE_FILE.write_text(json.dumps(usage), encoding="utf-8")

async def translate_lara(text: str, source_lang: str, target_lang: str) -> str:
    if not LARA_ID or not LARA_SECRET:
        raise HTTPException(status_code=400, detail="Lara Credentials fehlen in .env.")
    try:
        from lara_sdk import Translator, Credentials
        import asyncio
        credentials = Credentials(access_key_id=LARA_ID, access_key_secret=LARA_SECRET)
        lara = Translator(credentials)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: lara.translate(text, source=source_lang.lower(), target=target_lang.lower())
        )
        translation = result.translation.strip()
        add_lara_usage(len(text))
        return translation
    except ImportError:
        raise HTTPException(status_code=500, detail="lara-sdk nicht installiert. Bitte 'pip install lara-sdk' ausführen.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lara Fehler: {e}")

async def translate_deepl(text: str, source_lang: str, target_lang: str) -> str:
    if not DEEPL_KEY:
        raise HTTPException(status_code=400, detail="Kein DeepL API Key in config.yaml eingetragen.")
    base = "https://api-free.deepl.com" if DEEPL_FREE else "https://api.deepl.com"
    url = f"{base}/v2/translate"
    params = {
        "auth_key": DEEPL_KEY,
        "text": text,
        "source_lang": source_lang.upper(),
        "target_lang": target_lang.upper(),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(url, data=params)
            r.raise_for_status()
            return r.json()["translations"][0]["text"]
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"DeepL Fehler: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"DeepL Fehler: {e}")

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/lara/usage")
async def lara_usage():
    usage = get_lara_usage()
    return {
        "chars_today": usage["chars"],
        "limit": LARA_DAILY_LIMIT,
        "remaining": max(0, LARA_DAILY_LIMIT - usage["chars"]),
    }

@app.get("/libretranslate/status")
async def libretranslate_status(source: str = "", target: str = ""):
    if not LIBRE_ON:
        return {"online": False, "pair_available": False, "reason": "disabled"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{LIBRE_URL}/languages")
            r.raise_for_status()
            codes = [l["code"].lower() for l in r.json()]
            src = source.lower()
            tgt = target.lower()
            src_ok = src in codes
            tgt_ok = tgt in codes
            pair_ok = src_ok and tgt_ok
            reason = ""
            if not pair_ok:
                missing = []
                if not src_ok: missing.append(src.upper())
                if not tgt_ok: missing.append(tgt.upper())
                reason = f"{' & '.join(missing)} not installed"
            return {"online": True, "pair_available": pair_ok, "reason": reason}
        except Exception:
            return {"online": False, "pair_available": False, "reason": "offline"}

@app.post("/libretranslate/stop")
async def libretranslate_stop():
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "stop", "localtranslate-libre"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return {"stopped": True}
        else:
            raise HTTPException(status_code=500, detail=f"Docker error: {result.stderr.strip()}")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Docker not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stop failed: {e}")

@app.get("/config")
async def get_config():
    return {
        "languages": LANGUAGES,
        "default_source_lang": DEFAULT_SRC,
        "default_target_lang": DEFAULT_TGT,
        "debounce_seconds": DEBOUNCE_SEC,
        "deepl_available": bool(DEEPL_KEY),
        "libretranslate_available": LIBRE_ON,
        "mymemory_available": MYMEMORY_ON,
        "lara_available": LARA_ON and bool(LARA_ID) and bool(LARA_SECRET),
        "ollama_model": _active_model,
    }

class ChunkRequest(BaseModel):
    text: str
    source_lang: str
    target_lang: str
    engine: str = "ollama"
    context: str = ""

class PrepareRequest(BaseModel):
    text: str
    engine: str = "ollama"

@app.post("/translate/chunks/prepare")
async def prepare_chunks(req: PrepareRequest):
    if req.engine == "mymemory":
        limit = MYMEMORY_CHUNK_SIZE
    elif req.engine == "deepl":
        limit = DEEPL_CHUNK_SIZE
    else:
        limit = OLLAMA_CHUNK_SIZE
    chunks = split_chunks(req.text, limit)
    return {"chunks": chunks, "total": len(chunks)}

@app.post("/translate/chunk")
async def translate_chunk(req: ChunkRequest):
    if not req.text.strip():
        return {"translation": ""}
    if req.engine == "deepl":
        result = await translate_deepl(req.text, req.source_lang, req.target_lang)
    elif req.engine == "libretranslate":
        result = await translate_libretranslate(req.text, req.source_lang, req.target_lang)
    elif req.engine == "mymemory":
        result = await translate_mymemory(req.text, req.source_lang, req.target_lang)
    elif req.engine == "lara":
        result = await translate_lara(req.text, req.source_lang, req.target_lang)
    else:
        result = await translate_ollama(req.text, req.source_lang, req.target_lang, req.context)
    return {"translation": result}

@app.post("/translate")
async def translate(req: TranslateRequest):
    if not req.text.strip():
        return {"translation": ""}
    if req.engine == "deepl":
        result = await translate_deepl(req.text, req.source_lang, req.target_lang)
    elif req.engine == "libretranslate":
        result = await translate_libretranslate(req.text, req.source_lang, req.target_lang)
    elif req.engine == "mymemory":
        result = await translate_mymemory(req.text, req.source_lang, req.target_lang)
    elif req.engine == "lara":
        result = await translate_lara(req.text, req.source_lang, req.target_lang)
    else:
        result = await translate_ollama(req.text, req.source_lang, req.target_lang)
    return {"translation": result}

@app.get("/ollama/status")
async def ollama_status():
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            current_available = OLLAMA_MODEL in models or any(
                m.startswith(OLLAMA_MODEL.split(":")[0]) for m in models
            )
            return {"online": True, "models": models, "current_model_available": current_available}
        except Exception:
            return {"online": False, "models": [], "current_model_available": False}


class SetModelRequest(BaseModel):
    model: str

@app.post("/ollama/set_model")
async def set_model(req: SetModelRequest):
    global _active_model
    _active_model = req.model
    return {"model": _active_model}

@app.post("/export")
async def export_md(req: ExportRequest):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    src_file = EXPORT_DIR / f"{FILENAME_PFX}_{req.source_lang.lower()}_{ts}.md"
    tgt_file = EXPORT_DIR / f"{FILENAME_PFX}_{req.target_lang.lower()}_{ts}.md"

    src_content = f"# {lang_name(req.source_lang)}\n\n{req.source_text}\n"
    tgt_content = f"# {lang_name(req.target_lang)}\n\n{req.target_text}\n"

    src_file.write_text(src_content, encoding="utf-8")
    tgt_file.write_text(tgt_content, encoding="utf-8")

    return {
        "source_file": str(src_file),
        "target_file": str(tgt_file),
        "export_dir": str(EXPORT_DIR.resolve()),
    }

@app.get("/export/open")
async def export_open():
    import subprocess, sys
    path = str(EXPORT_DIR.resolve())
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return {"opened": True, "path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not open folder: {e}")

# ── Start ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = cfg.get("host", "127.0.0.1")
    port = cfg.get("port", 8000)
    auto_open = cfg.get("auto_open_browser", True)

    if auto_open:
        def _open_when_ready():
            import time, urllib.request
            for _ in range(20):
                try:
                    urllib.request.urlopen(f"http://{host}:{port}/config", timeout=1)
                    webbrowser.open(f"http://{host}:{port}")
                    return
                except Exception:
                    time.sleep(0.5)
        Thread(target=_open_when_ready, daemon=True).start()

    print(f"\n  LocalTranslate läuft auf http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


---

## File: .\config.yaml

# ─────────────────────────────────────────
#  LocalTranslate – Konfiguration
# ─────────────────────────────────────────

# Ollama
ollama_url: "http://localhost:11434"
ollama_model: "dolphin3:latest"          # z.B. mistral, llama3.1, phi3, gemma2

# DeepL (optional – API Key in .env eintragen)
deepl_free_tier: true            # true = Free API (api-free.deepl.com)
                                 # false = Pro API (api.deepl.com)

# LibreTranslate (self-hosted oder libretranslate.com)
libretranslate_url: "http://localhost:5000"
libretranslate_api_key: ""       # leer = kein Key (self-hosted ohne Auth)
libretranslate_enabled: false

# Chunking
ollama_chunk_size: 6000          # chars per chunk for Ollama — DeepL: 4900, MyMemory: 500 (fixed)

# MyMemory
mymemory_enabled: true
mymemory_email: ""               # optional: higher daily limit

# Lara Translate (https://laratranslate.com – Credentials in .env eintragen)
lara_enabled: true
lara_daily_limit: 5000           # Zeichen pro Tag (Free Tier = 5000)

# Übersetzungs-Einstellungen
default_source_lang: "DE"
default_target_lang: "EN"
debounce_seconds: 1.5            # Sekunden Tippstop bevor Übersetzung startet
ollama_chunk_size: 6000          # Zeichen pro Chunk für Ollama (0 = kein Chunking)

# Unterstützte Sprachen (Anzeigename: API-Code)
languages:
  Deutsch: "DE"
  Englisch: "EN"
  Französisch: "FR"
  Spanisch: "ES"
  Italienisch: "IT"
  Portugiesisch: "PT"
  Niederländisch: "NL"
  Polnisch: "PL"
  Russisch: "RU"
  Chinesisch: "ZH"
  Japanisch: "JA"

# Export
export_dir: "./exports"          # Ordner für MD-Exporte (wird auto-erstellt)
filename_prefix: "translation"   # Dateiname-Präfix: translation_source.md / translation_target.md

# Server
host: "127.0.0.1"
port: 8000
auto_open_browser: true          # Browser automatisch öffnen beim Start

---

## File: .\index.html

<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GLA - LocalTranslate</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css">
</head>
<body>

<header>
  <div class="logo">
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
      <!-- Horn -->
      <polygon points="14,1 16,9 12,9" fill="#e879f9" opacity="0.9"/>
      <line x1="14" y1="1" x2="14" y2="9" stroke="#f0abfc" stroke-width="0.5"/>
      <!-- Head -->
      <ellipse cx="14" cy="12" rx="5.5" ry="4.5" fill="#e2c9f5"/>
      <!-- Muzzle -->
      <ellipse cx="17" cy="14" rx="2.5" ry="2" fill="#f3e0ff"/>
      <!-- Eye -->
      <circle cx="12.5" cy="11" r="1" fill="#4c1d95"/>
      <circle cx="12.8" cy="10.7" r="0.3" fill="white"/>
      <!-- Ear -->
      <polygon points="10,8 9,5 12,7.5" fill="#e2c9f5"/>
      <polygon points="10.2,7.8 9.5,6 11.5,7.5" fill="#e879f9" opacity="0.6"/>
      <!-- Mane flowing -->
      <path d="M9 10 Q5 13 6 18 Q7 22 10 24" stroke="#a855f7" stroke-width="2.5" fill="none" stroke-linecap="round" opacity="0.8"/>
      <path d="M9 11 Q4 15 5.5 20 Q7 23 11 25" stroke="#818cf8" stroke-width="1.5" fill="none" stroke-linecap="round" opacity="0.6"/>
      <path d="M10 9.5 Q7 12 8 17 Q9 21 12 23" stroke="#c084fc" stroke-width="1.5" fill="none" stroke-linecap="round" opacity="0.5"/>
      <!-- Stars in mane -->
      <circle cx="6" cy="16" r="0.8" fill="white" opacity="0.9"/>
      <circle cx="7" cy="20" r="0.5" fill="white" opacity="0.7"/>
      <circle cx="5" cy="18" r="0.4" fill="#e879f9" opacity="0.9"/>
    </svg>
    GLA - Local<span>Translate</span>
  </div>

  <div class="controls">
    <div class="lang-row">
      <span class="lang-label">From</span>
      <select id="srcLang"></select>
    </div>
    <button class="swap-btn" onclick="swapLangs()" title="Swap languages">⇄</button>
    <div class="lang-row">
      <span class="lang-label">To</span>
      <select id="tgtLang"></select>
    </div>

    <div class="sep"></div>

    <div class="lang-row">
      <span class="mode-label">Mode</span>
      <select id="modeSelect">
        <option value="debounce">Automatic (Pause)</option>
        <option value="sentence">Sentence (Enter)</option>
        <option value="manual">Manual (Button)</option>
      </select>
    </div>
  </div>
</header>

<div class="statusbar">
  <span><span class="dot" id="ollamaDot"></span><span id="ollamaStatus">Ollama …</span></span>
  <select id="modelSelect" style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:6px;padding:2px 8px;cursor:pointer;" onchange="setModel(this.value)">
    <option value="">Modell ...</option>
  </select>
  <span id="deeplStatus"></span>
  <span id="libreStatus" style="display:none;">
    <span class="dot" id="libreDot"></span>
    <span id="libreStatusText">LibreTranslate</span>
    <button onclick="stopLibre()" style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;background:none;border:1px solid var(--border);color:var(--warn);border-radius:4px;padding:1px 7px;cursor:pointer;margin-left:4px;" title="Stop LibreTranslate container">■ Stop</button>
  </span>
  <a href="https://github.com/Wewoc/Garmin_Local_Archive" target="_blank" id="glaLink" style="margin-left:auto;color:var(--muted);text-decoration:none;font-size:0.72rem;letter-spacing:0.05em;transition:color 0.15s;" onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color='var(--muted)'">⬡ Garmin-Local-Archive</a>
</div>

<main>
  <div class="pane">
    <div class="pane-header">
      <span class="pane-title">Input</span>
      <span class="char-count" id="srcCount">0 chars</span>
    </div>
    <textarea id="srcText" placeholder="Enter text here …"></textarea>
  </div>

  <div class="pane">
    <div class="pane-header">
      <span class="pane-title">Translation</span>
      <span id="engineBadge" style="font-size:0.68rem;color:var(--muted);font-family:'JetBrains Mono',monospace;margin-left:6px;"></span>
      <span class="char-count" id="tgtCount">0 chars</span>
    </div>
    <div class="output-area" id="tgtOutput">
      <span class="placeholder-text">Translation appears here …</span>
    </div>
  </div>
</main>

<footer>
  <button class="btn btn-clear" onclick="clearAll()">✕ Clear</button>
  <button class="btn" id="translateBtn" onclick="translateNow()">▶ Translate</button>
  <button class="btn btn-deepl"    id="deeplBtn"    onclick="deeplFinal()"    disabled title="Finalen Text über DeepL übersetzen">★ DeepL</button>
  <button class="btn btn-libre"    id="libreBtn"    onclick="libreFinal()"    disabled title="Finalen Text über LibreTranslate übersetzen">★ LibreTranslate</button>
  <button class="btn btn-mymemory" id="mymemoryBtn" onclick="mymemoryFinal()" disabled title="Finalen Text über MyMemory übersetzen">★ MyMemory - max. 500 characters</button>
  <button class="btn btn-lara"     id="laraBtn"     onclick="laraFinal()"     disabled title="Finalen Text über Lara übersetzen">★ Lara</button>
  <div class="spacer"></div>
  <button class="btn" onclick="copyTranslation()" title="Übersetzung in Zwischenablage kopieren">⎘ Copy</button>
  <button class="btn btn-accent" onclick="exportMD()">↓ Export as .md</button>
  <button class="btn" onclick="openExportDir()" title="Open exports folder">⬡ Open Folder</button>
</footer>

<div class="toast" id="toast"></div>

<script src="/static/app.js"></script>
</body>
</html>

---

## File: .\lara_usage.json

{"date": "2026-05-03", "chars": 698}

---

## File: .\README_libretranslate.md

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

---

## File: .\README_translator.md

# GLA - LocalTranslate

Local translation tool — part of the [Garmin Local Archive](https://github.com/Wewoc/Garmin_Local_Archive) ecosystem.
Ollama as primary engine, optional Final-Pass via DeepL, LibreTranslate, MyMemory or Lara Translate.
Two-column UI in the browser, synchronized scrolling, MD export of both texts.
Long texts are split into chunks automatically — progress shown live during translation.

---

## Prerequisites

- **Python 3.9+**
- **Ollama Desktop App** running locally
  - Recommended models: `mistral`, `llama3.1`, `phi3`, `gemma2`
  - Pull a model: `ollama pull mistral`
- **Docker Desktop** (only required for LibreTranslate)
- Optional Final-Pass engines — see configuration below

---

## Setup

1. Copy `.env.example` → `.env` and fill in your credentials
2. Adjust `config.yaml` (model, languages, engines)
3. Start Ollama Desktop App
4. Double-click `translator.bat` (Windows) or run `bash translator.sh` (Linux/Mac)
5. Browser opens automatically at `http://127.0.0.1:8000`

For LibreTranslate setup, see `README_libretranslate.md`.

---

## Startup — `translator.bat`

The start script handles everything in order:

1. Checks Python and installs dependencies if needed
2. Checks if Docker is available
3. Checks if Ollama is reachable — prompts to retry or skip if not
4. Starts LibreTranslate Docker container (if `libretranslate_enabled: true`)
5. Starts the LocalTranslate server

---

## Credentials — `.env`

Sensitive API keys are stored in `.env`, not in `config.yaml`.

```env
DEEPL_API_KEY=

LARA_ACCESS_KEY_ID=
LARA_ACCESS_KEY_SECRET=
```

Never commit `.env` to Git — it is listed in `.gitignore`.

---

## Model Selection

The active Ollama model can be changed on the fly via the dropdown in the status bar.
Available models are loaded automatically from the local Ollama instance.
The default model is set in `config.yaml` — the dropdown overrides it at runtime without restart.

---

## Translation Modes

| Mode | Description |
|------|-------------|
| **Automatic (Pause)** | Translates after X seconds of typing stop (configurable via `debounce_seconds`) |
| **Sentencewise (Enter)** | Translates on every Enter press |
| **Manual (Button)** | Only on button press |

---

## Final Pass Engines

Four optional Final-Pass buttons appear in the footer when an engine is configured and enabled.

Recommended workflow:
- During editing → Ollama (local, no cost)
- Final text → one Final-Pass button (one-time quality pass)

| Engine | Signup | Key required | Notes |
|--------|--------|--------------|-------|
| **★ DeepL** | Yes + credit card | Yes (in `.env`) | Best quality for European languages |
| **★ LibreTranslate** | No | Optional | Self-hosted via Docker, see `README_libretranslate.md` |
| **★ MyMemory** | No | No | Works out of the box. Texts over 500 chars are chunked automatically. |
| **★ Lara** | Yes, no credit card | Yes (in `.env`) | 5.000 chars/day free, daily counter shown in button |

Configure engines in `config.yaml`:

```yaml
# DeepL
deepl_free_tier: true            # true = Free API, false = Pro API

# LibreTranslate
libretranslate_url: "http://localhost:5000"
libretranslate_api_key: ""
libretranslate_enabled: false

# MyMemory
mymemory_enabled: true
mymemory_email: ""               # optional: higher daily limit

# Lara Translate
lara_enabled: false
lara_daily_limit: 5000           # local daily counter limit
```

Lara credentials go into `.env`:
```env
LARA_ACCESS_KEY_ID=your-key-id
LARA_ACCESS_KEY_SECRET=your-secret
```
Get credentials at: `app.laratranslate.com/account/credentials`

---

## Lara Daily Counter

The Lara button shows remaining characters for today: `★ Lara (4.200 / 5.000)`.
Usage is tracked locally in `lara_usage.json` and resets at midnight.
The button disables automatically when the daily limit is reached.

---

## LibreTranslate Status

The LibreTranslate button updates dynamically based on the selected language pair:
- `★ LibreTranslate` — online, language pair available
- `★ LibreTranslate (offline)` — service not running
- `★ LibreTranslate (DE not installed)` — language model missing

Use the **■ Stop** button in the status bar to stop the Docker container from within the UI.

---

## Export

**↓ Als .md exportieren** saves two files in the `exports/` folder:
- `translation_de_TIMESTAMP.md` — Source text
- `translation_en_TIMESTAMP.md` — Translation

---

## Dependencies (automatically installed)

```
fastapi
uvicorn
httpx
pyyaml
python-dotenv
lara-sdk
```

---

## Engine Quality — Benchmark Notes

The engines in LocalTranslate are not equivalent. They differ fundamentally in how they work,
not just in price or availability.

**LLMs** (Claude, Ollama models) have learned language as a whole — including style, rhythm,
context, and pragmatics. They translate with an understanding of what a sentence means and how
it should read.

**LibreTranslate** is based on Argos Translate, a small neural MT model trained specifically for
translation. It processes text segment by segment without holding the broader context. This works
well for standardised content — UI strings, forms, short technical phrases — but breaks down on
prose with deliberate style and tone.

---

### Results — DE → EN, literary-technical prose (8 engines tested)

| Rank | Engine | Score | Notes |
|------|--------|-------|-------|
| 1 | Claude.ai  | 96 / 100 | Publication-ready. Preserves rhythm and tone. |
| 2 | Ollama — Dolphin 3 | 88 / 100 | Best local result. Closest to Claude in feel. |
| 3 | Ollama — Mistral Nemo | 85 / 100 | Clean and accurate. Slightly more formal than the original. |
| 4 | Ollama — Mistral latest | 83 / 100 | Solid. Occasional quote formatting inconsistency. |
| 5 | Ollama — qwen2.5-coder:14b-instruct-q8_0 | 81 / 100 | Precise on technical terms. Narrative flow is flatter. |
| 6 | Ollama — deepseek-r1:14b  | 80 / 100 | Content intact. Sentence rhythm partly lost. |
| 7 | Ollama — Llama 3.2 | 68 / 100 | Meta-comments in output, one paragraph detached. Needs cleanup. |
| 8 | LibreTranslate | 48 / 100 | Word-level errors, broken gender references, rhythm gone. |

Test text: a German essay with short declarative sentences and deliberate pauses.
Results will differ for other text types — LibreTranslate performs better on short, standardised content.

---

### Recommendations by use case

**Literary or editorial prose** — Use Claude as primary engine. No local model currently matches it
for texts where style matters. Dolphin 3 or Mistral Nemo are the best offline fallbacks, but expect
to do a light editing pass.

**Technical documentation, config comments, UI strings** — Any Ollama model works well here.
LibreTranslate is acceptable if the text is short and repetitive.

**LibreTranslate** — Useful as an offline fallback for simple content, or to check whether a passage
is structurally correct before a full pass. Not suitable for prose with tone.

**MyMemory** — Convenience option for quick checks. Texts over 500 characters are split into chunks automatically. Quality varies per language pair.

**DeepL / Lara** — Cloud engines with the best quality outside of Claude for European language pairs.
Use as a final-pass step on texts that matter.

---

## File: .\setup_libretranslate.bat

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

---

## File: .\setup_libretranslate.sh

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

---

## File: .\translator.bat

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


---

## File: .\translator.sh

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

# Docker pruefen
check_docker() {
    command -v docker &> /dev/null && docker info > /dev/null 2>&1
}

while ! check_docker; do
    echo " [WARNUNG] Docker nicht erreichbar – LibreTranslate nicht verfuegbar."
    echo " Bitte Docker Desktop starten."
    echo " [R] Erneut versuchen   [S] Ueberspringen"
    read -p " Auswahl: " docker_choice
    if [[ "$docker_choice" =~ ^[Ss]$ ]]; then
        break
    fi
done
if check_docker; then
    echo " Docker online."
fi
echo ""

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

# LibreTranslate starten falls aktiviert
if grep -qi "libretranslate_enabled: true" config.yaml; then
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

---

## File: .\static\app.js

let config = {};
let debounceTimer = null;
let currentTranslation = '';
let isTranslating = false;

// ── Init ────────────────────────────────────────────────────────────────────

async function init() {
  config = await fetch('/config').then(r => r.json());

  // Sprach-Dropdowns befüllen
  const langs = config.languages;
  ['srcLang', 'tgtLang'].forEach(id => {
    const sel = document.getElementById(id);
    Object.entries(langs).forEach(([name, code]) => {
      const opt = document.createElement('option');
      opt.value = code;
      opt.textContent = name;
      sel.appendChild(opt);
    });
  });
  document.getElementById('srcLang').value = config.default_source_lang;
  document.getElementById('tgtLang').value = config.default_target_lang;

  // Final-Pass Buttons
  document.getElementById('deeplBtn').disabled    = !config.deepl_available;
  if (config.libretranslate_available) checkLibre();
  else document.getElementById('libreBtn').disabled = true;
  const mmBtn = document.getElementById('mymemoryBtn');
  mmBtn.disabled = !config.mymemory_available;
  if (!config.mymemory_available) mmBtn.dataset.forceDisabled = '1';
  document.getElementById('laraBtn').disabled     = !config.lara_available;
  if (config.lara_available) updateLaraUsage();
  document.getElementById('deeplStatus').textContent = config.deepl_available
    ? '⬡ DeepL available' : '⬡ DeepL not configured';

  document.getElementById('srcLang').addEventListener('change', () => { if (config.libretranslate_available) checkLibre(); });
  document.getElementById('tgtLang').addEventListener('change', () => { if (config.libretranslate_available) checkLibre(); });

  checkOllama();
  setInterval(checkOllama, 15000);
  setupInput();
}

async function checkOllama() {
  const dot    = document.getElementById('ollamaDot');
  const label  = document.getElementById('ollamaStatus');
  const sel    = document.getElementById('modelSelect');
  try {
    const s = await fetch('/ollama/status').then(r => r.json());
    if (s.online) {
      dot.className     = 'dot ok';
      label.textContent = 'Ollama online';
      const current = sel.value || config.ollama_model;
      sel.innerHTML = '';
      s.models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m;
        if (m === current || m.startsWith(current.split(':')[0])) opt.selected = true;
        sel.appendChild(opt);
      });
      if (!sel.value && s.models.length) sel.value = s.models[0];
    } else {
      dot.className     = 'dot err';
      label.textContent = 'Ollama offline';
      sel.innerHTML = '<option>offline</option>';
    }
  } catch {
    dot.className     = 'dot err';
    label.textContent = 'Ollama not reachable';
  }
}

async function setModel(model) {
  if (!model) return;
  await fetch('/ollama/set_model', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model })
  });
  config.ollama_model = model;
  showToast(`Modell: ${model}`, 'ok');
}

// ── Input Handling ──────────────────────────────────────────────────────────

function setupInput() {
  const ta  = document.getElementById('srcText');
  const out = document.getElementById('tgtOutput');

  ta.addEventListener('scroll', () => {
    const ratio = ta.scrollTop / (ta.scrollHeight - ta.clientHeight || 1);
    out.scrollTop = ratio * (out.scrollHeight - out.clientHeight);
  });
  out.addEventListener('scroll', () => {
    const ratio = out.scrollTop / (out.scrollHeight - out.clientHeight || 1);
    ta.scrollTop = ratio * (ta.scrollHeight - ta.clientHeight);
  });

  ta.addEventListener('input', () => {
    updateCharCount('srcText', 'srcCount');
    const mode = document.getElementById('modeSelect').value;
    if (mode === 'debounce') {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(translateNow, (config.debounce_seconds || 1.5) * 1000);
    }
  });

  ta.addEventListener('keydown', (e) => {
    const mode = document.getElementById('modeSelect').value;
    if (mode === 'sentence' && e.key === 'Enter' && !e.shiftKey) {
      setTimeout(translateNow, 50);
    }
  });
}

function updateCharCount(taId, countId) {
  const len = document.getElementById(taId).value.length;
  document.getElementById(countId).textContent = `${len.toLocaleString('en')} chars`;
  const btn = document.getElementById('mymemoryBtn');
  if (btn && !btn.dataset.forceDisabled) {
    btn.disabled = !config.mymemory_available;
    if (len > 500) {
      btn.textContent = '★ MyMemory (chunked)';
      btn.title = 'Text will be split into 500-char chunks';
    } else {
      btn.textContent = '★ MyMemory - max. 500 characters';
      btn.title = 'Final pass via MyMemory';
    }
  }
}

// ── Translate ───────────────────────────────────────────────────────────────

const CHUNK_LIMITS = { ollama: 6000, deepl: 4900, mymemory: 480 };

async function translate(engine = 'ollama') {
  const text = document.getElementById('srcText').value.trim();
  if (!text || isTranslating) return;

  const src = document.getElementById('srcLang').value;
  const tgt = document.getElementById('tgtLang').value;
  if (src === tgt) { showToast('Source and target language are identical', 'err'); return; }

  const limit = CHUNK_LIMITS[engine];
  const needsChunking = limit && text.length > limit;

  isTranslating = true;
  const out = document.getElementById('tgtOutput');
  out.textContent = 'Translating …';
  out.className = 'output-area loading';

  try {
    if (needsChunking) {
      // Chunks vorbereiten
      const prepRes = await fetch('/translate/chunks/prepare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, engine })
      });
      const prepData = await prepRes.json();
      if (!prepRes.ok) throw new Error(prepData.detail || 'Error');

      const { chunks, total } = prepData;
      const results = [];
      let context = '';

      for (let i = 0; i < chunks.length; i++) {
        out.textContent = `Übersetze… (${i + 1} / ${total})\n\n${results.join('\n\n')}`;

        const res = await fetch('/translate/chunk', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: chunks[i],
            source_lang: src,
            target_lang: tgt,
            engine,
            context
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Error');

        results.push(data.translation);
        // letzter Absatz als Kontext für nächsten Chunk
        const paras = data.translation.split('\n\n');
        context = paras[paras.length - 1].slice(-300);

        out.textContent = results.join('\n\n');
      }

      currentTranslation = results.join('\n\n');

    } else {
      // Normaler Pfad — kein Chunking
      const res = await fetch('/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, source_lang: src, target_lang: tgt, engine })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Error');
      currentTranslation = data.translation;
    }

    out.textContent = currentTranslation;
    out.className = 'output-area';
    document.getElementById('tgtCount').textContent =
      `${currentTranslation.length.toLocaleString('en')} chars`;
    if (engine === 'lara') updateLaraUsage();
    document.getElementById('engineBadge').textContent = `via ${engine}`;

  } catch (err) {
    out.textContent = `⚠ ${err.message}`;
    out.className = 'output-area';
    showToast(err.message, 'err');
  } finally {
    isTranslating = false;
  }
}

function translateNow()   { translate('ollama'); }
function deeplFinal()     { translate('deepl'); }
function libreFinal()     { translate('libretranslate'); }
function mymemoryFinal()  { translate('mymemory'); }

async function checkLibre() {
  const src = document.getElementById('srcLang').value;
  const tgt = document.getElementById('tgtLang').value;
  const btn = document.getElementById('libreBtn');
  const statusEl = document.getElementById('libreStatus');
  const dotEl = document.getElementById('libreDot');
  const textEl = document.getElementById('libreStatusText');
  try {
    const s = await fetch(`/libretranslate/status?source=${src}&target=${tgt}`).then(r => r.json());
    if (!s.online) {
      btn.disabled = true;
      btn.textContent = '★ LibreTranslate (offline)';
      btn.title = 'LibreTranslate is not running';
      statusEl.style.display = 'none';
    } else if (!s.pair_available) {
      btn.disabled = true;
      btn.textContent = `★ LibreTranslate (${s.reason})`;
      btn.title = `Language pair not available: ${s.reason}`;
      dotEl.className = 'dot ok';
      textEl.textContent = 'LibreTranslate';
      statusEl.style.display = '';
    } else {
      btn.disabled = false;
      btn.textContent = '★ LibreTranslate';
      btn.title = 'Final pass via LibreTranslate';
      dotEl.className = 'dot ok';
      textEl.textContent = 'LibreTranslate';
      statusEl.style.display = '';
    }
  } catch {
    btn.disabled = true;
    btn.textContent = '★ LibreTranslate (offline)';
    statusEl.style.display = 'none';
  }
}

async function stopLibre() {
  try {
    const r = await fetch('/libretranslate/stop', { method: 'POST' });
    if (r.ok) {
      showToast('LibreTranslate stopped', 'ok');
      setTimeout(checkLibre, 1000);
    } else {
      const d = await r.json();
      showToast(d.detail || 'Stop failed', 'err');
    }
  } catch {
    showToast('Stop failed', 'err');
  }
}

async function updateLaraUsage() {
  try {
    const data = await fetch('/lara/usage').then(r => r.json());
    const btn = document.getElementById('laraBtn');
    const remaining = data.remaining.toLocaleString('de');
    const limit = data.limit.toLocaleString('de');
    btn.textContent = `★ Lara (${remaining} / ${limit})`;
    if (data.remaining <= 0) {
      btn.disabled = true;
      btn.title = 'Lara: Tageslimit erreicht';
    }
  } catch {}
}

function laraFinal() { translate('lara'); }

// ── Utils ───────────────────────────────────────────────────────────────────

function swapLangs() {
  const s = document.getElementById('srcLang');
  const t = document.getElementById('tgtLang');
  [s.value, t.value] = [t.value, s.value];
  if (config.libretranslate_available) checkLibre();
}

function clearAll() {
  document.getElementById('srcText').value = '';
  document.getElementById('tgtOutput').innerHTML = '<span class="placeholder-text">Translation appears here …</span>';
  currentTranslation = '';
  ['srcCount', 'tgtCount'].forEach(id =>
    document.getElementById(id).textContent = '0 chars');
}

async function exportMD() {
  const src = document.getElementById('srcText').value.trim();
  if (!src) { showToast('Kein Text zum Exportieren', 'err'); return; }
  if (!currentTranslation) { showToast('No translation yet', 'err'); return; }

  try {
    const res = await fetch('/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_text: src,
        target_text: currentTranslation,
        source_lang: document.getElementById('srcLang').value,
        target_lang: document.getElementById('tgtLang').value,
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);
    showToast(`✓ Exportiert nach ${data.export_dir}`, 'ok');
  } catch (err) {
    showToast(err.message, 'err');
  }
}

async function openExportDir() {
  try {
    const r = await fetch('/export/open');
    if (!r.ok) {
      const d = await r.json();
      showToast(d.detail || 'Could not open folder', 'err');
    }
  } catch {
    showToast('Could not open folder', 'err');
  }
}

function showToast(msg, type = '') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast show ${type}`;
  setTimeout(() => t.className = 'toast', 3000);
}

function copyTranslation() {
  if (!currentTranslation) { showToast('Keine Übersetzung vorhanden', 'err'); return; }
  navigator.clipboard.writeText(currentTranslation)
    .then(() => showToast('✓ In Zwischenablage kopiert', 'ok'))
    .catch(() => showToast('Kopieren fehlgeschlagen', 'err'));
}

init();

---

## File: .\static\style.css

:root {
  --bg:        #0c0b12;
  --surface:   #13111c;
  --border:    #2a2440;
  --accent:    #c084fc;
  --accent2:   #818cf8;
  --warn:      #ff6b6b;
  --text:      #e8e6f0;
  --muted:     #6b6880;
  --radius:    10px;
  --glow:      rgba(192, 132, 252, 0.18);
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html { height: 100%; overflow: hidden; }

body {
  background: var(--bg);
  background-image:
    radial-gradient(ellipse at 20% 10%, rgba(129, 60, 180, 0.12) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 80%, rgba(99, 60, 160, 0.10) 0%, transparent 50%);
  color: var(--text);
  font-family: 'Syne', sans-serif;
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* ── Header ── */
header {
  padding: 18px 28px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.logo {
  font-size: 1.25rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--accent);
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 8px;
  text-shadow: 0 0 20px rgba(192, 132, 252, 0.5);
}
.logo span { color: var(--text); text-shadow: none; }
.logo svg { filter: drop-shadow(0 0 6px rgba(192, 132, 252, 0.7)); flex-shrink: 0; }

.controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-left: auto;
}

select, button {
  font-family: 'Syne', sans-serif;
  font-size: 0.82rem;
  font-weight: 600;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  transition: all 0.15s;
}

select {
  padding: 7px 12px;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23666672'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  padding-right: 28px;
}
select:hover, select:focus { border-color: var(--accent); outline: none; }

.lang-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.lang-label {
  font-size: 0.72rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.swap-btn {
  background: none;
  border: 1px solid var(--border);
  padding: 7px 10px;
  font-size: 0.9rem;
  color: var(--muted);
}
.swap-btn:hover { border-color: var(--accent); color: var(--accent); }

.sep { width: 1px; height: 28px; background: var(--border); }

.mode-label {
  font-size: 0.72rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

/* ── Status bar ── */
.statusbar {
  padding: 6px 28px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 0.75rem;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
}
.dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--muted);
  display: inline-block;
  margin-right: 5px;
}
.dot.ok  { background: var(--accent); box-shadow: 0 0 6px var(--accent); }
.dot.err { background: var(--warn);   box-shadow: 0 0 6px var(--warn); }

/* ── Main columns ── */
main {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  min-height: 0;
  overflow: hidden;
}

.pane {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  min-height: 0;
  overflow: hidden;
}
.pane:last-child { border-right: none; }

.pane-header {
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.pane-title {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--muted);
}
.char-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.72rem;
  color: var(--muted);
}

textarea {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text);
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.9rem;
  line-height: 1.7;
  padding: 20px;
  resize: none;
  outline: none;
  min-height: 0;
  overflow-y: auto;
}
textarea::placeholder { color: #3a3a42; }
textarea:focus { background: #111114; }

.output-area {
  flex: 1;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.9rem;
  line-height: 1.7;
  padding: 20px;
  color: var(--text);
  white-space: pre-wrap;
  overflow-y: auto;
  min-height: 0;
  position: relative;
}
.output-area.loading { color: var(--muted); }
.output-area.loading::after {
  content: '';
  display: inline-block;
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--accent);
  margin-left: 6px;
  animation: pulse 0.8s ease-in-out infinite;
  vertical-align: middle;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.3; transform: scale(0.6); }
}
.placeholder-text { color: #3a3a42; }

/* ── Footer / Actions ── */
footer {
  border-top: 1px solid var(--border);
  padding: 14px 28px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.btn {
  padding: 9px 18px;
  border-radius: var(--radius);
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  transition: all 0.15s;
}
.btn:hover { border-color: var(--accent); color: var(--accent); }
.btn:active { transform: scale(0.97); }

.btn-accent {
  background: var(--accent);
  color: #0c0b12;
  border-color: var(--accent);
}
.btn-accent:hover { background: #d8b4fe; border-color: #d8b4fe; color: #0c0b12; }

.btn-deepl {
  background: var(--accent2);
  color: #fff;
  border-color: var(--accent2);
}
.btn-deepl:hover { background: #9980ff; border-color: #9980ff; }
.btn-deepl:disabled { opacity: 0.35; cursor: not-allowed; }

.btn-libre {
  background: #a78bfa;
  color: #0c0b12;
  border-color: #a78bfa;
}
.btn-libre:hover { background: #c4b5fd; border-color: #c4b5fd; }
.btn-libre:disabled { opacity: 0.35; cursor: not-allowed; }

.btn-mymemory {
  background: #c4b5fd;
  color: #0c0b12;
  border-color: #c4b5fd;
}
.btn-mymemory:hover { background: #ddd6fe; border-color: #ddd6fe; }
.btn-mymemory:disabled { opacity: 0.35; cursor: not-allowed; }

.btn-lara {
  background: #94a3b8;
  color: #0c0b12;
  border-color: #94a3b8;
}
.btn-lara:hover { background: #cbd5e1; border-color: #cbd5e1; }
.btn-lara:disabled { opacity: 0.35; cursor: not-allowed; }

.btn-clear {
  color: var(--warn);
  border-color: transparent;
  background: none;
}
.btn-clear:hover { border-color: var(--warn); }

.spacer { flex: 1; }

/* ── Toast ── */
.toast {
  position: fixed;
  bottom: 28px; left: 50%;
  transform: translateX(-50%) translateY(20px);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 20px;
  font-size: 0.82rem;
  color: var(--text);
  opacity: 0;
  transition: all 0.25s;
  pointer-events: none;
  white-space: nowrap;
  z-index: 100;
}
.toast.show {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}
.toast.ok  { border-color: var(--accent); color: var(--accent); }
.toast.err { border-color: var(--warn);   color: var(--warn); }

---


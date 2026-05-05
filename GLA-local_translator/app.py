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

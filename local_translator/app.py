"""
LocalTranslate – FastAPI Backend

Besitzt:
  - FastAPI app-Instanz, Static-Mount, Index-Route
  - Alle Pydantic Models
  - Alle Endpoints
  - __main__ Block mit Browser-Launch und uvicorn

Importiert aus diesem Projekt:
  - core.config: state, Konstanten
  - core.chunking: split_chunks, lang_name
  - core.logging: get_lara_usage
  # write_chunk_perf_log wird via engines.ollama aufgerufen — kein Direkt-Import
  - engines.ollama: translate_ollama, run_s2, detect_mindset, write_chunk_perf_log
  - engines.external: translate_deepl, translate_libretranslate,
                      translate_mymemory, translate_lara
"""

import os
import webbrowser
from datetime import datetime
from pathlib import Path
from threading import Thread

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import (
    AUTO_OPEN_BROWSER,
    DEBOUNCE_SEC,
    DEFAULT_MINDSET,
    DEFAULT_MODE,
    DEFAULT_SRC,
    DEFAULT_TGT,
    DEEPL_CHUNK_SIZE,
    DEEPL_KEY,
    EXPORT_DIR,
    FILENAME_PFX,
    HOST,
    LANGUAGES,
    LARA_DAILY_LIMIT,
    LARA_ID,
    LARA_ON,
    LARA_SECRET,
    LIBRE_ON,
    LIBRE_URL,
    MINDSET_MODEL,
    MINDSETS,
    MYMEMORY_ON,
    OLLAMA_CHUNK_SIZE,
    OLLAMA_MODEL,
    OLLAMA_URL,
    INDEX_PATH,
    MYMEMORY_CHUNK_SIZE,
    PORT,
    state,
)
from core.chunking import lang_name, split_chunks
from core.logging import get_lara_usage
from core import link_guard
from terminology.terminology import term_engine
from engines.ollama import (
    detect_mindset,
    run_s2,
    translate_ollama,
    write_chunk_perf_log,
)
from engines.external import (
    translate_deepl,
    translate_libretranslate,
    translate_lara,
    translate_mymemory,
)

# ── FastAPI Setup ──────────────────────────────────────────────────────────────

app = FastAPI(title="LocalTranslate")

app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(INDEX_PATH.read_text(encoding="utf-8"))

# ── Pydantic Models ───────────────────────────────────────────────────────────

class TranslateRequest(BaseModel):
    text: str
    source_lang: str
    target_lang: str
    engine: str = "ollama"
    s2_model: str = ""

class ExportRequest(BaseModel):
    source_text: str
    target_text: str
    source_lang: str
    target_lang: str

class ChunkRequest(BaseModel):
    text: str
    source_lang: str
    target_lang: str
    engine: str = "ollama"
    context: str = ""
    mindset: str = "general"
    s2_model: str = ""
    chunk_index: int = 0

class PrepareRequest(BaseModel):
    text: str
    engine: str = "ollama"

class DetectMindsetRequest(BaseModel):
    text: str
    mindset_model: str = ""

class SetModelRequest(BaseModel):
    model: str

# ── Endpoints — Konfiguration ─────────────────────────────────────────────────

@app.get("/config")
async def get_config():
    return {
        "languages":               LANGUAGES,
        "default_source_lang":     DEFAULT_SRC,
        "default_target_lang":     DEFAULT_TGT,
        "debounce_seconds":        DEBOUNCE_SEC,
        "default_mode":            DEFAULT_MODE,
        "deepl_available":         bool(DEEPL_KEY),
        "libretranslate_available": LIBRE_ON,
        "mymemory_available":      MYMEMORY_ON,
        "lara_available":          LARA_ON and bool(LARA_ID) and bool(LARA_SECRET),
        "ollama_model":            state.active_model,
        "mindset_model":           MINDSET_MODEL,
        "default_mindset":         DEFAULT_MINDSET,
        "mindsets":                {k: v.get("label", k) for k, v in MINDSETS.items()},
    }

@app.get("/mindsets")
async def get_mindsets():
    return {
        k: {"label": v.get("label", k), "rst_mode": v.get("rst_mode", "")}
        for k, v in MINDSETS.items()
    }

# ── Endpoints — Übersetzung ───────────────────────────────────────────────────

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
        import time

        # ── link_guard protect — außen um TermEngine, überlebt S1 + S2 ────────
        link_result = link_guard.protect(req.text)

        # ── protect vor S1 ───────────────────────────────────────────────────
        protected_text, code_map = term_engine.protect(
            link_result.protected_text, src_lang=req.source_lang, mindset=req.mindset
        )

        t0     = time.monotonic()
        result = await translate_ollama(
            protected_text, req.source_lang, req.target_lang, req.context, req.mindset
        )
        time_s1 = time.monotonic() - t0
        time_s2 = 0.0

        # ── restore nach S1 — S2 bekommt sauberen Text ───────────────────────
        result = term_engine.restore(result, tgt_lang=req.target_lang,
                                     code_map=code_map, mindset=req.mindset)
        issues = term_engine.verify(protected_text, result, code_map)
        if issues:
            for issue in issues:
                print(f"  [TermEngine] {issue}")

        # ── S2 editiert auf restauriertem EN-Text ─────────────────────────────
        if req.s2_model:
            t1      = time.monotonic()
            result  = await run_s2(result, req.s2_model, req.mindset)
            time_s2 = time.monotonic() - t1

        # ── link_guard restore — nach S1+S2, ganz am Ende ──────────────────────
        result = link_guard.restore(result, link_result.mapping)

        write_chunk_perf_log(req.chunk_index, len(req.text), time_s1, time_s2, req.s2_model,
                             terms_protected=len(code_map))

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
        import time

        link_result = link_guard.protect(req.text)

        protected_text, code_map = term_engine.protect(
            link_result.protected_text, src_lang=req.source_lang, mindset="general"
        )
        t0     = time.monotonic()
        result = await translate_ollama(protected_text, req.source_lang, req.target_lang)
        time_s1 = time.monotonic() - t0
        time_s2 = 0.0
        result = term_engine.restore(result, tgt_lang=req.target_lang,
                                     code_map=code_map, mindset="general")
        if req.s2_model:
            t1      = time.monotonic()
            result  = await run_s2(result, req.s2_model, mindset="general")
            time_s2 = time.monotonic() - t1

        result = link_guard.restore(result, link_result.mapping)

        write_chunk_perf_log(0, len(req.text), time_s1, time_s2, req.s2_model,
                             terms_protected=len(code_map))

    return {"translation": result}

# ── Endpoints — Ollama ────────────────────────────────────────────────────────

@app.get("/ollama/status")
async def ollama_status():
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            r      = await client.get(f"{OLLAMA_URL}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            current_available = OLLAMA_MODEL in models or any(
                m.startswith(OLLAMA_MODEL.split(":")[0]) for m in models
            )
            return {"online": True, "models": models, "current_model_available": current_available}
        except Exception:
            return {"online": False, "models": [], "current_model_available": False}

@app.get("/ollama/vram")
async def ollama_vram():
    """Geladene Modelle + VRAM aus /api/ps. Optional: GPU-Gesamt via nvidia-smi."""
    import subprocess
    loaded = []
    vram_used_bytes = 0

    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            r = await client.get(f"{OLLAMA_URL}/api/ps")
            r.raise_for_status()
            for m in r.json().get("models", []):
                name = m.get("name", "")
                size = m.get("size_vram", 0) or 0
                loaded.append({"name": name, "vram_bytes": size})
                vram_used_bytes += size
        except Exception:
            pass

    vram_total_bytes = None
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            mb = int(result.stdout.strip().split("\n")[0])
            vram_total_bytes = mb * 1024 * 1024
    except Exception:
        pass

    return {
        "loaded":           loaded,
        "vram_used_bytes":  vram_used_bytes,
        "vram_total_bytes": vram_total_bytes,
    }

@app.post("/ollama/unload")
async def ollama_unload():
    """Alle geladenen Modelle aus VRAM entladen."""
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            r      = await client.get(f"{OLLAMA_URL}/api/ps")
            r.raise_for_status()
            models = [m.get("name") for m in r.json().get("models", []) if m.get("name")]
        except Exception:
            return {"unloaded": []}

    unloaded = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for name in models:
            try:
                await client.post(f"{OLLAMA_URL}/api/generate", json={
                    "model": name, "keep_alive": 0, "prompt": "", "stream": False,
                })
                unloaded.append(name)
            except Exception:
                pass

    return {"unloaded": unloaded}

@app.post("/ollama/set_model")
async def set_model(req: SetModelRequest):
    state.active_model = req.model
    return {"model": state.active_model}

# ── Endpoints — Mindset ───────────────────────────────────────────────────────

@app.post("/mindset/detect")
async def detect_mindset_endpoint(req: DetectMindsetRequest):
    mindset = await detect_mindset(req.text.strip(), req.mindset_model)
    return {"mindset": mindset}

# ── Endpoints — Lara ──────────────────────────────────────────────────────────

@app.get("/lara/usage")
async def lara_usage():
    usage = get_lara_usage()
    return {
        "chars_today": usage["chars"],
        "limit":       LARA_DAILY_LIMIT,
        "remaining":   max(0, LARA_DAILY_LIMIT - usage["chars"]),
    }

# ── Endpoints — Terminologie ──────────────────────────────────────────────────

@app.get("/terminology/status")
async def terminology_status(
    source: str = DEFAULT_SRC,
    target: str = DEFAULT_TGT,
    mindset: str = DEFAULT_MINDSET,
):
    return term_engine.status(src_lang=source, tgt_lang=target, mindset=mindset)

# ── Endpoints — LibreTranslate ────────────────────────────────────────────────

@app.get("/libretranslate/status")
async def libretranslate_status(source: str = "", target: str = ""):
    if not LIBRE_ON:
        return {"online": False, "pair_available": False, "reason": "disabled"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r     = await client.get(f"{LIBRE_URL}/languages")
            r.raise_for_status()
            codes = [lang["code"].lower() for lang in r.json()]
            src_ok  = source.lower() in codes
            tgt_ok  = target.lower() in codes
            pair_ok = src_ok and tgt_ok
            reason  = ""
            if not pair_ok:
                missing = []
                if not src_ok: missing.append(source.upper())
                if not tgt_ok: missing.append(target.upper())
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
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return {"stopped": True}
        raise HTTPException(
            status_code=500,
            detail=f"Docker error: {result.stderr.strip()}",
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Docker not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stop failed: {e}")

# ── Endpoints — Export ────────────────────────────────────────────────────────

@app.post("/export")
async def export_md(req: ExportRequest):
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    src_file = EXPORT_DIR / f"{FILENAME_PFX}_{req.source_lang.lower()}_{ts}.md"
    tgt_file = EXPORT_DIR / f"{FILENAME_PFX}_{req.target_lang.lower()}_{ts}.md"

    src_file.write_text(
        f"# {lang_name(req.source_lang)}\n\n{req.source_text}\n",
        encoding="utf-8",
    )
    tgt_file.write_text(
        f"# {lang_name(req.target_lang)}\n\n{req.target_text}\n",
        encoding="utf-8",
    )
    return {
        "source_file": str(src_file),
        "target_file": str(tgt_file),
        "export_dir":  str(EXPORT_DIR.resolve()),
    }

@app.get("/export/open")
async def export_open():
    import subprocess
    import sys
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
    if AUTO_OPEN_BROWSER:
        def _open_when_ready():
            import time
            import urllib.request
            import subprocess
            import sys
            url = f"http://{HOST}:{PORT}"
            for _ in range(20):
                try:
                    urllib.request.urlopen(f"{url}/config", timeout=1)
                    chrome = os.environ.get("LOCALTRANSLATE_BROWSER", "").strip('"')
                    if chrome and os.path.exists(chrome):
                        subprocess.Popen([chrome, url])
                    else:
                        webbrowser.open(url)
                    return
                except Exception:
                    time.sleep(0.5)
        Thread(target=_open_when_ready, daemon=True).start()

    print(f"\n  LocalTranslate läuft auf http://{HOST}:{PORT}\n")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

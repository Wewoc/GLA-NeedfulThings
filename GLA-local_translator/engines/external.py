"""
engines/external.py — Externe Übersetzungs-Engines

Besitzt:
  - translate_deepl()
  - translate_libretranslate()
  - translate_mymemory()
  - translate_lara()

Importiert:
  - httpx, fastapi.HTTPException
  - core.config: Credentials und Engine-Flags
  - core.logging: add_lara_usage

Wird importiert von: app.py
"""

import httpx
from fastapi import HTTPException

from core.config import (
    DEEPL_FREE,
    DEEPL_KEY,
    LARA_ID,
    LARA_SECRET,
    LIBRE_KEY,
    LIBRE_ON,
    LIBRE_URL,
    MYMEMORY_MAIL,
    MYMEMORY_ON,
)
from core.logging import add_lara_usage

# ── DeepL ─────────────────────────────────────────────────────────────────────

async def translate_deepl(text: str, source_lang: str, target_lang: str) -> str:
    if not DEEPL_KEY:
        raise HTTPException(
            status_code=400,
            detail="Kein DeepL API Key in config.yaml eingetragen.",
        )
    base = "https://api-free.deepl.com" if DEEPL_FREE else "https://api.deepl.com"
    url  = f"{base}/v2/translate"
    params = {
        "auth_key":   DEEPL_KEY,
        "text":       text,
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

# ── LibreTranslate ────────────────────────────────────────────────────────────

async def translate_libretranslate(text: str, source_lang: str, target_lang: str) -> str:
    if not LIBRE_ON:
        raise HTTPException(status_code=400, detail="LibreTranslate nicht aktiviert.")
    payload: dict = {
        "q":      text,
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

# ── MyMemory ──────────────────────────────────────────────────────────────────

async def translate_mymemory(text: str, source_lang: str, target_lang: str) -> str:
    if not MYMEMORY_ON:
        raise HTTPException(status_code=400, detail="MyMemory nicht aktiviert.")
    params: dict = {
        "q":        text,
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
                raise HTTPException(
                    status_code=502,
                    detail=f"MyMemory: {data.get('responseDetails', 'Fehler')}",
                )
            return data["responseData"]["translatedText"].strip()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"MyMemory Fehler: {e}")

# ── Lara ──────────────────────────────────────────────────────────────────────

async def translate_lara(text: str, source_lang: str, target_lang: str) -> str:
    if not LARA_ID or not LARA_SECRET:
        raise HTTPException(status_code=400, detail="Lara Credentials fehlen in .env.")
    try:
        import asyncio
        from lara_sdk import Credentials, Translator
        credentials = Credentials(access_key_id=LARA_ID, access_key_secret=LARA_SECRET)
        lara = Translator(credentials)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: lara.translate(text, source=source_lang.lower(), target=target_lang.lower()),
        )
        translation = result.translation.strip()
        add_lara_usage(len(text))
        return translation
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="lara-sdk nicht installiert. Bitte 'pip install lara-sdk' ausführen.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lara Fehler: {e}")

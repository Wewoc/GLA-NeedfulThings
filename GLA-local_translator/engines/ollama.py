"""
engines/ollama.py — Ollama-Engine

Besitzt:
  - translate_ollama()
  - run_s2()
  - detect_mindset()

Importiert:
  - httpx, re, fastapi.HTTPException
  - core.config: OLLAMA_URL, MINDSETS, state
  - core.chunking: lang_name
  - core.logging: _write_perf_log
  - terminology.terminology: term_engine

Wird importiert von: app.py
"""

import re

import httpx
from fastapi import HTTPException

from core.config import MINDSETS, OLLAMA_URL, state
from core.chunking import lang_name
from core.logging import _write_perf_log
from terminology.terminology import term_engine

# ── S1 — Primärübersetzung ────────────────────────────────────────────────────

async def translate_ollama(
    text: str,
    source_lang: str,
    target_lang: str,
    context: str = "",
    mindset: str = "general",
) -> str:
    src = lang_name(source_lang)
    tgt = lang_name(target_lang)
    ms  = MINDSETS.get(mindset, MINDSETS.get("general", {}))

    anchor = ms.get("anchor", "")
    mam    = ms.get("mam", "")
    veto   = ms.get("veto", [])
    p0     = ms.get("p0", (
        "Output only the translation. No introductory sentences. "
        "No explanations. Do not repeat the source text. "
        "Do not comment on the translation."
    ))

    veto_hint = (
        f"Keep these terms untranslated: {', '.join(veto)}.\n"
        if veto else ""
    )
    context_hint = (
        f"For continuity, the previous passage ended with:\n{context}\n\n"
        if context else ""
    )
    prompt = (
        f"{anchor}\n\n"
        f"{mam}\n"
        f"{veto_hint}"
        f"{context_hint}"
        f"Translate the following text from {src} to {tgt}.\n\n"
        f"{text}\n\n"
        f"{p0}"
    )
    payload = {
        "model": state.active_model,
        "prompt": prompt,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=180.0)) as client:
        try:
            r = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
            r.raise_for_status()
            return r.json().get("response", "").strip()
        except httpx.ConnectError:
            raise HTTPException(
                status_code=503,
                detail="Ollama nicht erreichbar. Läuft 'ollama serve'?",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ollama Fehler: {e}")

# ── S2 — Qualitäts-/Terminologie-Pass ────────────────────────────────────────

def _strip_code_blocks(text: str) -> str:
    return re.sub(r'```.*?```', '', text, flags=re.DOTALL)

async def run_s2(text: str, s2_model: str, mindset: str = "general") -> str:
    """Editiert, übersetzt nicht. Fällt still auf S1 zurück bei Fehler oder Drift."""
    ms    = MINDSETS.get(mindset, MINDSETS.get("general", {}))
    anchor = ms.get("anchor", "")
    veto   = ms.get("veto", [])
    veto_hint = f"Keep these terms untranslated: {', '.join(veto)}.\n" if veto else ""

    prompt = (
        f"{anchor}\n\n"
        "You are a post-editor reviewing a machine translation. "
        "Your scope is strictly limited to: fixing mistranslations, improving awkward phrasing, "
        "and correcting terminology against the domain anchor above. "
        "Do not change register, tone, or style beyond what is strictly necessary. "
        "Do not restructure sentences or paragraphs. "
        "Do not expand abbreviations or version numbers (e.g. V0.1 stays V0.1, GUI stays GUI, EXE stays EXE). "
        "Do not add, remove, or alter any Markdown formatting, italics, code blocks, "
        "or structural elements not already present in the input. "
        "Do not wrap the entire output in a code block or markdown fence. "
        "Do not translate — the text is already in the target language. "
        "If a passage is already correct, leave it exactly as is. "
        "Never delete sentences or paragraphs — every part of the input must appear in the output.\n"
        f"{veto_hint}"
        "Output only the corrected text. No explanations. No comments.\n"
        "IMPORTANT: Do not translate. The text is already in the target language. "
        "Output it in the same language as the input.\n\n"
        f"{text}"
    )
    payload = {"model": s2_model, "prompt": prompt, "stream": False}

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=180.0)) as client:
        try:
            # S1 aus VRAM entladen bevor S2 startet
            await client.post(f"{OLLAMA_URL}/api/generate", json={
                "model": state.active_model, "keep_alive": 0,
                "prompt": "", "stream": False,
            })
            r = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
            r.raise_for_status()
            result = r.json().get("response", "").strip()
            if not result:
                return text

            # Drift-Check: S2 hat zurückübersetzt wenn non-ASCII-Anteil stark gestiegen
            input_non_ascii  = sum(1 for c in _strip_code_blocks(text)   if ord(c) > 127) / max(len(_strip_code_blocks(text)),   1)
            output_non_ascii = sum(1 for c in _strip_code_blocks(result) if ord(c) > 127) / max(len(_strip_code_blocks(result)), 1)
            if output_non_ascii > input_non_ascii + 0.15:
                return text  # Fallback auf S1

            return result
        except Exception:
            return text  # S1-Ergebnis als Fallback

# ── Mindset-Erkennung ─────────────────────────────────────────────────────────

async def detect_mindset(text: str) -> str:
    """Klassifiziert Text per Ollama-Call. Gibt Mindset-Key zurück, Fallback 'general'."""
    if not text:
        return "general"

    length = len(text)
    if length < 6000:
        positions, snippet_len = [0], 500
    elif length < 12000:
        positions, snippet_len = [0, length // 2], 400
    elif length < 60000:
        positions, snippet_len = [0, length // 3, (length // 3) * 2], 300
    elif length < 100000:
        positions, snippet_len = [0, length // 4, length // 2, (length // 4) * 3], 250
    else:
        positions, snippet_len = [
            0, length // 5, (length // 5) * 2,
            (length // 5) * 3, (length // 5) * 4
        ], 200

    snippets = [text[pos:pos + snippet_len].strip() for pos in positions]
    valid_mindsets = list(MINDSETS.keys())
    excerpts = "\n\n---\n\n".join(
        f"Excerpt {i+1}:\n{s}" for i, s in enumerate(snippets)
    )
    prompt = (
        f"Classify the following text excerpts into exactly one of these categories: "
        f"{', '.join(valid_mindsets)}.\n"
        "Focus on the overall register and purpose of the text, not just vocabulary. "
        "A text about technical topics written in an academic, reflective, or analytical "
        "style is 'academic', not 'technical'. "
        "Use 'technical' only for documentation, specifications, manuals, API references, or code. "
        "Reply with only the category name, nothing else.\n\n"
        f"{excerpts}"
    )
    payload = {"model": state.active_model, "prompt": prompt, "stream": False}

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=30.0)) as client:
        try:
            r = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
            r.raise_for_status()
            detected = r.json().get("response", "").strip().lower()
            return detected if detected in valid_mindsets else "general"
        except Exception:
            return "general"

# ── Perf-Log-Wrapper ──────────────────────────────────────────────────────────

def write_chunk_perf_log(
    chunk_index: int,
    chunk_size: int,
    time_s1: float,
    time_s2: float,
    s2_model: str,
    terms_protected: int = 0,
) -> None:
    """Übergibt state.active_model explizit an core.logging — kein State-Import dort."""
    try:
        _write_perf_log(
            chunk_index=chunk_index,
            chunk_size=chunk_size,
            time_s1=time_s1,
            time_s2=time_s2,
            model_s1=state.active_model,
            model_s2=s2_model,
            terms_protected=terms_protected,
        )
    except Exception:
        pass

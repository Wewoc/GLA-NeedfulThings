"""
core/chunking.py — Textteilung und Sprachname-Hilfsfunktion

Besitzt:
  - LANG_NAMES (abgeleitet aus LANGUAGES)
  - lang_name(code) — benutzt von engines/ollama.py und app.py (Export)
  - split_chunks(text, limit)

Importiert: core.config (LANGUAGES)
Wird importiert von: engines/ollama.py, app.py
"""

from core.config import LANGUAGES

# ── Sprachname-Mapping ────────────────────────────────────────────────────────

LANG_NAMES = {v: k for k, v in LANGUAGES.items()}

def lang_name(code: str) -> str:
    return LANG_NAMES.get(code.upper(), code)

# ── Chunk-Logik ───────────────────────────────────────────────────────────────

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

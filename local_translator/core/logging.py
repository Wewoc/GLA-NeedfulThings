"""
core/logging.py — Performance-Log und Lara-Nutzungszähler

Besitzt:
  - _ensure_perf_log(), _write_perf_log()
  - get_lara_usage(), add_lara_usage()

Importiert: core.config (Pfade, Konstanten)
Wird importiert von: engines/ollama.py (perf log), app.py (lara usage endpoint)

Hinweis: _write_perf_log() bekommt active_model als expliziten Parameter —
  keine Abhängigkeit auf RuntimeState, logging bleibt vollständig unabhängig.
"""

import json
from datetime import datetime

from core.config import CSV_SEP, LARA_DAILY_LIMIT, LARA_USAGE_FILE, PERF_LOG

# ── Performance-Log ───────────────────────────────────────────────────────────

def _ensure_perf_log() -> None:
    if not PERF_LOG.exists():
        PERF_LOG.write_text(
            CSV_SEP.join([
                "timestamp", "chunk_index", "chunk_size", "complexity",
                "time_s1", "time_s2", "model_s1", "model_s2", "terms_protected"
            ]) + "\n",
            encoding="utf-8"
        )

def _write_perf_log(
    chunk_index: int,
    chunk_size: int,
    time_s1: float,
    time_s2: float,
    model_s1: str,
    model_s2: str,
    terms_protected: int = 0,
) -> None:
    """active_model wird als expliziter Parameter übergeben — kein State-Import."""
    complexity = "low" if chunk_size < 2000 else "medium" if chunk_size < 4000 else "high"
    _ensure_perf_log()
    with open(PERF_LOG, "a", encoding="utf-8") as f:
        f.write(CSV_SEP.join([
            datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            str(chunk_index),
            str(chunk_size),
            complexity,
            str(int(round(time_s1))),
            str(int(round(time_s2))),
            model_s1,
            model_s2 or "",
            str(terms_protected),
        ]) + "\n")

# ── Lara-Nutzungszähler ───────────────────────────────────────────────────────

def get_lara_usage() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        data = json.loads(LARA_USAGE_FILE.read_text(encoding="utf-8"))
        if data.get("date") != today:
            return {"date": today, "chars": 0}
        return data
    except Exception:
        return {"date": today, "chars": 0}

def add_lara_usage(chars: int) -> None:
    usage = get_lara_usage()
    usage["chars"] += chars
    LARA_USAGE_FILE.write_text(json.dumps(usage), encoding="utf-8")

"""
terminology/terminology.py — Runtime Terminologie-Engine

Struktur:
  terminology/
    technical/de.json   {"§Txxxxxxxx§": "Betriebssystem"}
    technical/en.json   {"§Txxxxxxxx§": "Operating System"}
    legal/de.json + en.json
    ... (general, medical, editorial, academic, marketing, political)

Neue Zielsprache: fr.json in den Mindset-Ordner legen — fertig.

API:
  engine = TermEngine()
  ok = engine.check(src_lang="DE", tgt_lang="EN", mindset="technical")
  protected, code_map = engine.protect(text, src_lang="DE", mindset="technical")
  result = engine.restore(translation, tgt_lang="EN", code_map=code_map)
  issues = engine.verify(protected, result, code_map)
  info   = engine.status(src_lang, tgt_lang, mindset)
"""

import json
import re
from pathlib import Path

_TERMINOLOGY_DIR = Path(__file__).resolve().parent
_CODE_PATTERN    = re.compile(r"§T[0-9a-f]{8}§")

ALL_MINDSETS = ["general", "technical", "legal", "medical",
                "editorial", "academic", "marketing", "political"]


class TermEngine:

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Cache: (mindset, lang) -> {code: term}
            cls._instance._cache: dict[tuple, dict] = {}
        return cls._instance

    # ── Laden ─────────────────────────────────────────────────────────────────

    def _load(self, mindset: str, lang: str) -> dict:
        """Lädt mindset/lang.json — nur einmal, dann gecacht. Gibt leeres Dict bei Fehler."""
        key = (mindset, lang)
        if key in self._cache:
            return self._cache[key]

        json_path = _TERMINOLOGY_DIR / mindset / f"{lang}.json"
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            self._cache[key] = data
            return data
        except FileNotFoundError:
            self._cache[key] = {}
            return {}
        except Exception as e:
            print(f"  [TermEngine] Ladefehler {json_path}: {e}")
            self._cache[key] = {}
            return {}

    # ── check ─────────────────────────────────────────────────────────────────

    def check(self, src_lang: str, tgt_lang: str, mindset: str) -> bool:
        """
        Prüft ob Quell- und Zielsprache für das Mindset verfügbar sind.
        Gibt True zurück wenn Engine aktiv, False wenn Fallback (Engine deaktiviert).
        """
        src = self._load(mindset, src_lang.lower())
        tgt = self._load(mindset, tgt_lang.lower())
        return bool(src) and bool(tgt)

    # ── status ────────────────────────────────────────────────────────────────

    def status(self, src_lang: str, tgt_lang: str, mindset: str) -> dict:
        """
        Für den /terminology/status Endpoint und den UI-Indikator.
        Returns:
          {
            "active": bool,
            "src_available": bool,
            "tgt_available": bool,
            "mindset": str,
            "src_lang": str,
            "tgt_lang": str,
            "src_terms": int,
            "tgt_terms": int,
          }
        """
        sl = src_lang.lower()
        tl = tgt_lang.lower()
        src_data = self._load(mindset, sl)
        tgt_data = self._load(mindset, tl)
        src_ok = bool(src_data)
        tgt_ok = bool(tgt_data)
        return {
            "active":        src_ok and tgt_ok,
            "src_available": src_ok,
            "tgt_available": tgt_ok,
            "mindset":       mindset,
            "src_lang":      src_lang.upper(),
            "tgt_lang":      tgt_lang.upper(),
            "src_terms":     len(src_data),
            "tgt_terms":     len(tgt_data),
        }

    # ── protect ───────────────────────────────────────────────────────────────

    def protect(
        self,
        text: str,
        src_lang: str = "de",
        mindset: str  = "general",
    ) -> tuple[str, dict]:
        """
        Ersetzt Quellsprach-Terme durch Codes.

        Returns:
            (protected_text, code_map)
            code_map: {"§Txxxxxxxx§": {"src": "Betriebssystem", "matched": "Betriebssystems"}}
        """
        sl = src_lang.lower()
        src_data = self._load(mindset, sl)
        if not src_data:
            return text, {}

        # Invert: term_lower -> code  (für Regex-Matching)
        term_to_code: dict[str, str] = {
            term.lower(): code for code, term in src_data.items()
        }
        # Längste Terme zuerst -> kein Partial-Match
        sorted_terms = sorted(term_to_code.keys(), key=len, reverse=True)

        code_map: dict[str, dict] = {}
        result = text

        for term_lower in sorted_terms:
            code = term_to_code[term_lower]
            original_term = src_data[code]  # Originalschreibweise

            base = re.escape(original_term)
            # \b vor dem Term verhindert Matches mitten in Wörtern
            # (z.B. "REST" in "underestimated", "NAL" in "external")
            # Negativer Lookahead statt \b nach dem Term — Flexionsendungen
            # (-e, -s, -es, -en, -n) werden direkt angehängt
            flexions = [base, base+r"e", base+r"s", base+r"es", base+r"en", base+r"n"]
            pattern = re.compile(
                r"\b(?:" + "|".join(flexions) + r")(?![a-zA-ZäöüÄÖÜ])",
                re.IGNORECASE,
            )

            def replacer(m, _code=code, _term=original_term):
                if _CODE_PATTERN.search(m.group(0)):
                    return m.group(0)
                code_map[_code] = {"src": _term, "matched": m.group(0)}
                return _code

            result = pattern.sub(replacer, result)

        return result, code_map

    # ── restore ───────────────────────────────────────────────────────────────

    def restore(
        self,
        text: str,
        tgt_lang: str = "en",
        code_map: dict = None,
        mindset: str   = "general",
    ) -> str:
        """
        Ersetzt Codes durch Zielsprach-Terme.
        Schlägt den Zielterm zur Laufzeit in tgt_lang.json nach.
        """
        if not code_map:
            return text

        tl = tgt_lang.lower()
        tgt_data = self._load(mindset, tl)

        result = text
        for code in code_map:
            tgt_term = tgt_data.get(code)
            if tgt_term:
                result = result.replace(code, tgt_term)

        # Reparatur beschädigter Codes (Leerzeichen, Großschreibung)
        result = _repair(result, tgt_data)
        return result

    # ── verify ────────────────────────────────────────────────────────────────

    def verify(self, protected: str, restored: str, code_map: dict) -> list[str]:
        """Gibt Warnmeldungen zurück — leer wenn alles ok."""
        issues = []
        for code in _CODE_PATTERN.findall(restored):
            if code in code_map:
                issues.append(f"Code nicht ersetzt: {code} (src: '{code_map[code]['src']}')")
        for code, info in code_map.items():
            if code in protected and code not in restored:
                issues.append(f"Code verloren: {code} ('{info['src']}')")
        return issues


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _repair(text: str, tgt_data: dict) -> str:
    """Repariert § T1a2b3c4d §  (Leerzeichen) und ähnliche LLM-Beschädigungen."""
    loose = re.compile(r"§\s*T([0-9a-f]{8})\s*§", re.IGNORECASE)
    def normalize(m):
        canonical = f"§T{m.group(1).lower()}§"
        return tgt_data.get(canonical, m.group(0))
    return loose.sub(normalize, text)


# ── Singleton ─────────────────────────────────────────────────────────────────

term_engine = TermEngine()

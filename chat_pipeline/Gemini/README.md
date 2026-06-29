# gemini_pipeline

Extraktion, Sortierung und Zusammenfassung von Gemini-Chatverläufen.
Gebaut im Kontext des Projekts **Garmin Local Archive** — funktioniert aber
für jeden Gemini-Nutzer der seine Chats lokal archivieren will.

---

## Pipeline-Übersicht

```
Gemini (Browser)
        │
        ▼
[Chrome Extension]         — amazingpaddy/ai-chat-exporter (unpacked, lokal)
        │
        ▼
[start_gla_export.bat]     — Chrome mit Debug-Port starten + Script starten
        │
        ▼
[gemini_exporter_gla.py]   — Playwright-Automation: Chats exportieren
        │
        ▼
gemini_gla_export/          — Rohe MD-Dateien (ungefiltert)
        │
        ▼
[sort_gemini_chats.py]      — Chronologische Sortierung + Dedup
        │
        ▼
gemini_sorted/              — Nummerierte MD-Dateien (gemini_001_*.md …)
        │
        ▼
[summarize_gemini_chats.py] — Ollama Map-Reduce Summarizer
        │
        ▼
chat_summaries_gemini.md    — Navigierbare Zusammenfassung aller Chats
```

---

## Voraussetzungen

### Software

| Tool | Version | Zweck |
|------|---------|-------|
| Python | 3.11+ | Alle Scripts |
| Chrome | aktuell | Export via Playwright |
| Ollama | aktuell | Lokale LLM-Inferenz |

### Chrome Extension — amazingpaddy/ai-chat-exporter

Die Extension wird als **unpacked** geladen — kein Chrome Web Store,
volle Kontrolle über den installierten Code.

**Installation:**
```
1. https://github.com/amazingpaddy/ai-chat-exporter klonen oder als ZIP herunterladen
   → Entpacken nach z.B. C:\Tools\ai-chat-exporter\

2. Chrome öffnen → chrome://extensions/
3. Oben rechts: "Entwicklermodus" einschalten
4. "Entpackte Erweiterung laden" klicken
5. Ordner C:\Tools\ai-chat-exporter\ auswählen
6. Extension erscheint in der Liste — fertig
```

> ⚠️ Die Extension bleibt nur für das Chrome-Profil unter `C:\ChromeDebug`
> aktiv (Debug-Instanz). Das normale Chrome-Profil ist nicht betroffen.

### Ollama-Modelle

```powershell
ollama pull qwen2.5:7b        # Chunk-Phase (schnell)
ollama pull deepseek-r1:14b   # Merge-Phase (Reasoning)
ollama pull phi4:14b          # Direkte Summaries kurzer Chats
```

Modelle sind in `summarize_gemini_chats.py` konfigurierbar — andere Modelle funktionieren ebenfalls.

### Python-Abhängigkeiten

```powershell
pip install playwright
playwright install chromium
```

---

## Verzeichnisstruktur

```
gemini_pipeline/
├── start_gla_export.bat          ← Schritt 0: Chrome starten + Exporter starten
├── gemini_exporter_gla.py        ← Schritt 1: Playwright-Export-Automation
├── sort_gemini_chats.py          ← Schritt 2: Chronologische Sortierung
├── summarize_gemini_chats.py     ← Schritt 3: Ollama Summarizer
│
├── gemini_gla_export/            ← [nicht im Repo] Rohexporte
├── gemini_sorted/                ← [nicht im Repo] Sortierte Chats
└── chat_summaries_gemini.md      ← [nicht im Repo] Finaler Output
```

---

## Schritt 0 — Chrome starten (`start_gla_export.bat`)

Doppelklick auf `start_gla_export.bat`. Das Script:

1. Beendet laufende Chrome-Instanzen
2. Startet Chrome mit Debug-Port 9222 und separatem Profil (`C:\ChromeDebug`)
3. Öffnet `gemini.google.com/app` direkt
4. Startet `gemini_exporter_gla.py` automatisch

**Beim ersten Start:**
- Chrome öffnet sich mit leerem `C:\ChromeDebug`-Profil
- Bei Google anmelden
- Extension manuell laden (siehe oben, einmalig)

**Chrome-Pfad anpassen** falls Chrome nicht unter
`C:\Program Files\Google\Chrome\Application\chrome.exe` liegt:
→ Zeile 10 in `start_gla_export.bat` editieren.

---

## Schritt 1 — Export-Automation (`gemini_exporter_gla.py`)

Das Script verbindet sich via Playwright CDP zum laufenden Chrome,
scrollt die Sidebar durch, sammelt alle Chat-URLs und exportiert
gefilterte Chats als MD-Dateien.

### Ablauf
```
1. CDP-Verbindung zu Chrome (Port 9222)
2. Sidebar scrollen → alle Chat-URLs sammeln
3. Jeden Chat öffnen → Titel gegen Keyword-Filter prüfen
4. Bei Treffer: Extension-Button "Export Chat" klicken (2× — Popup + Bestätigung)
5. MD-Datei landet im Download-Ordner → wird nach gemini_gla_export/ verschoben
```

### Keyword-Filter anpassen

Der Filter in `gemini_exporter_gla.py` ist auf GLA-relevante Begriffe
ausgelegt. Für andere Projekte einfach `GLA_KEYWORDS` (ab Zeile 55) anpassen.

Ohne Filter alle Chats exportieren:
```powershell
python gemini_exporter_gla.py --no-filter
```

### Parameter

```powershell
python gemini_exporter_gla.py --output-dir ./meine_chats   # Anderer Output-Ordner
python gemini_exporter_gla.py --no-filter                  # Alle Chats exportieren
python gemini_exporter_gla.py --cdp-port 9223              # Anderer Debug-Port
python gemini_exporter_gla.py --no-skip                    # Bereits vorhandene neu exportieren
```

**Output:** MD-Dateien mit Format `Chatname_YYYYMMDD_HHMMSS.md`

---

## Schritt 2 — Sortierung (`sort_gemini_chats.py`)

Sortiert die exportierten MDs chronologisch anhand des Export-Timestamps
im Dateinamen. Gemini exportiert Chats von oben nach unten
(neueste zuerst) — Umkehrung ergibt chronologische Reihenfolge.

### Ausführen

```powershell
# Dry-Run — nur Vorschau, nichts kopieren
python sort_gemini_chats.py --dry-run

# Produktiv
python sort_gemini_chats.py

# Andere Pfade
python sort_gemini_chats.py --source ./gemini_gla_export --dest ./gemini_sorted
```

### Duplikat-Behandlung

Die Extension erzeugt bei manchen Chats zwei Dateien mit leicht
unterschiedlichem Timestamp-Format. Das Script erkennt Duplikate
über normalisierten Titel-Vergleich und behält jeweils den älteren.

**Output:** `gemini_001_Titel.md` … `gemini_NNN_Titel.md`

---

## Schritt 3 — Summarizer (`summarize_gemini_chats.py`)

Fasst jeden Chat via Ollama zusammen. Kurze Chats direkt,
lange Chats per Map-Reduce (Chunk → Teil-Summary → Merge).

### Voraussetzung

```powershell
ollama serve   # in separatem Fenster laufen lassen
```

### Ausführen

```powershell
python summarize_gemini_chats.py
```

Resume-safe: bei Abbruch einfach neu starten —
bereits verarbeitete Chats werden übersprungen.

### Konfiguration (in `summarize_gemini_chats.py`)

```python
CHUNK_MODEL  = "qwen2.5:7b"      # Chunk-Phase — schnell
MERGE_MODEL  = "deepseek-r1:14b" # Merge — stärkeres Modell
DIRECT_MODEL = "phi4:14b"        # Kurze Chats direkt

CHUNK_SIZE    = 8000   # Zeichen pro Chunk
CHUNK_OVERLAP = 400    # Überlappung zwischen Chunks
```

### Verarbeitungslogik

```
Chat ≤ 8.000 Zeichen   → DIRECT_MODEL, 1 Aufruf

Chat > 8.000 Zeichen   → Map-Reduce:
  Chunk 1 → CHUNK_MODEL → Teil-Summary 1
  Chunk 2 → CHUNK_MODEL → Teil-Summary 2
  ...
  Alle Teil-Summaries → MERGE_MODEL → Gesamt-Summary
```

### Zeitschätzung

| Chat-Größe | Chunks | Dauer (ca.) |
|-----------|--------|-------------|
| < 8 KB | — (direkt) | 2-3 min |
| ~50 KB | ~6 Chunks | 15-20 min |
| ~200 KB | ~25 Chunks | 60-90 min |

**VRAM-Hinweis:** `qwen2.5:7b` + `deepseek-r1:14b` passen nicht gleichzeitig
in 16 GB VRAM. Ollama swapped automatisch — das ist OK, da Chunk- und
Merge-Phase sowieso sequenziell laufen.

---

## Hinweise

**Keyword-Filter:** `GLA_KEYWORDS` in `gemini_exporter_gla.py` ist projektspezifisch.
Für andere Kontexte anpassen oder mit `--no-filter` deaktivieren.

**Modellwechsel:** Der erste Wechsel zwischen CHUNK_MODEL und MERGE_MODEL
kostet ~30-60 Sekunden Ladezeit — das ist normal.

**Sehr lange Chats:** Einzelne Chats mit 200+ KB sind möglich (mehrere Monate
Entwicklung in einem Verlauf). Map-Reduce verarbeitet diese zuverlässig,
braucht aber entsprechend Zeit.

---

*Pipeline erstellt: Mai 2026*
*Kontext: Garmin Local Archive — Story-Dokumentation*
*Extension: [amazingpaddy/ai-chat-exporter](https://github.com/amazingpaddy/ai-chat-exporter)*

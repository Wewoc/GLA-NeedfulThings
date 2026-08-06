# GLA-Tools / translator — Reference

Architecture, configuration, endpoints, and constants.
Consult alongside `README_translator.md` and `MAINTENANCE_translator.md`.

---

## File roles

### Python

| File | Role | Owner |
|---|---|---|
| `app.py` | FastAPI-Setup, alle Endpoints, Start-Block | Endpoints, Pydantic Models, uvicorn |
| `core/config.py` | Konfiguration, Konstanten, RuntimeState, Mindsets | einziger Ort für cfg-Zugriff und state |
| `core/chunking.py` | `split_chunks()`, `lang_name()`, `LANG_NAMES` | reine Text-/Sprach-Helfer, kein IO |
| `core/logging.py` | `perf.csv`, `lara_usage.json` | ausschließlich Logging und Zähler |
| `core/link_guard.py` | `protect()`, `restore()` — URL/Pfad/Markdown-Link-Schutz vor der Übersetzungspipeline | eigener Placeholder-Namespace `§Lxxxxxxxx§`, unabhängig von TermEngine |
| `engines/ollama.py` | `translate_ollama()`, `run_s2()`, `detect_mindset()`, `write_chunk_perf_log()` | alles was Ollama direkt aufruft |
| `engines/external.py` | `translate_deepl()`, `translate_libretranslate()`, `translate_mymemory()`, `translate_lara()` | alle externen API-Engines |

### JavaScript

| File | Role | Owner |
|---|---|---|
| `static/app.js` | Globaler State, `init()`, `setupInput()` | einziger Ort für State-Deklaration |
| `static/translate.js` | `translate()`, Chunking-Loop, Abort, Final-Pass-Wrapper | gesamte Übersetzungslogik |
| `static/engines.js` | `checkOllama()`, `checkLibre()`, `checkTerminology()`, `updateVramStatus()`, `setModel()`, `stopLibre()`, `updateLaraUsage()` | Engine-Status und Modell-Verwaltung |
| `static/ui.js` | `showToast()`, `clearAll()`, `copyTranslation()`, `exportMD()`, `openExportDir()`, `updateCharCount()`, `swapLangs()`, `updatePipelineGray()` | reine UI-Hilfsfunktionen |

### Sonstige

| File | Role |
|---|---|
| `index.html` | UI-Struktur — statisches Markup, Button-IDs, Layout, Script-Tags |
| `style.css` | Visuelles Styling |
| `config.yaml` | Single source of truth für alle Runtime-Einstellungen |
| `.env` | API-Credentials — nie in `config.yaml` |
| `lara_usage.json` | Lara-Tageszähler — auto-generiert, Owner: `core/logging.py` |
| `pipeline/mindsets.json` | Mindset-Definitionen — manuell bearbeitet, geladen von `core/config.py` |
| `libretranslate_langs.txt` | Sprachcodes für Docker-Container — geschrieben von Setup-Script |
| `test/test.py` | Quality test runner — liest `test_config.csv`, ruft `/translate/chunk` direkt an |
| `test/test.bat` | Wrapper — prüft Server-Erreichbarkeit, startet `test.py` |
| `test/test_config.csv` | Testkonfiguration: quelle, S1, S2, target, mindset, source |
| `test/source/` | Quelltexte für Testläufe — manuell befüllen |
| `test/results/` | Ausgabe — eine MD-Datei pro Run, auto-generiert |
| `terminology/` | Terminologielisten pro Mindset — committed to repo |
| `terminology/{mindset}/de.json` | DE-Terme mit Hash-Codes |
| `terminology/{mindset}/en.json` | EN-Terme mit Hash-Codes |
| `Terminologie-Engine/` | Build-Scripts — lokal, nicht im Repo |
| `Terminologie-Engine/build_terminology.py` | Step 1: Listen aus TBX/CSV bauen |
| `Terminologie-Engine/filter_terminology.py` | Step 2: Listen filtern und validieren |
| `Terminologie-Engine/apply_checkpoint.py` | Recovery: Checkpoint manuell anwenden |
| `Terminologie-Engine/validate.bat` | Shortcut für Pass 3 Validierung |

---

## Import-Hierarchie (Python)

```
core/config.py          ← Basis, importiert niemanden aus diesem Projekt
    ↑
core/chunking.py        ← importiert core.config
core/logging.py         ← importiert core.config
core/link_guard.py      ← importiert nichts aus diesem Projekt (standalone, nur stdlib)
    ↑
engines/ollama.py       ← importiert core.config, core.chunking, core.logging, terminology.terminology
engines/external.py     ← importiert core.config, core.logging
    ↑
app.py                  ← importiert alle obigen + core.link_guard + terminology.terminology
    ↑
terminology/terminology.py  ← importiert nichts aus diesem Projekt (standalone)
```

`core/config.py` darf niemals etwas aus `core/logging.py`, `core/chunking.py`, `core/link_guard.py` oder den Engines importieren — das würde einen Circular Import erzeugen.

---

## config.yaml — field reference

| Key | Type | Default | Purpose |
|---|---|---|---|
| `ollama_url` | str | `http://localhost:11434` | Ollama API base URL |
| `ollama_model` | str | `mistral` | Default model — overridable at runtime via UI dropdown |
| `ollama_chunk_size` | int | `6000` | Max chars per chunk for Ollama |
| `deepl_free_tier` | bool | `true` | `true` = api-free.deepl.com, `false` = api.deepl.com |
| `libretranslate_url` | str | `http://localhost:5000` | LibreTranslate API base URL |
| `libretranslate_api_key` | str | `""` | Empty = no auth (self-hosted default) |
| `libretranslate_enabled` | bool | `false` | Master switch — also controls Docker startup in `translator.bat/.sh` |
| `mymemory_enabled` | bool | `true` | Enable MyMemory engine |
| `mymemory_email` | str | `""` | Optional — increases MyMemory daily limit |
| `lara_enabled` | bool | `false` | Enable Lara engine (credentials still required in `.env`) |
| `lara_daily_limit` | int | `5000` | Local daily char limit for Lara — tracked in `lara_usage.json` |
| `default_source_lang` | str | `DE` | Pre-selected source language on load |
| `default_target_lang` | str | `EN` | Pre-selected target language on load |
| `debounce_seconds` | float | `1.5` | Typing pause before auto-translation triggers |
| `default_mode` | str | `debounce` | Startup translation mode: `debounce` / `sentence` / `manual` |
| `default_mindset` | str | `general` | Startup mindset — reset to this after every translation |
| `pipeline_s2_model` | str | `""` | S2 quality/terminology pass — empty = disabled (e.g. `qwen2.5:7b`) |
| `pipeline_mindset_model` | str | `""` | Model for `/mindset/detect` — empty = falls back to `state.active_model` (S1) |
| `languages` | dict | DE/EN/… | Display name → API code mapping for all dropdowns |
| `export_dir` | str | `exports` | Output folder for MD exports — auto-created |
| `filename_prefix` | str | `translation` | Prefix for exported filenames |
| `log_dir` | str | `logs` | Output folder for performance log — auto-created |
| `log_csv_separator` | str | `";"` | CSV separator for `perf.csv` — `";"` for Excel/DE, `","` for EN |
| `host` | str | `127.0.0.1` | Server bind address |
| `port` | int | `8000` | Server port |
| `auto_open_browser` | bool | `true` | Open browser automatically on startup |

**.env keys:**

| Key | Used by |
|---|---|
| `DEEPL_API_KEY` | `engines/external.py` → `translate_deepl()` |
| `LARA_ACCESS_KEY_ID` | `engines/external.py` → `translate_lara()` |
| `LARA_ACCESS_KEY_SECRET` | `engines/external.py` → `translate_lara()` |

---

## Chunk limits

| Engine | Limit | Defined in |
|---|---|---|
| Ollama | `ollama_chunk_size` aus `config.yaml` (default 6000) | `core/config.py` als `OLLAMA_CHUNK_SIZE` |
| DeepL | 4900 chars | `core/config.py` als `DEEPL_CHUNK_SIZE` (fest) |
| MyMemory | 480 chars | `core/config.py` als `MYMEMORY_CHUNK_SIZE` (fest) |
| LibreTranslate | kein Chunking | single request, no loop |
| Lara | kein Chunking | single request, no loop |

Chunking-Logik liegt vollständig im Frontend (`translate.js` — `translate()` Funktion).
Das Backend `/translate/chunk` verarbeitet einen Chunk pro Request — kein Loop im Backend.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Serves `index.html` |
| GET | `/config` | Returns runtime config for frontend init |
| POST | `/translate` | Single-shot translation (no chunking) — accepts `s2_model`, runs S2 pass when set |
| POST | `/translate/chunk` | Single chunk translation — called repeatedly by frontend loop |
| POST | `/translate/chunks/prepare` | Splits text into chunks, returns list + total count |
| GET | `/ollama/status` | Ollama reachability + available models |
| GET | `/ollama/vram` | Loaded models + VRAM usage — optional GPU total via `nvidia-smi` |
| POST | `/ollama/unload` | Unload all loaded models from VRAM via `keep_alive: 0` |
| POST | `/ollama/set_model` | Set `state.active_model` at runtime |
| GET | `/terminology/status` | Terminology engine availability for current language pair + mindset |
| GET | `/lara/usage` | Today's Lara char usage + remaining |
| GET | `/libretranslate/status` | LibreTranslate online check + language pair availability |
| POST | `/libretranslate/stop` | Stop Docker container from UI |
| POST | `/mindset/detect` | Auto-detect mindset via `engines/ollama.py` → `detect_mindset()` |
| GET | `/mindsets` | Returns all available mindsets with label and rst_mode |
| POST | `/export` | Write source + translation to MD files in `export_dir` |
| GET | `/export/open` | Open export folder in OS file explorer |

---

## Language code conventions

- Config keys use uppercase codes: `DE`, `EN`, `FR` …
- LibreTranslate API expects lowercase: `de`, `en`, `fr` …
- MyMemory API expects uppercase pairs: `DE|EN` …
- DeepL API expects uppercase: `DE`, `EN` …
- Conversion handled per engine inside each `translate_*()` function in `engines/external.py`

---

## Runtime model override

`state.active_model` ist ein Attribut von `RuntimeState` in `core/config.py`.
`/ollama/set_model` schreibt es — Änderung gilt sofort für den nächsten Übersetzungs-Request.
Persistiert nicht über Server-Restarts — Default aus `config.yaml` wird beim Start gesetzt.

```python
# core/config.py
class RuntimeState:
    active_model: str = OLLAMA_MODEL

state = RuntimeState()
```

---

## Mindset model — request-scoped, not stateful

Anders als S1 (`state.active_model`, serverseitig gehalten) folgt das Mindset-Detection-Modell
dem S2-Muster: kein State, kein Setter-Endpoint. Das UI-Dropdown `mindsetModelSelect` schickt
den gewählten Modellnamen bei jedem `/mindset/detect`-Call im Request-Body mit
(`DetectMindsetRequest.mindset_model`).

Prioritätskette in `engines/ollama.py` → `detect_mindset(text, model)`:

model (Request, aus Dropdown) → MINDSET_MODEL (config.yaml) → state.active_model (S1-Fallback)


Grund für Request-scoped statt State: `detect_mindset()` läuft nur einmalig pro Session
(Debounce-Handler, `if (!mindsetDetected)`), nicht durchgehend wie S1 — ein eigener State hätte
nur Race-Condition-Risiko gegenüber S1-Modellwechseln eingeführt, ohne Nutzen.

---

## Mindset model — request-scoped, not stateful

Anders als S1 (`state.active_model`, serverseitig gehalten) folgt das Mindset-Detection-Modell
dem S2-Muster: kein State, kein Setter-Endpoint. Das UI-Dropdown `mindsetModelSelect` schickt
den gewählten Modellnamen bei jedem `/mindset/detect`-Call im Request-Body mit
(`DetectMindsetRequest.mindset_model`).

Prioritätskette in `engines/ollama.py` → `detect_mindset(text, model)`:

---

## Lara daily counter

Tracked locally in `lara_usage.json`:
```json
{"date": "2025-01-15", "chars": 1240}
```
Resets automatically at midnight (date check on every read).
Written by `add_lara_usage()` in `core/logging.py` after every successful Lara translation.
The UI button shows remaining chars and disables itself at limit.

---

## Link/path protection — link_guard.py

`core/link_guard.py` protects URLs, markdown links, and file paths from being altered by
the translation pipeline (S1 could otherwise spell out protocol prefixes like `https://`,
or mangle path separators).

```python
from core import link_guard

link_result = link_guard.protect(text)      # -> LinkGuardResult(protected_text, mapping)
restored     = link_guard.restore(text, link_result.mapping)
```

Placeholder format: `§Lxxxxxxxx§` (8-digit numeric ID) — independent namespace from
TermEngine's `§Txxxxxxxx§`, no collision risk.

**Detected patterns** (in this order): markdown links `[text](url)`, bare URLs, Windows/UNC
paths, backtick-quoted codespans containing a path separator (`` `src/docs/x.md` ``).
Anchor-text heuristic decides whether markdown link text itself is protected (filename-like)
or left translatable (prose).

**Pipeline position:** wraps *outside* TermEngine, spanning the whole S1+S2 pipeline — not
just S1. See `MAINTENANCE_translator.md` for the exact ordering rationale.

Intentionally out of scope: bare prose paths without backticks or markdown syntax (e.g.
"liegt unter src/docs/") — left untouched, no regex guessing.

---

## Globaler JS-State

Alle sechs State-Variablen leben ausschließlich in `static/app.js`:

| Variable | Typ | Schreiber |
|---|---|---|
| `config` | object | `init()` (app.js), `setModel()` (engines.js) |
| `debounceTimer` | number\|null | `setupInput()` (app.js) |
| `currentTranslation` | string | `translate()` (translate.js), `clearAll()` (ui.js) |
| `isTranslating` | bool | `translate()` (translate.js) |
| `abortController` | AbortController\|null | `translate()` (translate.js) |
| `mindsetDetected` | bool | `translate()` (translate.js), `clearAll()` (ui.js) — gesetzt auf `true` am Anfang von `translate()`, zurückgesetzt auf `false` im `finally`-Block danach; läuft also bei jedem Übersetzungsdurchlauf neu, nicht mehr pro Tipp-Session |

`setupInput()` (app.js) schreibt `mindsetDetected` **nicht mehr** — Mindset-Detect ist bewusst
aus dem `input`-Listener entfernt und sitzt stattdessen als erster Schritt in `translate()`
selbst, damit er einheitlich bei allen drei Trigger-Wegen (Button, Enter, Debounce-Timeout)
feuert, statt an `mode === 'debounce'` gekoppelt zu sein.
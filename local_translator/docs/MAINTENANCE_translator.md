# GLA-Tools / translator — Maintenance

Known pitfalls, debugging history, and non-obvious architecture decisions.
Consult before touching any file. See `REFERENCE_translator.md` for file roles and ownership.

---

## HTML onclick attributes override JS property assignment

**Symptom:** Button text changes (`▶ Translate` → `■ Stop`) but clicking does nothing — the old handler fires.

**Cause:** When a button has an `onclick` attribute in HTML, assigning `btn.onclick = fn` in JS has no effect. The HTML attribute takes precedence over the JS property.

**Wrong approach:**
```js
// This does NOT work if the button has onclick="..." in HTML
translateBtn.onclick = stopTranslation;
```

**Correct approach:** Use a stable dispatcher function as the `onclick` target in HTML, and let that function check state:

`index.html`:
```html
<button id="translateBtn" onclick="handleTranslateBtn()">▶ Translate</button>
```

`translate.js`:
```js
function handleTranslateBtn() {
  if (isTranslating) stopTranslation();
  else translateNow();
}
```

Text still changes via `btn.textContent` — only the handler stays fixed.

---

## Variable scope in try/catch blocks

**Symptom:** `ReferenceError: results is not defined` in the `catch` block after aborting a chunked translation.

**Cause:** `const results = []` was declared inside the `if (needsChunking)` block — not visible in the outer `catch`.

**Fix:** Declare `results` at the top of `translate()`, before the `try` block:

```js
async function translate(engine = 'ollama') {
  // ...
  const results = [];   // ← here, not inside if (needsChunking)

  try {
    if (needsChunking) {
      // results is now accessible here
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      out.textContent = results.length   // ← and accessible here
        ? results.join('\n\n') + '\n\n[aborted]'
        : '[aborted]';
    }
  }
}
```

---

## Killswitch — AbortController pattern

The chunk loop runs entirely in the frontend (`translate.js`). The backend handles one chunk per request — no loop, no state.

Abort is implemented via `AbortController` attached to each `fetch` call in the chunk loop:

```js
abortController = new AbortController();

const res = await fetch('/translate/chunk', {
  signal: abortController.signal,
  // ...
});
```

`stopTranslation()` calls `abortController.abort()` — this throws an `AbortError` on the next pending fetch, breaking the loop.

**Behavior on abort:**
- The currently running chunk request completes normally (Ollama is not interrupted)
- The abort fires when the next fetch is attempted
- Completed chunks are preserved in `results` and shown in the output
- A `[aborted]` marker is appended

**Note:** `AbortController` only interrupts fetches that haven't started yet, or are waiting for a response. A fetch that is already receiving data will complete.

---

## Static files path

`app.py` mounts `/static` to the `static/` subfolder:
```python
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
```

`style.css`, `app.js`, `translate.js`, `engines.js`, `ui.js` must be in `translator/static/`.
`index.html` is served directly from `translator/` root via the `/` endpoint.

---

## Script-Tag-Reihenfolge in index.html

Die vier JS-Dateien müssen in dieser Reihenfolge geladen werden:

```html
<script src="/static/ui.js"></script>
<script src="/static/engines.js"></script>
<script src="/static/translate.js"></script>
<script src="/static/app.js"></script>
```

**Begründung:** Kein Bundler — alle Dateien teilen denselben globalen Scope.
- `ui.js` zuerst: `showToast()` wird von engines.js und translate.js aufgerufen
- `engines.js` vor `translate.js`: `updateLaraUsage()` und `updateVramStatus()` werden in `translate()` aufgerufen
- `app.js` zuletzt: `init()` ruft Funktionen aus allen anderen Modulen auf — globaler State muss zuerst deklariert sein

Funktionen die über `onclick`/`onchange` in `index.html` aufgerufen werden müssen global verfügbar sein. Das ist durch die gemeinsame globale Scope sichergestellt, solange die Script-Reihenfolge stimmt.

---

## Globaler JS-State — Heimat und Zugriff

Alle sechs State-Variablen leben in `app.js`:

```js
let config = {};
let debounceTimer = null;
let currentTranslation = '';
let isTranslating = false;
let abortController = null;
let mindsetDetected = false;
```

Da kein Bundler verwendet wird, sind diese Variablen im globalen Scope und für alle anderen Script-Dateien direkt lesbar und schreibbar. Neue Variablen die sich zur Laufzeit ändern können gehören ausschließlich hier hin.

---

## LibreTranslate Docker container lifecycle

**Never delete the `localtranslate-libre` container in Docker Desktop.**
Deleting it removes downloaded language models — `setup_libretranslate.bat/.sh` must be re-run to re-download (can be several GB).

Only use **Stop** — either from Docker Desktop or the **■ Stop** button in the UI status bar.

The `translator.bat/.sh` start script calls `docker start localtranslate-libre` on each launch — this only works if the container exists (stopped state). If it doesn't exist, it runs `docker run` to create it fresh.

---

## Chunk table must not be overwritten after chunking

After the chunk loop completes, `tgtOutput` contains a live `chunk-table`. Calling `out.textContent = currentTranslation` after the loop destroys the table. The guard `if (!needsChunking)` before that line is intentional — do not remove it.

---

## engineBadge uses innerHTML during chunking

During the chunk loop, `engineBadge` is set via `innerHTML` to include the `badge-pulse` span:
```js
// Chunk start — counter only
engineBadge.innerHTML = `translating… (${i + 1} / ${total}) <span class="badge-pulse"></span>`;
// After chunk completes — checkmark appended
engineBadge.innerHTML = `translating… (${i + 1} / ${total} ✓) <span class="badge-pulse"></span>`;
```
After the loop, it switches back to `textContent`. Do not change the in-loop assignments to `textContent` — the pulse span would disappear. S1/S2 labels are not shown in the badge — models are visible in the statusbar dropdowns.

---

## Mindset dropdown resets after every translation

The mindset dropdown is reset to `config.default_mindset` in the `finally` block of `translate()` in `translate.js`. This is intentional — every new text gets a fresh auto-detection pass. Do not move the reset elsewhere or make it conditional.

The dropdown is also disabled during translation (`mindsetSelect.disabled = true`) and re-enabled in `finally`. Both lines are in the same block — keep them together.

---

## Chrome browser launch strips quotes from path

`translator.bat` sets `LOCALTRANSLATE_BROWSER` with quoted paths (e.g. `"C:\Program Files\..."`). When `app.py` reads this via `os.environ.get()`, the quotes are part of the string — `os.path.exists()` returns `False`. Always strip quotes before the exists check:
```python
chrome = os.environ.get("LOCALTRANSLATE_BROWSER", "").strip('"')
```

---

## S2 silent skip — texts under chunk limit (< 6000 chars)

**Symptom:** S2 is set in the UI, GPU shows a second load spike but result appears immediately — `model_s2` empty and `time_s2 = 0` in perf.csv.

**Root cause:** Two separate issues, both required:

1. `/translate` endpoint (used for texts ≤ chunk limit) never called `run_s2()` — only `/translate/chunk` had S2 wired up.
2. `run_s2()` connect timeout was 10s — too short for initial model load. Silent `except Exception: return text` fallback fired before S2 could respond. GPU kept running in the background.

**Fix:**
- `TranslateRequest` extended with `s2_model: str = ""`
- `/translate` endpoint: `import time`, S1/S2 timing, `run_s2()` call, `write_chunk_perf_log()`
- `translate.js`: non-chunking fetch sends `s2_model`; `/ollama/unload` called before fetch
- `run_s2()` connect timeout: 10s → 60s

**Watch out:** when adding logic to one path, always check the other — `/translate` and `/translate/chunk` share the same Ollama pipeline but are separate code paths with no shared helper. Silent fallbacks in `run_s2()` mask timeout errors completely — check perf.csv when S2 output looks unchanged.

---

## S2 pipeline — VRAM and language drift

**VRAM:** Ollama keeps S1 loaded for 5 minutes after use. When S2 starts, both models occupy VRAM simultaneously. To prevent overflow, `run_s2()` in `engines/ollama.py` sends a `keep_alive: 0` request to unload S1 before loading S2:
```python
await client.post(f"{OLLAMA_URL}/api/generate", json={
    "model": state.active_model, "keep_alive": 0, "prompt": "", "stream": False
})
```

**Language drift:** After S2 completes, a drift check compares the non-ASCII ratio of input vs. output (code blocks stripped). If output has significantly more non-ASCII than input, S2 has translated back into the source language — S1 result is used as fallback:
```python
if output_non_ascii > input_non_ascii + 0.15:
    return text  # fallback to S1
```

**Known limitation:** If the input already contains non-ASCII content (e.g. a license header in a code block), the threshold may not trigger even when S2 has partially back-translated. The `_strip_code_blocks()` helper in `engines/ollama.py` mitigates this but does not fully solve it.

**S3 removed:** S3 (formatting pass) was tested with `qwen2.5:3b` and `mistral-nemo:latest` — both produced structural damage (prompt text in output, duplicate sections, unwanted reformatting). S3 has been removed. The architecture can be reintroduced if a suitable model becomes available.

**Tested S2 models:**

| Model | Result |
|---|---|
| `qwen2.5:3b` | deletes content, ignores instructions |
| `qwen2.5:7b` | ✓ best result — occasional back-translation on last chunk |
| `dolphin3:latest` | back-translates last chunk + style degradation |
| `mistral-nemo:latest` | semantic expansion — rewrites content, invents acronyms (e.g. "LTPs") |

Recommended S2: `qwen2.5:7b`. Default: disabled.

**Known S2 failure mode — semantic expansion:**
Beyond language drift (back-translating to source language), S2 models can produce *semantic expansion* — rewriting content while staying in the target language. Example: `mistral-nemo` turned "Lokale KI-Modelle" into "Local text processing systems (LTPs)" without any drift signal. The non-ASCII drift check does not catch this. No automated fix exists — evaluate S2 output manually when quality matters.

**Translation pipeline order:**

---

## Model unloading — before and after translation

All loaded Ollama models are unloaded at two points:

1. **Before the first chunk** — `fetch('/ollama/unload')` is called in `translate.js` before the chunk table is built. Prevents VRAM overflow when switching models between runs.
2. **After translation completes** — called in the `finally` block of `translate()`, only when `engine === 'ollama'`. Followed immediately by `updateVramStatus()` so the statusbar updates to `GPU idle`.

Both calls use `.catch(() => {})` — unload failures are silent and never block translation.

The `/ollama/unload` endpoint in `app.py` reads all loaded models from `/api/ps`, then sends `keep_alive: 0` for each. Individual model failures are swallowed — the endpoint always returns `{ unloaded: [...] }`.

---

## Performance logging — perf.csv

After every Ollama chunk translation, one row is appended to `logs/perf.csv`. Fields: `timestamp`, `chunk_index`, `chunk_size`, `complexity`, `time_s1`, `time_s2`, `model_s1`, `model_s2`, `terms_protected`.

- File and header are auto-created on first write (`core/logging.py`)
- Timestamp format: `%Y-%m-%dT%H:%M:%S` — no microseconds, no decimal point
- Times are integers (full seconds, rounded) — avoids decimal separator issues in Excel
- Separator is configurable via `log_csv_separator` in `config.yaml` — default `";"` for Excel/DE compatibility
- Complexity derived from chunk size: `< 2000` = low, `< 4000` = medium, `≥ 4000` = high
- Only Ollama chunks are logged — DeepL, LibreTranslate, MyMemory, Lara write nothing
- Log failures are silent (`try/except pass`) — never block translation
- `model_s1` wird als expliziter Parameter an `_write_perf_log()` übergeben — `core/logging.py` hat keine Abhängigkeit auf `RuntimeState`
- `terms_protected` — Anzahl der durch die Terminologie-Engine ersetzten Fachbegriffe pro Chunk (0 wenn Engine inaktiv oder kein Sprachpaar verfügbar)

If the separator is changed after existing data was written, delete `perf.csv` — the header will be re-created with the new separator on the next run.

---

## Terminology engine — interaction with veto list

The mindset veto list (`mindsets.json`) and the terminology engine operate at different levels and do not conflict — but there is one edge case worth knowing.

**Normal case:** both mechanisms protect the same terms independently.
- Veto list: prompt-level hint — "Keep these terms untranslated: API, Backend."
- Term engine: replaces the term with a code *before* the LLM sees the text — Ollama never encounters the word at all. restore() puts the EN equivalent back after translation.

If a term appears in both the veto list and `de.json`, the term engine fires first. The veto hint in the prompt is then redundant but harmless.

**Edge case — diverging EN equivalents:** if the veto list implies a term should stay as-is (e.g. "Backend" → "Backend") but `de.json` maps it to a different form (e.g. "back-end"), the term engine wins — it runs before the prompt is built. In practice this is rare because veto list entries are typically EN terms already present in DE source text, which either have identical DE/EN entries in the terminology lists or are absent from them entirely.

**If a conflict causes problems:** remove the term from `de.json` for the affected mindset — the veto list will then handle it via prompt as before.

---

## link_guard — placeholder restore timing differs from TermEngine

`link_guard.restore()` runs **after S2**, not right after S1 like TermEngine's restore.
TermEngine restores early so S2 edits clean, readable EN text — but link_guard placeholders
must survive S2 too, otherwise S2 could reformat or "improve" an already-restored URL or
path. Keep this ordering if the pipeline is ever refactored:

```
link_guard.protect() → term_engine.protect() → S1
  → term_engine.restore() → S2 (optional) → link_guard.restore()
```

Two independent placeholder namespaces coexist in the protected text during S1/S2:
`§Lxxxxxxxx§` (link_guard) and `§Txxxxxxxx§` (TermEngine). No collision risk — different
prefix character, both are 8-digit numeric IDs.

**Applies to both `/translate` and `/translate/chunk`** — same caveat as the S2 silent-skip
case above: these are separate code paths with no shared helper. When touching pipeline
order in one, check the other.

**Grey zone, deliberately unhandled:** bare prose paths without backticks or markdown
syntax (e.g. "liegt unter src/docs/") are not protected — regex-guessing here risked false
positives on ordinary text like "und/oder". If this turns out to matter in practice, an
LLM batch-classification pass for the remaining grey zone was discussed as a future option
— not implemented.

---

## Quality test runner — test/test.py

`test.py` calls `/translate/chunk` directly — same endpoint as the UI chunking loop. This means term engine, S2 pass, and perf logging all fire exactly as in production.

**perf.csv filtering:** rows are filtered by timestamp range (run start → run end). If a run takes longer than expected and timestamps overlap with another concurrent run, rows from both runs will appear. Don't run tests in parallel.

**S2 in test mode:** `test.py` calls `/translate/chunk` with `s2_model` set — S2 runs server-side as part of the chunk request, same as in the UI. The S2 time shown in the result MD is wall-clock time for the full request, not isolated S2 time (perf.csv has the split).

**Source file size:** keep source files under the Ollama chunk limit (6 000 chars by default) — test.py sends the full file as a single chunk. If the file exceeds the limit, the server will still process it but context continuity is not guaranteed.

---

## RuntimeState — active_model

`_active_model` existiert nicht mehr als nackte Modul-Variable. Stattdessen:

```python
# core/config.py
class RuntimeState:
    active_model: str = OLLAMA_MODEL

state = RuntimeState()
```

Zugriff überall via `from core.config import state`, dann `state.active_model`.
Schreiben nur im `/ollama/set_model` Endpoint in `app.py`: `state.active_model = req.model`.
Kein `global` keyword mehr nötig.

---

## Pfade — PROJECT_ROOT

Alle Pfade in `core/config.py` basieren auf `PROJECT_ROOT`:

```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent
```

`__file__` zeigt auf `core/config.py` — `.parent.parent` navigiert zum Projektstamm.
Nie relative Pfade wie `Path(__file__).parent / "pipeline"` in Untermodulen verwenden — das würde auf den falschen Ordner zeigen.

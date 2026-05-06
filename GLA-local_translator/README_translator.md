# GLA - LocalTranslate

Local translation tool — part of the [Garmin Local Archive](https://github.com/Wewoc/Garmin_Local_Archive) ecosystem.
Ollama as primary engine, optional Final-Pass via DeepL, LibreTranslate, MyMemory or Lara Translate.
Two-column UI in the browser, synchronized scrolling, MD export of both texts.
Long texts are split into chunks automatically — progress shown live during translation.

---

## Prerequisites

- **Python 3.9+**
- **Ollama Desktop App** running locally
  - Recommended models: `mistral`, `llama3.1`, `phi3`, `gemma2`
  - Pull a model: `ollama pull mistral`
- **Docker Desktop** (only required for LibreTranslate)
- Optional Final-Pass engines — see configuration below

---

## Setup

1. Copy `.env.example` → `.env` and fill in your credentials
2. Adjust `config.yaml` (model, languages, engines)
3. Start Ollama Desktop App
4. Double-click `translator.bat` (Windows) or run `bash translator.sh` (Linux/Mac)
5. Browser opens automatically at `http://127.0.0.1:8000`

For LibreTranslate setup, see `README_libretranslate.md`.

---

## Startup — `translator.bat` / `translator.sh`

The start script handles everything in order:

1. Checks Python and installs dependencies if needed
2. If `libretranslate_enabled: true` in `config.yaml` — asks whether to start LibreTranslate (Docker)
3. If yes: checks Docker availability, starts the container
4. Checks if Ollama is reachable — prompts to retry or skip if not
5. Starts the LocalTranslate server

Docker is only touched if LibreTranslate is both enabled in the config **and** confirmed at startup.

---

## Credentials — `.env`

Sensitive API keys are stored in `.env`, not in `config.yaml`.

```env
DEEPL_API_KEY=

LARA_ACCESS_KEY_ID=
LARA_ACCESS_KEY_SECRET=
```

Never commit `.env` to Git — it is listed in `.gitignore`.

---

## Model Selection

The active Ollama model can be changed on the fly via the dropdown in the status bar.
Available models are loaded automatically from the local Ollama instance.
The default model is set in `config.yaml` — the dropdown overrides it at runtime without restart.

---

## Translation Modes

| Mode | Description |
|------|-------------|
| **Automatic (Pause)** | Translates after X seconds of typing stop (configurable via `debounce_seconds`) |
| **Sentencewise (Enter)** | Translates on every Enter press |
| **Manual (Button)** | Only on button press |

---

## Final Pass Engines

Four optional Final-Pass buttons appear in the footer when an engine is configured and enabled.

Recommended workflow:
- During editing → Ollama (local, no cost)
- Final text → one Final-Pass button (one-time quality pass)

| Engine | Signup | Key required | Notes |
|--------|--------|--------------|-------|
| **★ DeepL** | Yes + credit card | Yes (in `.env`) | Best quality for European languages |
| **★ LibreTranslate** | No | Optional | Self-hosted via Docker, see `README_libretranslate.md` |
| **★ MyMemory** | No | No | Works out of the box. Texts over 500 chars are chunked automatically. |
| **★ Lara** | Yes, no credit card | Yes (in `.env`) | 5.000 chars/day free, daily counter shown in button |

Configure engines in `config.yaml`:

```yaml
# DeepL
deepl_free_tier: true            # true = Free API, false = Pro API

# LibreTranslate
libretranslate_url: "http://localhost:5000"
libretranslate_api_key: ""
libretranslate_enabled: false

# MyMemory
mymemory_enabled: true
mymemory_email: ""               # optional: higher daily limit

# Lara Translate
lara_enabled: false
lara_daily_limit: 5000           # local daily counter limit
```

Lara credentials go into `.env`:
```env
LARA_ACCESS_KEY_ID=your-key-id
LARA_ACCESS_KEY_SECRET=your-secret
```
Get credentials at: `app.laratranslate.com/account/credentials`

---

## Lara Daily Counter

The Lara button shows remaining characters for today: `★ Lara (4.200 / 5.000)`.
Usage is tracked locally in `lara_usage.json` and resets at midnight.
The button disables automatically when the daily limit is reached.

---

## LibreTranslate Status

The LibreTranslate button updates dynamically based on the selected language pair:
- `★ LibreTranslate` — online, language pair available
- `★ LibreTranslate (offline)` — service not running
- `★ LibreTranslate (DE not installed)` — language model missing

Use the **■ Stop** button in the status bar to stop the Docker container from within the UI.

---

## Export

**↓ Als .md exportieren** saves two files in the `exports/` folder:
- `translation_de_TIMESTAMP.md` — Source text
- `translation_en_TIMESTAMP.md` — Translation

---

## Dependencies (automatically installed)

```
fastapi
uvicorn
httpx
pyyaml
python-dotenv
lara-sdk
```

---

## Engine Quality — Benchmark Notes

The engines in LocalTranslate are not equivalent. They differ fundamentally in how they work,
not just in price or availability.

**LLMs** (Claude, Ollama models) have learned language as a whole — including style, rhythm,
context, and pragmatics. They translate with an understanding of what a sentence means and how
it should read.

**LibreTranslate** is based on Argos Translate, a small neural MT model trained specifically for
translation. It processes text segment by segment without holding the broader context. This works
well for standardised content — UI strings, forms, short technical phrases — but breaks down on
prose with deliberate style and tone.

---

### Results — DE → EN, literary-technical prose (8 engines tested)

| Rank   | Engine                          | Score        | Tone  | Formatting | Error Rate | Notes                                                             |
| ------ | ------------------------------- | ------------ | ----- | ---------- | ---------- | ----------------------------------------------------------------- |
| **1**  | **Claude.ai**                   | **96 / 100** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐      | ⭐          | Publication-ready. Matches original voice, structure, and rhythm. |
| **2**  | **Ollama — TranslateGemma-12B** | **92 / 100** | ⭐⭐⭐⭐  | ⭐⭐⭐⭐⭐      | ⭐⭐         | Best local model. Slightly smoother than original, very stable.   |
| **3**  | **Ollama — Aya Expanse**        | **89 / 100** | ⭐⭐⭐⭐  | ⭐⭐⭐⭐⭐      | ⭐⭐         | Strong narrative flow, minor interpretive drift.                  |
| **4**  | **Ollama — Mistral (latest)**   | **85 / 100** | ⭐⭐⭐   | ⭐⭐⭐⭐       | ⭐⭐⭐        | Reliable, but stylistically flatter and more generic.             |
| **5**  | **Ollama — DeepSeek-R1 14B**    | **83 / 100** | ⭐⭐⭐   | ⭐⭐⭐⭐       | ⭐⭐⭐        | Content accurate, rhythm slightly mechanical.                     |
| **6**  | **Ollama — Dolphin 3**          | **82 / 100** | ⭐⭐⭐   | ⭐⭐⭐⭐       | ⭐⭐⭐        | Generally good, but inconsistent phrasing and tone.               |
| **7**  | **Ollama — Mistral Nemo**       | **78 / 100** | ⭐⭐    | ⭐⭐⭐⭐       | ⭐⭐⭐⭐       | Grammatically solid, but stiff and less natural tone.             |
| **8**  | **Ollama — Qwen2.5-Coder 14B**  | **77 / 100** | ⭐⭐    | ⭐⭐⭐⭐⭐      | ⭐⭐⭐        | Structurally clean, but narratively dry and technical.            |
| **9**  | **Ollama — Llama 3.2**          | **68 / 100** | ⭐⭐    | ⭐⭐⭐        | ⭐⭐⭐⭐       | Noticeable phrasing issues and minor structural inconsistencies.  |
| **10** | **LibreTranslate**              | **48 / 100** | ⭐     | ⭐⭐         | ⭐⭐⭐⭐⭐      | Frequent wording errors, tone lost, formatting unstable.          |

---

### Rating Criteria (for clarity)

* **Tone** → How well the model preserves the original voice (reflective, direct, non-hyped)
* **Formatting** → Structural integrity (Markdown, emphasis, code blocks)
* **Error Rate** → Linguistic + semantic errors (lower = better)

Test text: a German engineering narrative (technical + reflective) with restrained tone, implicit meaning, and structured pacing.
Results vary by text type — simpler, standardised content (e.g. UI text or documentation) is significantly easier for most models.

---

### Recommendations by use case

**Literary or editorial prose** — Use Claude as primary engine. No local model currently matches it
for texts where style matters. Dolphin 3 or Mistral Nemo are the best offline fallbacks, but expect
to do a light editing pass.

**Technical documentation, config comments, UI strings** — Any Ollama model works well here.
LibreTranslate is acceptable if the text is short and repetitive.

**LibreTranslate** — Useful as an offline fallback for simple content, or to check whether a passage
is structurally correct before a full pass. Not suitable for prose with tone.

**MyMemory** — Convenience option for quick checks. Texts over 500 characters are split into chunks automatically. Quality varies per language pair.

**DeepL / Lara** — Cloud engines with the best quality outside of Claude for European language pairs.
Use as a final-pass step on texts that matter.

# Gemini Chat Pipeline

Extraction, sorting, and summarizing of Gemini chat histories.
Built in the context of the **Garmin Local Archive** project — but it works
for anyone who uses Gemini and wants to archive their chats locally.

---

## Pipeline overview

```
Gemini (browser)
        │
        ▼
[Chrome extension]         — amazingpaddy/ai-chat-exporter (unpacked, local)
        │
        ▼
[start_gla_export.bat]     — start Chrome with a debug port + start the script
        │
        ▼
[gemini_exporter_gla.py]   — Playwright automation: export chats
        │
        ▼
gemini_gla_export/          — raw MD files (unfiltered)
        │
        ▼
[sort_gemini_chats.py]      — chronological sorting + dedup
        │
        ▼
gemini_sorted/              — numbered MD files (gemini_001_*.md …)
        │
        ▼
[summarize_gemini_chats.py] — Ollama map-reduce summarizer
        │
        ▼
chat_summaries_gemini.md    — navigable summary of all chats
```

---

## Prerequisites

### Software

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | All scripts |
| Chrome | current | Export via Playwright |
| Ollama | current | Local LLM inference |

### Chrome extension — amazingpaddy/ai-chat-exporter

The extension is loaded **unpacked** — no Chrome Web Store, full control
over the installed code.

**Installation:**
```
1. Clone https://github.com/amazingpaddy/ai-chat-exporter or download it as a ZIP
   → unpack to e.g. C:\Tools\ai-chat-exporter\

2. Open Chrome → chrome://extensions/
3. Top right: switch on "Developer mode"
4. Click "Load unpacked"
5. Select the folder C:\Tools\ai-chat-exporter\
6. The extension appears in the list — done
```

> ⚠️ The extension stays active only for the Chrome profile under
> `C:\ChromeDebug` (the debug instance). Your normal Chrome profile is not
> affected.

### Ollama models

```powershell
ollama pull qwen2.5:7b        # chunk phase (fast)
ollama pull deepseek-r1:14b   # merge phase (reasoning)
ollama pull phi4:14b          # direct summaries of short chats
```

The models are configurable in `summarize_gemini_chats.py` — other models work as well.

### Python dependencies

```powershell
pip install playwright
playwright install chromium
```

---

## Directory structure

```
chat_pipeline/Gemini/
├── start_gla_export.bat          ← step 0: start Chrome + start the exporter
├── gemini_exporter_gla.py        ← step 1: Playwright export automation
├── sort_gemini_chats.py          ← step 2: chronological sorting
├── summarize_gemini_chats.py     ← step 3: Ollama summarizer
│
├── gemini_gla_export/            ← [not in the repo] raw exports
├── gemini_sorted/                ← [not in the repo] sorted chats
└── chat_summaries_gemini.md      ← [not in the repo] final output
```

---

## Step 0 — Start Chrome (`start_gla_export.bat`)

Double-click `start_gla_export.bat`. The script:

1. Closes running Chrome instances
2. Starts Chrome with debug port 9222 and a separate profile (`C:\ChromeDebug`)
3. Opens `gemini.google.com/app` directly
4. Starts `gemini_exporter_gla.py` automatically

**On the first start:**
- Chrome opens with an empty `C:\ChromeDebug` profile
- Sign in to Google
- Load the extension manually (see above, one time only)

**Adjust the Chrome path** if Chrome is not installed under
`C:\Program Files\Google\Chrome\Application\chrome.exe`:
→ edit the `start "" "…\chrome.exe"` line in `start_gla_export.bat`.

---

## Step 1 — Export automation (`gemini_exporter_gla.py`)

The script connects to the running Chrome via Playwright CDP, scrolls
through the sidebar, collects all chat URLs, and exports the filtered chats
as MD files.

### Flow
```
1. CDP connection to Chrome (port 9222)
2. Scroll the sidebar → collect all chat URLs
3. Open each chat → check the title against the keyword filter
4. On a match: click the extension button "Export Chat" (twice — popup + confirmation)
5. The MD file lands in the download folder → is moved to gemini_gla_export/
```

### Adjusting the keyword filter

The filter in `gemini_exporter_gla.py` exports only chats whose title contains one of the terms in
`PROJECT_KEYWORDS`. The shipped list holds two placeholders — replace them with terms from your own
chat titles at the top of the script.

Export all chats without a filter:
```powershell
python gemini_exporter_gla.py --no-filter
```

### Parameters

```powershell
python gemini_exporter_gla.py --output-dir ./my_chats      # different output folder
python gemini_exporter_gla.py --no-filter                  # export all chats
python gemini_exporter_gla.py --cdp-port 9223              # different debug port
python gemini_exporter_gla.py --no-skip                    # re-export chats that already exist
```

**Output:** MD files named `Chatname_YYYYMMDD_HHMMSS.md`

---

## Step 2 — Sorting (`sort_gemini_chats.py`)

Sorts the exported MDs chronologically by the export timestamp in the file
name. Gemini exports chats from top to bottom (newest first) — reversing
that gives chronological order.

### Running it

```powershell
# Dry run — preview only, nothing is copied
python sort_gemini_chats.py --dry-run

# For real
python sort_gemini_chats.py

# Different paths
python sort_gemini_chats.py --source ./gemini_gla_export --dest ./gemini_sorted
```

### Duplicate handling

For some chats the extension produces two files with a slightly different
timestamp format. The script detects duplicates through a normalized title
comparison and keeps the older one in each case.

**Output:** `gemini_001_Title.md` … `gemini_NNN_Title.md`

---

## Step 3 — Summarizer (`summarize_gemini_chats.py`)

Summarizes every chat via Ollama. Short chats directly, long chats via
map-reduce (chunk → partial summary → merge).

### Prerequisite

```powershell
ollama serve   # keep it running in a separate window
```

### Running it

```powershell
python summarize_gemini_chats.py
```

Resume-safe: after an interruption just start it again —
chats that were already processed are skipped.

### Configuration (in `summarize_gemini_chats.py`)

```python
CHUNK_MODEL  = "qwen2.5:7b"      # chunk phase — fast
MERGE_MODEL  = "deepseek-r1:14b" # merge — stronger model
DIRECT_MODEL = "phi4:14b"        # short chats, directly

CHUNK_SIZE    = 8000   # characters per chunk
CHUNK_OVERLAP = 400    # overlap between chunks
```

### Processing logic

```
Chat ≤ 8,000 characters  → DIRECT_MODEL, 1 call

Chat > 8,000 characters  → map-reduce:
  Chunk 1 → CHUNK_MODEL → partial summary 1
  Chunk 2 → CHUNK_MODEL → partial summary 2
  ...
  All partial summaries → MERGE_MODEL → overall summary
```

### Time estimate

| Chat size | Chunks | Duration (approx.) |
|-----------|--------|--------------------|
| < 8 KB | — (direct) | 2-3 min |
| ~50 KB | ~6 chunks | 15-20 min |
| ~200 KB | ~25 chunks | 60-90 min |

**VRAM note:** `qwen2.5:7b` + `deepseek-r1:14b` do not fit into 16 GB of VRAM
at the same time. Ollama swaps automatically — that is fine, since the chunk
and merge phases run sequentially anyway.

---

## Notes

**Keyword filter:** `PROJECT_KEYWORDS` in `gemini_exporter_gla.py` holds placeholders.
Set your own terms or switch the filter off with `--no-filter`.

**Project description:** `PROJECT_DESCRIPTION` at the top of `summarize_gemini_chats.py`
is inserted into every summary prompt. Describe your project there.

**Switching models:** The first switch between CHUNK_MODEL and MERGE_MODEL
costs ~30-60 seconds of load time — that is normal.

**Very long chats:** Single chats of 200+ KB are possible (several months
of development in one conversation). Map-reduce handles these reliably,
but needs time accordingly.

---

*Pipeline created: May 2026*
*Context: Garmin Local Archive — story documentation*
*Extension: [amazingpaddy/ai-chat-exporter](https://github.com/amazingpaddy/ai-chat-exporter)*

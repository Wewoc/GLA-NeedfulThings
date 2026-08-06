# Garmin Local Archive — Chat Analysis Pipeline

A local pipeline for sorting, summarizing, and exporting Claude chat histories.
Useful for reviewing architectural decisions, generating project narratives, or building context for new sessions.

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) running locally (`ollama serve`)
- A locally available model — default: `qwen2.5-coder:14b`
- Step 6 only: `pip install python-docx`

### Recommended models

| Model | Size | Best for |
|---|---|---|
| `qwen2.5:14b` | 14B | General default — technical and non-technical |
| `qwen2.5-coder:14b` | 14B | Technical/code-heavy chats |
| `llama3.1:8b` | 8B | Faster, good for mixed DE/EN content |
| `mistral:7b` | 7B | Lightweight, solid for text summarization |

Pull a model with `ollama pull <model>` before running Step 2.

---

## Setup

1. Export your Claude chats via claude.ai → Settings → Export Data
2. Place the exported JSON file(s) in a folder
3. Run `run.bat` — it will ask for configuration and which steps to run

Or manually:
- Edit `config.py` — set `INPUT_DIR`, `SEARCH_LABEL`, and `MODEL`
- Run the steps in order

---

## Steps

| Step | Script | Required |
|---|---|---|
| 1 | `Step 1 - sort_chats.py` | ✓ |
| 2 | `Step 2 - summarize_chats.py` | ✓ |
| 3 | `Step 3 - sort_summaries.py` | ✓ |
| 4 | `Step 4 - optional - merge_chats.py` | Optional |
| 5 | `Step 5 - optional - sorted_json_to_md.py` | Optional |
| 6 | `Step 6 - optional - chats_to_word.py` | Optional |

**Step 1** — filters chats by label prefix (`SEARCH_LABEL` in config.py), writes individual JSON files to `sorted/label/`.

**Step 2** — summarizes each chat via Ollama. Resume-safe: interrupted runs continue where they left off. With 277 chats expect several hours depending on model and hardware.

**Step 3** — sorts the summary file chronologically by chat timestamp. Original file is not modified.

**Step 4** — merges all sorted JSONs into a single file for upload to another LLM.

**Step 5** — converts each sorted JSON to a Markdown file.

**Step 6** — converts each sorted JSON to a Word document (.docx). Requires `python-docx`.

---

## Output

All output lands in `sorted/Garmin/` (or `sorted/<SEARCH_LABEL>/` if changed):

```
sorted/Garmin/
  0001_Garmin-....json       ← sorted individual chats
  chat_summaries.md          ← raw summaries (Step 2 output)
  chat_summaries_sorted.md   ← chronologically sorted (Step 3 output)
  merged_chats.json          ← optional merge (Step 4)
  Markdown_Export/           ← optional MD export (Step 5)
  Word_Export/               ← optional Word export (Step 6)
```

---

## Configuration

All parameters in `config.py` — no other files need to be changed:

| Parameter | Default | Description |
|---|---|---|
| `SEARCH_LABEL` | `"Garmin"` | Label prefix to filter chats |
| `INPUT_DIR` | `.` | Folder with exported Claude JSON files |
| `MODEL` | `"qwen2.5-coder:14b"` | Ollama model for summarization |
| `MAX_MESSAGES`   | `60`  | Max messages per chat sent to model |
| `OLLAMA_TIMEOUT` | `300` | Seconds to wait per summarization request |

# mcp-llm-tester

Automated end-to-end test runner that checks how well different local
Ollama models handle tool calling against a running MCP server. Sends
a configurable catalog of questions to each model in turn, executes
any tool calls the model makes for real against your MCP server, and
logs everything as raw data for you to review afterwards.

This is a generic tool: it has no built-in knowledge of what your MCP
server's tools are called or what they do. You provide the questions
and the expected tool/arguments as plain data in a question catalog
file. Optionally, you can also compare several system prompt variants
(e.g. a minimal one vs. a more guided one) against the same catalog.

Two ways to run it:

- **GUI** (`mcp_test_gui.py`) -- pick catalogs, models, and system
  prompt variants by clicking, start/stop/resume runs, watch a live
  log and progress bar.
- **CLI** (`mcp_llm_test_runner.py`, `main()`) -- plain script run, no
  interaction, uses `config.py` + `question_catalog.py` directly.

Both share the same underlying run logic (`run_test_session()` in
`mcp_llm_test_runner.py`).

## What it does

For every selected model, for every selected system prompt variant,
for every question in the selected catalog(s):

1. Sends the question to the model via Ollama's `/api/chat`, along
   with the live tool definitions fetched from your MCP server
   (`tools/list`).
2. If the model responds with a tool call, executes it for real
   against the MCP server (`tools/call`) and feeds the result back to
   the model.
3. Repeats until the model gives a final text answer, or
   `config.MAX_TOOL_TURNS` is reached.
4. Logs the full exchange -- which tool was called with which
   arguments, timings, errors, and the final answer -- to a progress
   file immediately, and to a timestamped JSON + Markdown report at
   the end of the run.

**The runner does not judge correctness.** It never checks the actual
tool call against your `expected_tool`/`expected_params` -- those
fields are written into the results purely so you can compare them
yourself afterwards.

## Prerequisites

- Your MCP server is already running and reachable at the URL set in
  `config.MCP_URL`. This tool is a client only -- it does not start or
  manage the server.
- Ollama is running locally. For the GUI, available models are fetched
  live from Ollama (no need to list them anywhere). For the CLI path,
  the models listed in `config.MODEL_LIST` must already be pulled
  (`ollama list` to check).
- Python 3.10+ with `requests` installed. The GUI additionally needs
  Tkinter (included in most standard Python installs on Windows).

## Usage -- GUI

1. Edit `config.py`: set `MCP_URL` and timeouts for your setup (model
   list is not used by the GUI).
2. Put one or more question catalog files into the `question_catalog/`
   subfolder, named `question_catalog*.py` (see format below). A blank
   template is included there to start from.
3. Optionally, put one or more system prompt files into the
   `system_prompts/` subfolder, named `system_prompt*.md` (see System
   prompt variants below). A minimal and a guided example are included
   there to start from.
4. Run `run_mcp_llm_test_gui.bat` (Windows) or `python mcp_test_gui.py`.
5. In the GUI:
   - Select one or more catalogs, one or more models, and one or more
     system prompt variants (click to multi-select in each list). The
     prompt list always includes a synthetic "(no system prompt)"
     entry at the top, alongside anything found in `system_prompts/`.
   - Fill in the run folder fields (Nr./Date/Rest) -- a name is
     suggested automatically, but editable. This becomes the folder
     name under `results/`.
   - **Start new run** begins a fresh run in that folder.
   - **Stop** requests a clean stop after the currently running
     question finishes -- the run folder stays resumable.
   - **Resume run** becomes available after a stop (or automatically
     at GUI startup, if the last run folder was left incomplete) and
     continues the same run, skipping questions already completed.
6. Results land in `results/<run_folder_name>/` -- see the Output
   files section below.

## Usage -- CLI

1. Edit `config.py`: set `MCP_URL`, `MODEL_LIST`, and timeouts.
2. Edit `question_catalog.py` (the one directly in this folder, not
   inside `question_catalog/`): replace the placeholder entries with
   real questions. See the schema in that file's docstring.
3. Run `run_mcp_llm_test.bat` (Windows) or
   `python mcp_llm_test_runner.py`.
4. Results land directly in `results/` (no per-run subfolder, for
   backward compatibility with the plain CLI path).

## Question catalog format

Same schema whether the file lives at the root (CLI path) or inside
`question_catalog/` (GUI path) -- see the docstring at the top of
`question_catalog.py` for the full field reference. In short, each
entry needs at least:

```python
{
    "id": "unique_id",
    "round": 1,
    "text": "the exact prompt sent to the model",
    "expected_tool": "tool_name_or_None",
}
```

Optional fields (`field`, `variant`, `note`, `expected_params`) are
passed through untouched into the result records for your own later
evaluation -- the runner never interprets them.

Each catalog file must export a `QUESTIONS` list of such dicts. For
the GUI, any file matching `question_catalog/question_catalog*.py` is
picked up automatically and shown as a selectable catalog.

## System prompt variants

Each file in `system_prompts/` matching `system_prompt*.md` is a
selectable system prompt, sent to Ollama as-is (plain text, no
Markdown rendering). Use this to compare, for example, a minimal
flow-control-only prompt against a more guided one that adds
orchestration hints for your own tool set, without touching the
question catalog or the runner itself. Two examples are included:

- `system_prompt_minimal.md` -- flow control only (tells the model to
  use tool results and not repeat calls), no hints about which tool to
  pick. Identical in spirit to `config.SYSTEM_PROMPT`.
- `system_prompt_guided.md` -- adds generic orchestration guidance
  (multi-tool questions, consistent parameters across related calls,
  retrying after a tool error, not inventing values). Adapt the
  specifics to your own tools/domains before relying on it.

In the CLI path (`main()`), only `config.SYSTEM_PROMPT` is used, same
as before this feature existed -- `system_prompts/` only applies to
the GUI.

## Output files

Per run folder (`results/` for the CLI path, `results/<run_folder>/`
for a GUI run):

- `mcp_llm_test_progress.jsonl` -- one line per completed
  (model, question, prompt variant) combination, written immediately.
  Interrupting a run and resuming it (CLI: rerun the script; GUI:
  Resume run) skips everything already in this file.
- `mcp_llm_test_<timestamp>.json` -- full result dump for all
  questions/models from the run (including anything resumed from the
  progress file).
- `mcp_llm_test_<timestamp>.md` -- the same data as a readable
  Markdown report.
- `_debug_ollama_tools.json` -- the tool definitions as sent to
  Ollama, written once per run (useful if tool-matching behaves
  unexpectedly and you want to check the exact schema Ollama saw).
- `_debug_first_raw_response.json` -- the raw Ollama response for the
  very first question/turn of the run, for the same reason.
- `console.log` (GUI runs only) -- a plain-text copy of everything
  shown in the GUI's log panel.

## Notes on model behaviour handled by this runner

- **Content-fallback tool calls**: some models return an otherwise
  correct tool call as plain JSON text in the message content instead
  of Ollama's native `tool_calls` field. The runner detects this
  strictly (only a bare `{"name": ..., "arguments": {...}}` JSON
  object, nothing else) and logs it with `"source": "content_fallback"`
  so you can tell native and fallback tool calls apart when comparing
  models.
- **No system prompt by default beyond flow control**: `SYSTEM_PROMPT`
  in `config.py` (used by the CLI path, and as the GUI's fallback if
  no prompt variant is available) is deliberately minimal -- it tells
  the model to use tool results and not repeat calls, but gives no
  hint about which tool to pick. This keeps the test focused on the
  model's own tool-matching ability. Set it to `None`/`""` to test with
  no system prompt at all, or use the GUI's system prompt variants (see
  above) to compare several prompts in one run.

## What this tool does not do

- It does not start, configure, or manage your MCP server or Ollama.
- It does not score or grade results -- that's a manual step using the
  JSON/Markdown output plus your own `expected_tool`/`expected_params`.
- It does not modify anything on your MCP server; `tools/call` results
  depend entirely on what your server's tools actually do.

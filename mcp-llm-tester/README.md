# mcp-llm-tester

Automated end-to-end test runner that checks how well different local
Ollama models handle tool calling against a running MCP server. Sends
a fixed catalog of questions to each model in turn, executes any tool
calls the model makes for real against your MCP server, and logs
everything as raw data for you to review afterwards.

This is a generic tool: it has no built-in knowledge of what your MCP
server's tools are called or what they do. You provide the questions
and the expected tool/arguments as plain data in `question_catalog.py`.

## What it does

For every model in `config.MODEL_LIST`, for every question in
`question_catalog.py`:

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
  `config.MCP_URL`. This script is a client only -- it does not start
  or manage the server.
- Ollama is running locally with the models listed in
  `config.MODEL_LIST` already pulled (`ollama list` to check).
- Python 3.10+ with the `requests` package installed.

## Usage

1. Edit `config.py`: set `MCP_URL`, `MODEL_LIST`, and timeouts for
   your setup.
2. Edit `question_catalog.py`: replace the placeholder entries with
   real questions against your own MCP tools. See the schema described
   in that file's docstring.
3. Run it:
   - Windows: double-click `run_mcp_llm_test.bat`, or
   - Any platform: `python mcp_llm_test_runner.py`
4. Results land in `results/`:
   - `mcp_llm_test_progress.jsonl` -- one line per completed question,
     written immediately. If a run is interrupted, restarting the
     script skips everything already in this file and picks up where
     it left off.
   - `mcp_llm_test_<timestamp>.json` -- full result dump for all
     questions/models from this run (including anything resumed from
     the progress file).
   - `mcp_llm_test_<timestamp>.md` -- the same data as a readable
     Markdown report.
   - `_debug_ollama_tools.json` -- the tool definitions as sent to
     Ollama, written once per run (useful if tool-matching behaves
     unexpectedly and you want to check the exact schema Ollama saw).
   - `_debug_first_raw_response.json` -- the raw Ollama response for
     the very first question/turn of the run, for the same reason.

## Question catalog format

See the docstring at the top of `question_catalog.py` for the full
field reference. In short, each entry needs at least:

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

## Notes on model behaviour handled by this runner

- **Content-fallback tool calls**: some models return an otherwise
  correct tool call as plain JSON text in the message content instead
  of Ollama's native `tool_calls` field. The runner detects this
  strictly (only a bare `{"name": ..., "arguments": {...}}` JSON
  object, nothing else) and logs it with `"source": "content_fallback"`
  so you can tell native and fallback tool calls apart when comparing
  models.
- **No system prompt by default beyond flow control**: `SYSTEM_PROMPT`
  in `config.py` is deliberately minimal -- it tells the model to use
  tool results and not repeat calls, but gives no hint about which
  tool to pick. This keeps the test focused on the model's own
  tool-matching ability. Set it to `None`/`""` to test with no system
  prompt at all.

## What this tool does not do

- It does not start, configure, or manage your MCP server or Ollama.
- It does not score or grade results -- that's a manual step using the
  JSON/Markdown output plus your own `expected_tool`/`expected_params`.
- It does not modify anything on your MCP server; `tools/call` results
  depend entirely on what your server's tools actually do.

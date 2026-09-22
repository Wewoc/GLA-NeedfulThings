#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
mcp-llm-tester/mcp_llm_test_runner.py
Automated end-to-end test: multiple Ollama models against a running
MCP server, real tool calls, minimal system prompt, no manual
intervention required.

Prerequisite: your MCP server is already running (see config.py for
the expected URL/port). Ollama runs locally on the default port.

Flow per catalog x model x question:
  1. Ollama chat call with the question + the tool definitions fetched
     live from the MCP server.
  2. If the response contains tool_calls, these are executed via
     tools/call against the real MCP server (end-to-end, no
     simulation) and the result is fed back to Ollama as a "tool"
     message.
  3. Repeats until the model answers without a further tool_call, or
     MAX_TOOL_TURNS is reached (safety limit against infinite loops
     with a misbehaving model).
  4. Every question is logged independently of success/failure -- a
     timeout or exception on one question does not abort the run, it
     is recorded as an error case in the result JSON instead.

Grading (pass/partial/fail) is NOT part of this script -- it only logs
raw data (which tool was called with which arguments, the final model
answer, timings, errors). Content evaluation happens afterwards,
manually, alongside your server/proxy logs.

── GUI addition ─────────────────────────────────────────────────────
Originally: one fixed catalog (question_catalog.py, imported directly),
one fixed model list (config.MODEL_LIST), one global progress path,
main() as the only entry point.

Now: run_test_session() is the new central, reusable run function --
takes a list of catalog file paths (loaded dynamically via importlib
instead of a fixed import) and a model list as parameters, iterates
catalog -> model -> question, writes progress/results into a passed-in
run folder instead of the global config.OUTPUT_DIR, and accepts
optional callbacks for log lines and progress events plus a
threading.Event for controlled stopping (after the currently running
question, not mid Ollama-call).

main() remains as a plain CLI entry point (backward compatible with
run_mcp_llm_test.bat) and simply calls run_test_session() with the
previous values from config.py (one catalog: question_catalog.py in
the same folder, model list: config.MODEL_LIST, output directly into
config.OUTPUT_DIR rather than a per-run subfolder -- kept unchanged
for backward compatibility).

All prior core functions (MCP client, Ollama client, per-question
flow, progress file, result writing) are functionally unchanged --
only run_question() additionally accepts an optional log_callback
parameter, since the GUI needs live output and an extra
logging.Handler (see _QueueLogHandler below) covers every
logger.info/warning/error call automatically anyway -- no manual
threading-through at every individual call site needed.

── System prompt variants ───────────────────────────────────────────
Analogous to the question catalogs: instead of a single fixed
config.SYSTEM_PROMPT, run_test_session() optionally accepts a list of
named (label, prompt_text) prompt variants (see
discover_system_prompts()/load_system_prompt()) and runs every
catalog x model combination through each variant in turn. Lets you
compare a minimal prompt against a more guided one without changing
the tool-matching test itself. Omitting prompt_variants keeps the
previous single-prompt behavior unchanged (backward compatible for
the CLI path).
"""

import importlib.util
import json
import logging
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import requests

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


# ── Optional live log for GUI hookup ─────────────────────────────────
#
# An extra logging.Handler that forwards every logged line to an
# arbitrary callback (e.g. a queue that a Tkinter GUI polls).
# Deliberately implemented as a handler rather than manually threading
# a callback through every logger.info(...) call site -- the ~15
# existing logging calls in this file stay unchanged, every log line
# is picked up automatically, including from functions that don't take
# a callback parameter (e.g. fetch_mcp_tools(), _mcp_request()).
class _QueueLogHandler(logging.Handler):
    """logging.Handler that forwards every formatted line to a
    callback. Errors in the callback itself must not crash the test
    run -- they are swallowed here, not re-raised (logging must never
    disrupt the actual program flow)."""

    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._callback(msg)
        except Exception:  # noqa: BLE001 — logging must never stop the run
            pass


def _install_log_callback(log_callback: Optional[Callable[[str], None]]) -> Optional[_QueueLogHandler]:
    """Registers a _QueueLogHandler on the module logger (if
    log_callback is given) and returns it, so the caller can remove it
    again after the run (otherwise handlers would accumulate across
    multiple GUI runs within the same process lifetime)."""
    if log_callback is None:
        return None
    handler = _QueueLogHandler(log_callback)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return handler


# ── MCP client part ──────────────────────────────────────────────────
#
# MCP over Streamable-HTTP is session-based: the server issues a
# session ID on the initialize call (header "Mcp-Session-Id") and
# expects it back in the same header on every following request --
# otherwise 400 Bad Request. If a server creates a new transport on
# every call instead of reusing one, check whether this header is
# actually being read and sent back.
#
# A session is built once per test run and reused across all
# models/questions -- the session is a pure transport connection to
# the MCP server, independent of the (deliberately stateless per-call)
# Ollama chat context per question.
_session_id: str | None = None


def _mcp_request(method: str, params: dict | None = None) -> dict:
    """Executes a single JSON-RPC request against the MCP server.
    Sends along the Mcp-Session-Id obtained from the earlier
    initialize call, once one is available. Raises an exception on
    timeout/connection error -- the caller catches this and logs it as
    an error case instead of aborting."""
    global _session_id
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params or {},
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if _session_id is not None:
        headers["Mcp-Session-Id"] = _session_id

    resp = requests.post(
        config.MCP_URL,
        json=payload,
        headers=headers,
        timeout=config.MCP_CALL_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()

    # Session ID arrives with the initialize response -- send it along
    # with every subsequent request of this run from here on.
    returned_session_id = resp.headers.get("Mcp-Session-Id")
    if returned_session_id and _session_id is None:
        _session_id = returned_session_id
        logger.info("MCP session established: %s", _session_id)

    # notifications/initialized is a notification with no response
    # body (JSON-RPC notification) -- some servers answer with an
    # empty body/202 here, which is not an error and doesn't need to
    # be parsed as JSON.
    if not resp.content:
        return {}

    # Streamable-HTTP can come back as text/event-stream (SSE framing,
    # "data: {...}" lines) instead of plain JSON -- handle both cases.
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in resp.text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                return json.loads(line[len("data:"):].strip())
        raise ValueError(f"No 'data:' field found in SSE response: {resp.text[:200]}")
    return resp.json()


def fetch_mcp_tools() -> list[dict]:
    """Fetches the tool list live from the MCP server (tools/list) and
    translates it into Ollama's tool format. Runs once before the
    actual test run -- no duplicating tool definitions inside this
    test script. Also establishes the MCP session reused for the whole
    run (see _session_id above)."""
    # MCP requires an initialize + notifications/initialized before
    # tools/list.
    _mcp_request("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "mcp_llm_test_runner", "version": "1.0"},
    })
    _mcp_request("notifications/initialized")
    result = _mcp_request("tools/list")
    mcp_tools = result.get("result", {}).get("tools", [])

    ollama_tools = []
    for t in mcp_tools:
        ollama_tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
            },
        })

    # Debug dump -- once per run, so the exact tool format sent to
    # Ollama can be inspected without guessing (useful for diagnosing
    # "0 tool calls" issues). Not a permanent part of normal operation,
    # kept mainly for troubleshooting.
    debug_path = Path(config.OUTPUT_DIR) / "_debug_ollama_tools.json"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_text(json.dumps(ollama_tools, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Debug: tool format sent to Ollama written to %s", debug_path)

    return ollama_tools


def call_mcp_tool(name: str, arguments: dict) -> dict:
    """Executes a real tools/call against the MCP server (end-to-end,
    no simulation) and returns the raw result."""
    result = _mcp_request("tools/call", {"name": name, "arguments": arguments})
    return result.get("result", result)


def _parse_content_fallback_tool_call(content: str) -> dict | None:
    """Some models return an otherwise-correct tool call not in
    Ollama's native message.tool_calls field, but as plain JSON text in
    message.content ('{"name": ..., "arguments": {...}}'). Some
    clients (e.g. Open WebUI) apparently tolerate/parse this
    themselves; the native Ollama client path here previously did not
    -- the call was lost as an empty final answer.

    Deliberately strict: only counts as a tool-call candidate if
    content, after strip(), parses completely and exclusively as a
    JSON object with exactly the keys "name" (str) and "arguments"
    (dict). Any deviation (not JSON, extra surrounding prose, missing
    or different keys) returns None -- a normal text answer that
    happens to contain a JSON-like fragment must not be wrongly
    treated as a tool call."""
    if not content or not content.strip():
        return None
    try:
        parsed = json.loads(content.strip())
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if set(parsed.keys()) != {"name", "arguments"}:
        return None
    if not isinstance(parsed["name"], str) or not isinstance(parsed["arguments"], dict):
        return None
    return parsed


# ── Ollama client part ───────────────────────────────────────────────

def ollama_chat(model: str, messages: list[dict], tools: list[dict]) -> dict:
    """A single Ollama /api/chat call, no streaming (easier to parse,
    response time is measured as a whole anyway, not token-by-token)."""
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
    }
    resp = requests.post(
        f"{config.OLLAMA_URL}/api/chat",
        json=payload,
        timeout=config.OLLAMA_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_ollama_models() -> list[str]:
    """Determines the locally available Ollama models live via the
    Ollama API (GET /api/tags) -- used by the GUI instead of the
    static config.MODEL_LIST. No parsing of 'ollama list' console
    text, the API returns the same information in structured form.
    Raises an exception on connection error -- the caller (GUI) catches
    this and shows it as an error message, no silent empty list."""
    resp = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return [m["name"] for m in data.get("models", [])]


def unload_ollama_model(model: str) -> None:
    """Asks Ollama to unload a model from memory immediately (the
    official mechanism: keep_alive=0 on a call with no real messages)
    -- prevents several models from stacking up in RAM/VRAM at once
    when cycling through many of them in sequence, since without this
    signal Ollama only unloads after its own idle timeout. Best
    effort: a failure here must not abort the run -- the model would
    just unload a bit later on its own instead."""
    try:
        requests.post(
            f"{config.OLLAMA_URL}/api/chat",
            json={"model": model, "messages": [], "keep_alive": 0},
            timeout=config.OLLAMA_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — best effort, must not abort the run
        logger.warning("Could not explicitly unload model %s: %s", model, exc)


# ── Catalog loading ──────────────────────────────────────────────────

def load_question_catalog(path: Path) -> list[dict]:
    """Dynamically loads a QUESTIONS list from an arbitrary catalog
    file (e.g. question_catalog_extra.py, question_catalog_full.py,
    ...). Replaces a fixed 'from question_catalog import QUESTIONS'
    import -- several structurally similar catalogs can live in the
    same folder (convention: question_catalog*.py, each file exports a
    QUESTIONS attribute).

    Raises AttributeError if the file has no QUESTIONS attribute --
    deliberately not silently skipped: a catalog without QUESTIONS is
    a configuration error the caller should see."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load catalog module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "QUESTIONS"):
        raise AttributeError(f"Catalog file without a QUESTIONS attribute: {path}")
    return module.QUESTIONS


def discover_question_catalogs(directory: Path) -> list[Path]:
    """Finds all question_catalog*.py files in a folder (naming
    convention). Sorted alphabetically for a stable, predictable list
    order in the GUI. Pure path discovery, does not load the modules
    -- that only happens once a catalog is actually selected, via
    load_question_catalog()."""
    return sorted(directory.glob("question_catalog*.py"))


# ── System prompt variants ───────────────────────────────────────────

def discover_system_prompts(directory: Path) -> list[Path]:
    """Finds all system_prompt*.md files in a folder (naming convention
    analogous to question_catalog*.py). Sorted alphabetically for a
    stable, predictable list order in the GUI."""
    return sorted(directory.glob("system_prompt*.md"))


def load_system_prompt(path: Path) -> str:
    """Loads a prompt file as plain text (no Markdown rendering -- the
    raw text goes to Ollama 1:1 as the system message)."""
    return path.read_text(encoding="utf-8").strip()


# ── Per-question flow ────────────────────────────────────────────────

def run_question(model: str, question: dict, tools: list[dict],
                  system_prompt: str | None = None) -> dict:
    """Multi-turn loop for a single question against one model. Returns
    a complete raw log -- never a grade/evaluation."""
    record = {
        "model": model,
        "question_id": question["id"],
        "round": question["round"],
        "question_text": question["text"],
        "expected_tool": question.get("expected_tool"),
        "expected_params": question.get("expected_params"),
        "timestamp_start": datetime.now(timezone.utc).isoformat(),
        "tool_calls": [],
        "final_answer": None,
        "turns_used": 0,
        "error": None,
        "duration_seconds": None,
    }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": question["text"]})
    start = time.monotonic()

    try:
        for turn in range(1, config.MAX_TOOL_TURNS + 1):
            record["turns_used"] = turn
            response = ollama_chat(model, messages, tools)

            # Debug dump of the RAW Ollama response -- once, for the
            # very first question/turn of the whole run, to diagnose
            # "0 tool calls" style issues without guessing (tool schema
            # itself can look valid while the actual Ollama response
            # format was never verified). Not a permanent part of
            # normal operation.
            debug_raw_path = Path(config.OUTPUT_DIR) / "_debug_first_raw_response.json"
            if not debug_raw_path.exists():
                debug_raw_path.parent.mkdir(parents=True, exist_ok=True)
                debug_raw_path.write_text(
                    json.dumps(response, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                logger.info("Debug: raw Ollama response written to %s", debug_raw_path)

            message = response.get("message", {})
            tool_calls = message.get("tool_calls") or []
            tool_call_source = "native"

            if not tool_calls:
                fallback = _parse_content_fallback_tool_call(message.get("content", ""))
                if fallback is not None:
                    tool_calls = [{"function": fallback}]
                    tool_call_source = "content_fallback"
                    logger.info(
                        "  -> Tool call parsed from content fallback (not "
                        "native tool_calls): %s", fallback["name"])

            if not tool_calls:
                record["final_answer"] = message.get("content", "")
                break

            messages.append(message)
            for call in tool_calls:
                fn = call.get("function", {})
                tool_name = fn.get("name", "")
                tool_args = fn.get("arguments", {})
                call_start = time.monotonic()
                try:
                    tool_result = call_mcp_tool(tool_name, tool_args)
                    call_error = None
                except Exception as exc:  # noqa: BLE001 — deliberately broad, error is logged, not swallowed
                    tool_result = None
                    call_error = str(exc)
                call_duration = time.monotonic() - call_start

                record["tool_calls"].append({
                    "turn": turn,
                    "name": tool_name,
                    "arguments": tool_args,
                    "result": tool_result,
                    "error": call_error,
                    "duration_seconds": round(call_duration, 3),
                    "source": tool_call_source,
                })

                messages.append({
                    "role": "tool",
                    "content": json.dumps(tool_result if call_error is None
                                           else {"error": call_error}),
                })
        else:
            record["error"] = f"MAX_TOOL_TURNS ({config.MAX_TOOL_TURNS}) reached without a final answer"

    except requests.exceptions.Timeout:
        record["error"] = f"Ollama timeout after {config.OLLAMA_TIMEOUT_SECONDS}s"
    except requests.exceptions.RequestException as exc:
        record["error"] = f"Connection error: {exc}"
    except Exception as exc:  # noqa: BLE001 — question is still logged, run continues
        record["error"] = f"Unexpected error: {exc}"

    record["duration_seconds"] = round(time.monotonic() - start, 3)
    record["timestamp_end"] = datetime.now(timezone.utc).isoformat()
    return record


# ── Progress file (resume) ───────────────────────────────────────────
#
# Originally a single global fixed path
# (results/mcp_llm_test_progress.jsonl) shared across all runs. Now:
# one progress path per run folder (see run_test_session() below) --
# fits the "one folder per run" scheme (lauf_<nr>_<date>_<label>/) and
# allows resuming exactly the one interrupted run instead of globally
# across every run ever made.

def load_completed_keys(progress_path: Path) -> tuple[set[tuple[str, object]], list[dict]]:
    """Reads an existing progress file (if present) and returns:
    (1) the set of already-completed (model, question_id,
    prompt_variant) keys to skip, (2) the already-loaded records
    themselves, so the final report stays complete on a resumed run
    instead of only showing the newly added questions. Broken/unreadable
    individual lines are skipped and logged, not a reason to abort the
    whole run -- resume should be more robust than the problem it's
    meant to solve.

    Older progress files predating the prompt-variant axis have no
    "prompt_variant" field (reads back as None) -- on resume this at
    worst re-runs a handful of questions unnecessarily, never loses
    data or wrongly marks a combination as done."""
    completed: set[tuple[str, object]] = set()
    records: list[dict] = []
    if not progress_path.exists():
        return completed, records

    with progress_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Progress file %s, line %d unreadable -- skipped: %s",
                    progress_path, line_num, exc)
                continue
            completed.add((record.get("model"), record.get("question_id"), record.get("prompt_variant")))
            records.append(record)

    if records:
        logger.info(
            "%d already-completed question(s) loaded from %s -- will be skipped",
            len(records), progress_path)
    return completed, records


def append_result(record: dict, progress_path: Path) -> None:
    """Appends a single record as a JSON line to the progress file and
    flushes immediately -- the goal is that the line is already on
    disk right after this call, even on a hard crash, not just
    sitting in a Python buffer."""
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    with progress_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False))
        f.write("\n")
        f.flush()


def write_results(results: list[dict], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    json_path = output_dir / f"mcp_llm_test_{run_id}.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    md_path = output_dir / f"mcp_llm_test_{run_id}.md"
    lines = [f"# MCP-LLM test run {run_id}", ""]
    for r in results:
        lines.append(f"## Model: {r['model']} — Prompt: {r.get('prompt_variant', 'config_default')} — question {r['question_id']} (round {r['round']})")
        lines.append(f"**Question:** {r['question_text']}")
        lines.append(f"**Expected tool:** {r['expected_tool']}")
        lines.append(f"**Duration:** {r['duration_seconds']}s, **Turns:** {r['turns_used']}")
        if r["error"]:
            lines.append(f"**ERROR:** {r['error']}")
        if r["tool_calls"]:
            lines.append("**Tool calls:**")
            for tc in r["tool_calls"]:
                lines.append(f"- `{tc['name']}({tc['arguments']})` — {tc['duration_seconds']}s"
                              + (f" — ERROR: {tc['error']}" if tc["error"] else ""))
        else:
            lines.append("**Tool calls:** none")
        lines.append(f"**Final answer:** {r['final_answer']}")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return json_path, md_path


# ── Central run function (GUI-capable) ────────────────────────────────

def run_test_session(
    catalog_paths: list[Path],
    model_list: list[str],
    output_dir: Path,
    prompt_variants: Optional[list[tuple[str, str]]] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[dict], None]] = None,
    stop_event: Optional[threading.Event] = None,
    resume: bool = False,
) -> tuple[Path, Path]:
    """Central run function, iterates catalog -> model -> prompt variant
    -> question (in exactly this order: catalog A with model 1 through
    every prompt variant, then model 2, and so on, then catalog B).

    Parameters:
      catalog_paths      -- list of paths to question_catalog*.py files,
                            in the desired processing order.
      model_list          -- list of Ollama model names.
      prompt_variants     -- list of (label, prompt_text) pairs (see
                            discover_system_prompts()/load_system_prompt()).
                            If None/empty: single-element default
                            [("config_default", config.SYSTEM_PROMPT)] --
                            identical to the previous main() behavior,
                            purely backward compatible for the CLI path.
      output_dir           -- run folder that the progress file and the
                            final JSON/MD are written into (with
                            resume=True this must be the same folder as
                            the original run, so the existing progress
                            file is found).
      log_callback        -- optional, receives every formatted log line
                            (see _QueueLogHandler above) -- for live
                            display in a GUI.
      progress_callback   -- optional, receives a dict after every
                            completed question:
                              {"catalog": <filename>, "catalog_idx": int,
                               "catalog_total": int, "model": <name>,
                               "model_idx": int, "model_total": int,
                               "prompt": <variant label>, "prompt_idx": int,
                               "prompt_total": int,
                               "question_idx": int, "question_total": int}
                            (1-based counters, question_idx/total refer
                            to the currently active catalog).
      stop_event           -- optional, threading.Event. Checked after
                            every completed question (not during a
                            running Ollama/MCP call) -- the currently
                            running question is always finished and
                            written to the progress file, only then
                            does the run stop cleanly.
      resume               -- if True: an existing progress file in
                            output_dir is read, already-completed
                            (model, question_id, prompt_variant)
                            combinations are skipped (see
                            load_completed_keys()). If False: an
                            existing progress file in output_dir is not
                            deleted, but also not taken into account --
                            appending to a foreign/stale file would mix
                            data, so with resume=False and an
                            already-existing progress file, an error is
                            raised instead of silently overwriting or
                            mixing data.

    Returns (json_path, md_path) of the final result files.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "mcp_llm_test_progress.jsonl"

    if progress_path.exists() and not resume:
        raise FileExistsError(
            f"A progress file already exists in {output_dir}, but resume=False. "
            "Use a new run folder for a new run, or set resume=True to "
            "continue the existing one."
        )

    variants = prompt_variants if prompt_variants else [
        ("config_default", getattr(config, "SYSTEM_PROMPT", None) or "")
    ]

    handler = _install_log_callback(log_callback)
    try:
        logger.info("Fetching tool list from MCP server (%s) ...", config.MCP_URL)
        try:
            tools = fetch_mcp_tools()
        except Exception as exc:
            logger.error("Could not load tool list -- is the MCP server running? Error: %s", exc)
            raise

        logger.info("%d tools loaded: %s", len(tools), [t["function"]["name"] for t in tools])

        if resume:
            completed_keys, results = load_completed_keys(progress_path)
        else:
            completed_keys, results = set(), []

        catalog_total = len(catalog_paths)
        for catalog_idx, catalog_path in enumerate(catalog_paths, start=1):
            catalog_name = catalog_path.name
            questions = load_question_catalog(catalog_path)
            question_total = len(questions)
            model_total = len(model_list)

            logger.info("=== Catalog %d/%d: %s (%d questions) ===",
                        catalog_idx, catalog_total, catalog_name, question_total)

            prompt_total = len(variants)
            for model_idx, model in enumerate(model_list, start=1):
                logger.info("--- Model %d/%d: %s ---", model_idx, model_total, model)

                for prompt_idx, (prompt_name, prompt_text) in enumerate(variants, start=1):
                    logger.info("  >>> Prompt variant %d/%d: %s <<<",
                                prompt_idx, prompt_total, prompt_name)

                    for question_idx, question in enumerate(questions, start=1):
                        key = (model, question["id"], prompt_name)
                        if key in completed_keys:
                            logger.info(
                                "[%s | %s | %s | %d/%d] Question %s: already done -- skipped",
                                catalog_name, model, prompt_name, question_idx, question_total,
                                question["id"])
                        else:
                            logger.info(
                                "[%s | %s | %s | %d/%d] Question %s: %s",
                                catalog_name, model, prompt_name, question_idx, question_total,
                                question["id"], question["text"])
                            record = run_question(model, question, tools, system_prompt=prompt_text)
                            record["catalog"] = catalog_name
                            record["prompt_variant"] = prompt_name
                            if record["error"]:
                                logger.warning("  -> Error: %s", record["error"])
                            else:
                                logger.info("  -> %d tool call(s), %.1fs",
                                            len(record["tool_calls"]), record["duration_seconds"])
                            results.append(record)
                            append_result(record, progress_path)

                        if progress_callback is not None:
                            progress_callback({
                                "catalog": catalog_name,
                                "catalog_idx": catalog_idx,
                                "catalog_total": catalog_total,
                                "model": model,
                                "model_idx": model_idx,
                                "model_total": model_total,
                                "prompt": prompt_name,
                                "prompt_idx": prompt_idx,
                                "prompt_total": prompt_total,
                                "question_idx": question_idx,
                                "question_total": question_total,
                            })

                        # Stop is deliberately only checked AFTER the completed
                        # question -- the currently running question is
                        # always finished first, so the progress file never
                        # ends up in a half-written/inconsistent state.
                        if stop_event is not None and stop_event.is_set():
                            logger.info("Stop requested -- run will end after this question.")
                            json_path, md_path = write_results(results, output_dir)
                            # Deliberately NO mcp_llm_test_done.marker here --
                            # the marker distinguishes genuine completion from
                            # a stop, so find_resumable_run() (mcp_test_gui.py)
                            # still recognizes a stopped run as resumable even
                            # after a GUI restart, despite a (snapshot) JSON
                            # already sitting in the folder.
                            logger.info("Intermediate results written to: %s / %s", json_path, md_path)
                            return json_path, md_path

                # Explicitly unload the model for this catalog once all
                # prompt variants/questions are done -- otherwise, with
                # many models in sequence, several can end up loaded at
                # once in RAM/VRAM, since Ollama only unloads after its
                # own timeout without this signal.
                unload_ollama_model(model)

        json_path, md_path = write_results(results, output_dir)
        (output_dir / "mcp_llm_test_done.marker").touch()
        logger.info("Done. Results written to:")
        logger.info("  %s", json_path)
        logger.info("  %s", md_path)
        return json_path, md_path
    finally:
        if handler is not None:
            logger.removeHandler(handler)


# ── CLI entry point (backward compatibility) ──────────────────────────

def main() -> None:
    """Plain CLI entry point for the original call path
    (run_mcp_llm_test.bat, no GUI). Assembles the previous values from
    config.py/question_catalog.py into a run_test_session() call -- no
    standalone flow code left here, just a thin wrapper. Deliberately
    identical behavior to the original main(): one catalog
    (question_catalog.py in the same folder), config.MODEL_LIST,
    output_dir=config.OUTPUT_DIR directly (no dedicated run subfolder)
    -- so existing calls/scripts keep working unchanged. resume=True,
    since the original main() logic always treated an existing
    progress file in config.OUTPUT_DIR as a resume source, never as an
    error case."""
    default_catalog = Path(__file__).parent / "question_catalog.py"
    try:
        run_test_session(
            catalog_paths=[default_catalog],
            model_list=config.MODEL_LIST,
            output_dir=Path(config.OUTPUT_DIR),
            resume=True,
        )
    except Exception as exc:
        logger.error("Run aborted: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
mcp-llm-tester/mcp_llm_test_runner.py
Automated end-to-end test: runs several Ollama models against a
running MCP server, with real tool calls, no manual intervention.

Prerequisite: your MCP server is already running (see config.py for
the expected URL/port). Ollama is running locally on its default port.

Flow per model x question:
  1. An Ollama chat call with the question plus the tool definitions
     fetched live from the MCP server (no system prompt beyond the
     minimal flow-control one in config.py -- the goal is to measure
     the model's own tool-matching behaviour, not to steer it).
  2. If the response contains tool_calls, each one is executed against
     the real MCP server via tools/call (end-to-end, no simulation)
     and the result is fed back to Ollama as a "tool" message.
  3. This repeats until the model answers without a further tool call,
     or MAX_TOOL_TURNS is reached (safety limit against infinite loops
     if a model misbehaves).
  4. Every question is logged independently of success or failure -- a
     timeout or exception on one question does not abort the run, it
     is recorded as an error case in the result JSON instead.

Scoring (correct/partial/incorrect) is NOT part of this script -- it
only logs raw data (which tool was called with which arguments, the
model's final answer, timings, errors). Interpreting the results is a
separate, manual step done afterwards.
"""

import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

import config
from question_catalog import QUESTIONS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


# ── MCP client part ──────────────────────────────────────────────────
#
# MCP over Streamable-HTTP is session-based: the server issues a
# session ID on the initialize call (header "Mcp-Session-Id") and
# expects it back on every following request in the same header --
# otherwise it responds 400 Bad Request.
#
# One session is established per test run and reused across all
# models/questions -- the session is a pure transport connection to
# the MCP server, independent of the (deliberately stateless) Ollama
# chat context per question.
_session_id: str | None = None


def _mcp_request(method: str, params: dict | None = None) -> dict:
    """Runs a single JSON-RPC request against the MCP server. Sends the
    Mcp-Session-Id received from a prior initialize call, once one is
    available. Raises on timeout/connection error -- the caller catches
    that and logs it as an error case instead of aborting the run."""
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

    # The session ID arrives on the initialize response -- from then on
    # it is sent on every further request in this run.
    returned_session_id = resp.headers.get("Mcp-Session-Id")
    if returned_session_id and _session_id is None:
        _session_id = returned_session_id
        logger.info("MCP session established: %s", _session_id)

    # notifications/initialized is a notification with no response body
    # (JSON-RPC notification) -- some servers reply with an empty
    # body/202 here, which is not an error and doesn't need JSON parsing.
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
    actual test run -- tool definitions are never duplicated in this
    script. Also establishes the MCP session reused for the whole run
    (see _session_id above)."""
    # MCP requires an initialize + notifications/initialized call
    # before tools/list.
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

    # One-off debug dump per run, so the exact tool format sent to
    # Ollama can be inspected without guesswork if tool-matching
    # behaves unexpectedly. Not required for normal use -- delete the
    # file or ignore it if you don't need it.
    debug_path = Path(config.OUTPUT_DIR) / "_debug_ollama_tools.json"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_text(json.dumps(ollama_tools, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Debug: tool format sent to Ollama written to %s", debug_path)

    return ollama_tools


def call_mcp_tool(name: str, arguments: dict) -> dict:
    """Runs a real tools/call against the MCP server (end-to-end, no
    simulation) and returns the raw result."""
    result = _mcp_request("tools/call", {"name": name, "arguments": arguments})
    return result.get("result", result)


def _parse_content_fallback_tool_call(content: str) -> dict | None:
    """Some models return an otherwise-correct tool call not in
    Ollama's native message.tool_calls field, but as plain JSON text in
    message.content (e.g. '{"name": ..., "arguments": {...}}').  Some
    downstream consumers tolerate/parse that automatically; a plain
    Ollama client does not, and the call would otherwise be lost as an
    empty final answer.

    Deliberately strict: content only counts as a tool-call candidate
    if, after strip(), it parses as a JSON object with exactly the keys
    "name" (str) and "arguments" (dict). Any deviation (not JSON, extra
    surrounding text, missing/different keys) returns None -- a normal
    text answer that happens to contain a JSON-looking fragment must
    not be misclassified as a tool call."""
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
    """A single Ollama /api/chat call, no streaming (simpler to parse;
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


# ── Per-question flow ────────────────────────────────────────────────

def run_question(model: str, question: dict, tools: list[dict]) -> dict:
    """Multi-turn loop for a single question against one model. Always
    returns a complete raw log record -- never a score/judgement."""
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
    if getattr(config, "SYSTEM_PROMPT", None):
        messages.append({"role": "system", "content": config.SYSTEM_PROMPT})
    messages.append({"role": "user", "content": question["text"]})
    start = time.monotonic()

    try:
        for turn in range(1, config.MAX_TOOL_TURNS + 1):
            record["turns_used"] = turn
            response = ollama_chat(model, messages, tools)

            # One-off debug dump of the RAW Ollama response, for the
            # very first question/turn of the whole run, to make it
            # possible to diagnose tool-matching or format problems
            # without further guesswork. Not required for normal use.
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
                except Exception as exc:  # noqa: BLE001 -- deliberately broad, error is logged, not swallowed
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
    except Exception as exc:  # noqa: BLE001 -- question is still logged, run continues
        record["error"] = f"Unexpected error: {exc}"

    record["duration_seconds"] = round(time.monotonic() - start, 3)
    record["timestamp_end"] = datetime.now(timezone.utc).isoformat()
    return record


# ── Main run ─────────────────────────────────────────────────────────

# Incremental checkpointing: one line per completed question, appended
# and flushed immediately after every run_question() call -- if the
# run is interrupted mid-way (crash, kill, power loss), everything up
# to the last question is preserved instead of losing it all at the
# final write_results() call. Fixed filename (not timestamped like the
# final result files below) -- that's what makes it findable as a
# resume source on the next start.
PROGRESS_PATH = Path(config.OUTPUT_DIR) / "mcp_llm_test_progress.jsonl"


def load_completed_keys(progress_path: Path) -> tuple[set[tuple[str, object]], list[dict]]:
    """Reads an existing progress file (if any) and returns: (1) the
    set of already-completed (model, question_id) keys to skip, (2)
    the already-loaded records themselves, so the final report stays
    complete even for a resumed run instead of only showing newly
    added questions. Broken/unreadable individual lines are skipped
    and logged, not a reason to abort the whole run -- resuming should
    be more robust than the problem it's meant to solve."""
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
            completed.add((record.get("model"), record.get("question_id")))
            records.append(record)

    if records:
        logger.info(
            "%d already-completed question(s) loaded from %s -- will be skipped",
            len(records), progress_path)
    return completed, records


def append_result(record: dict, progress_path: Path) -> None:
    """Appends a single record as a JSON line to the progress file and
    flushes immediately -- the goal is that the line is already on
    disk right after this call, not just sitting in Python's buffer."""
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
    lines = [f"# MCP LLM test run {run_id}", ""]
    for r in results:
        lines.append(f"## Model: {r['model']} -- Question {r['question_id']} (Round {r['round']})")
        lines.append(f"**Question:** {r['question_text']}")
        lines.append(f"**Expected tool:** {r['expected_tool']}")
        lines.append(f"**Duration:** {r['duration_seconds']}s, **Turns:** {r['turns_used']}")
        if r["error"]:
            lines.append(f"**ERROR:** {r['error']}")
        if r["tool_calls"]:
            lines.append("**Tool calls:**")
            for tc in r["tool_calls"]:
                lines.append(f"- `{tc['name']}({tc['arguments']})` -- {tc['duration_seconds']}s"
                              + (f" -- ERROR: {tc['error']}" if tc["error"] else ""))
        else:
            lines.append("**Tool calls:** none")
        lines.append(f"**Final answer:** {r['final_answer']}")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return json_path, md_path


def main() -> None:
    logger.info("Fetching tool list from MCP server (%s) ...", config.MCP_URL)
    try:
        tools = fetch_mcp_tools()
    except Exception as exc:
        logger.error("Could not load tool list -- is the MCP server running? Error: %s", exc)
        sys.exit(1)
    logger.info("%d tools loaded: %s", len(tools), [t["function"]["name"] for t in tools])

    completed_keys, results = load_completed_keys(PROGRESS_PATH)
    total = len(config.MODEL_LIST) * len(QUESTIONS)
    done = 0

    for model in config.MODEL_LIST:
        logger.info("=== Model: %s ===", model)
        for question in QUESTIONS:
            done += 1
            key = (model, question["id"])
            if key in completed_keys:
                logger.info("[%d/%d] Question %s: already done (from %s) -- skipped",
                            done, total, question["id"], PROGRESS_PATH.name)
                continue
            logger.info("[%d/%d] Question %s: %s", done, total, question["id"], question["text"])
            record = run_question(model, question, tools)
            if record["error"]:
                logger.warning("  -> Error: %s", record["error"])
            else:
                logger.info("  -> %d tool call(s), %.1fs", len(record["tool_calls"]), record["duration_seconds"])
            results.append(record)
            append_result(record, PROGRESS_PATH)

    output_dir = Path(config.OUTPUT_DIR)
    json_path, md_path = write_results(results, output_dir)
    logger.info("Done. Results written to:")
    logger.info("  %s", json_path)
    logger.info("  %s", md_path)


if __name__ == "__main__":
    main()

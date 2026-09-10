#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
mcp-llm-tester/config.py
Configuration for mcp_llm_test_runner.py -- model list, server URLs,
timeouts. Plain values only, no logic.
"""

# Which Ollama models are tested when running via the CLI entry point
# (main() in mcp_llm_test_runner.py, launched via run_mcp_llm_test.bat).
# Names must match exactly what "ollama list" shows.
#
# Note: when running via the GUI (mcp_test_gui.py), the model list is
# instead fetched dynamically from Ollama itself (GET /api/tags, see
# fetch_ollama_models()) -- this constant is NOT read in that case. It
# only matters for the plain CLI run without a GUI.
MODEL_LIST = [
    "qwen2.5-coder:7b",
    "qwen2.5-coder:14b",
]

# Ollama's default port -- normally left as-is.
OLLAMA_URL = "http://localhost:11434"

# MCP server URL. The server must already be running before you start
# this tool -- this script is a client only, it does not start or
# manage the server. Point this at whatever MCP endpoint you want to
# test tool-calling against.
MCP_URL = "http://127.0.0.1:8756/mcp"

# Timeout per individual Ollama call (seconds). Larger local models can
# take well over a minute for a single response -- keep this generous
# so a slow-but-working model isn't wrongly logged as an error.
OLLAMA_TIMEOUT_SECONDS = 180

# Timeout per individual MCP tools/call (seconds). Kept noticeably
# shorter than the Ollama timeout, since a hanging MCP server is a
# distinct, separately diagnosable failure mode.
MCP_CALL_TIMEOUT_SECONDS = 30

# Safety limit against infinite loops: maximum number of tool-call
# rounds per question before the run gives up and logs "turn limit
# reached" for that question.
MAX_TOOL_TURNS = 5

# Minimal system prompt: pure flow control, deliberately NO tool
# selection / parameter / data hints -- that would bias the actual
# tool-matching test goal of the question catalog. Background: without
# any system prompt, some models kept re-issuing an identical tool call
# instead of giving a final text answer after already having the
# result (observed loop -- tool matching itself was already correct,
# only the conversational close was missing).
# Set to None/"" to restore the old "no system prompt at all" behavior
# for a comparison run -- no code change needed.
SYSTEM_PROMPT = (
    "You are an assistant with access to tools. When you call a tool "
    "and receive its result, use that result to answer the user's "
    "question in natural language. Do not call the same tool again "
    "with the same arguments after you already have its result."
)

# Output folder for JSON/MD results (relative to the script's working
# directory) -- used only by the plain CLI entry point (main()). The
# GUI writes into its own per-run folder instead, see mcp_test_gui.py.
OUTPUT_DIR = "results"

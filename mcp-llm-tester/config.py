#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
mcp-llm-tester/config.py
Configuration for mcp_llm_test_runner.py -- model list, server URLs,
timeouts. Plain values only, no logic.
"""

# Which Ollama models are tested, one after another. Names must match
# exactly what "ollama list" shows.
MODEL_LIST = [
    "qwen2.5-coder:14b",
    "qwen2.5-coder:7b",
]

# Ollama's default port -- normally left as-is.
OLLAMA_URL = "http://localhost:11434"

# MCP server URL. The server must already be running before you start
# this tool -- this script is a client only, it does not start or
# manage the server.
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

# Minimal system prompt: pure flow control, deliberately NOT hinting at
# tool choice, parameters, or data -- that would bias the tool-matching
# behaviour this runner is meant to measure. Some models loop
# (repeating the same tool call instead of giving a final text answer)
# if there is no system prompt at all; this line is enough to prevent
# that without steering tool selection.
# Set to None or "" to fully disable the system prompt for a comparison
# run -- no code change needed.
SYSTEM_PROMPT = (
    "You are an assistant with access to tools. When you call a tool "
    "and receive its result, use that result to answer the user's "
    "question in natural language. Do not call the same tool again "
    "with the same arguments after you already have its result."
)

# Output folder for JSON/MD results (relative to the script's working
# directory).
OUTPUT_DIR = "results"

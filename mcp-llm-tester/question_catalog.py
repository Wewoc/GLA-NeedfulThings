#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
mcp-llm-tester/question_catalog.py

Blank template. This file defines the QUESTIONS list that
mcp_llm_test_runner.py imports and works through, one entry per
question, against every model in config.MODEL_LIST.

Copy this file (or edit it in place) and replace the placeholder
entries below with your own questions against your own MCP server's
tools. The runner does not care what your tools are called or what
they do -- it only needs each question to follow the schema described
here.

── Schema per entry ─────────────────────────────────────────────────

Required keys:
  "id"            -- str, unique per entry. Used as part of the
                      (model, question_id) key for resuming an
                      interrupted run, and to label results.
  "round"         -- int (or any JSON-serialisable value). Purely a
                      label for your own grouping/filtering of results;
                      the runner does not act on it.
  "text"          -- str, the exact prompt sent to the model as the
                      user message. Can be a natural-language question
                      or a literal "tool_name argument" style prompt,
                      depending on what you want to test.
  "expected_tool" -- str or None. Metadata only -- the runner never
                      checks this automatically, it is written into
                      the result records for your own manual scoring
                      afterwards. Use None for questions where you
                      expect the model to answer WITHOUT calling any
                      tool.

Optional keys (all purely descriptive, passed through into the result
records untouched, never interpreted by the runner):
  "field"           -- str, e.g. which data field or capability this
                        question targets, if that grouping matters for
                        your evaluation.
  "variant"         -- str, e.g. "direct" / "indirect" / "typo" if you
                        want to test how robust tool-matching is to
                        how the request is phrased.
  "note"            -- str, free-text reminder to yourself for later
                        evaluation.
  "expected_params" -- dict, the arguments you'd expect a correct tool
                        call to use. Not checked automatically -- for
                        your own comparison against the logged
                        "arguments" in each tool call record.

── Placeholder entries ──────────────────────────────────────────────

Replace these with real questions against your own MCP tools before
running the tool. They are intentionally inert (no real tool will
match "your_tool_name") so an unmodified copy of this file fails
loudly and obviously rather than silently testing nothing.
"""

QUESTIONS = [

    {
        "id": "example_1",
        "round": 1,
        "text": "your_tool_name some_argument_value",
        "expected_tool": "your_tool_name",
        "note": "Direct-style prompt: tool name and argument spelled "
                "out explicitly in the text.",
    },

    {
        "id": "example_2",
        "round": 1,
        "text": "Phrase the same request in natural language here, "
                "without naming the tool or its parameters directly.",
        "expected_tool": "your_tool_name",
        "field": "some_field_or_capability",
        "variant": "indirect",
        "note": "Tests whether the model picks the right tool and "
                "arguments from a natural-language request alone.",
        "expected_params": {"some_argument": "expected_value"},
    },

    {
        "id": "example_3",
        "round": 1,
        "text": "A question that should be answerable without calling "
                "any tool at all.",
        "expected_tool": None,
        "note": "Use expected_tool: None to flag questions where a "
                "tool call would be a false positive -- useful for "
                "checking whether a system prompt makes a model "
                "trigger-happy about calling tools it doesn't need.",
    },

]

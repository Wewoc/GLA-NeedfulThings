#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
mcp-llm-tester/question_catalog.py
Blank template showing the schema mcp_llm_test_runner.py expects from
a question catalog. This is NOT a working catalog -- replace the
placeholder entries below with your own questions before running a
real test.

Required fields per question:
  id             -- unique string, used as part of the resume key
                     (model, id) and in filenames/logs.
  round          -- int or string, free-form grouping label of your
                     choosing (e.g. batch number, test phase).
  text           -- the exact user message sent to the model.
  expected_tool  -- name of the tool you expect the model to call, or
                     None if you expect no tool call at all. Purely a
                     metadata field for your own manual evaluation
                     afterwards -- the runner never grades anything
                     itself.

Optional fields (used by nothing in the runner itself, but commonly
useful for your own analysis afterwards):
  expected_params -- dict of parameters you expect the tool call to
                      use, for comparison against what actually got
                      called.
  field           -- free-form label if your questions are organized
                      around specific data fields/domains.
  variant         -- free-form label if you test the same underlying
                      question in different phrasings (e.g. "direct",
                      "indirect", "typo").
  note            -- any free-text note for yourself.

Every catalog file must export a QUESTIONS list of such dicts.

For the CLI entry point (main() in mcp_llm_test_runner.py, run via
run_mcp_llm_test.bat), this file is used directly as the one and only
catalog.

For the GUI (mcp_test_gui.py), catalogs are instead discovered from a
"question_catalog/" subfolder next to this file -- any file matching
question_catalog*.py in that subfolder shows up as a selectable
catalog. Copy/adapt this template there if you want multiple catalogs
selectable in the GUI.
"""

QUESTIONS = [
    {
        "id": "example-1",
        "round": 1,
        "text": "your_tool_name some_argument",
        "expected_tool": "your_tool_name",
        "expected_params": {"some_argument": "some_value"},
        "variant": "direct",
        "note": "TODO: replace with a real question before running this catalog.",
    },
    {
        "id": "example-2",
        "round": 1,
        "text": "Phrase the same request in natural language, without naming the tool.",
        "expected_tool": "your_tool_name",
        "variant": "indirect",
        "note": "TODO: replace with a real question before running this catalog.",
    },
]

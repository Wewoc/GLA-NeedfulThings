#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
mcp-llm-tester/mcp_test_gui.py
Tkinter GUI for mcp_llm_test_runner.py -- pick question catalogs,
Ollama models, and system prompt variants by clicking, start/stop/
resume a test run, live log display, progress display.

Builds on run_test_session() from mcp_llm_test_runner.py (see there
for the actual run logic -- this file contains GUI code only, no test
run logic).

Threading model:
  The actual test run (run_test_session()) runs in its own worker
  thread, NEVER on the Tkinter mainloop thread -- otherwise the GUI
  would freeze during every Ollama call (up to OLLAMA_TIMEOUT_SECONDS).
  Communication from the worker thread back to the GUI goes
  exclusively through a thread-safe queue.Queue: the worker puts log
  lines and progress events into it, the GUI polls the queue via
  root.after(...) on the mainloop thread. Tkinter widgets may only be
  modified from the mainloop thread -- so the worker thread never
  touches any widget directly.

Stop semantics:
  Stop sets a threading.Event. The worker checks it after every
  completed question (see run_test_session()) -- the currently
  running question is always finished first, only then does the run
  stop cleanly. After a stop, the run folder stays "resumable": the
  "Resume run" button becomes active and continues on the same folder
  on the next click (resume=True). This association is only cleared
  by "Start new run".
"""

import json
import queue
import re
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import mcp_llm_test_runner as runner

CATALOG_DIR = Path(__file__).parent / "question_catalog"
PROMPT_DIR = Path(__file__).parent / "system_prompts"
RESULTS_DIR = Path(__file__).parent / "results"

_NO_SYSTEM_PROMPT_LABEL = "(no system prompt)"


# ── Hilfsfunktionen (reine Logik, kein Tkinter) ─────────────────────

def _highest_lauf_dir(results_dir: Path) -> tuple[int, Path] | None:
    """Finds the lauf_<nr>_*-folder with the highest number in
    results_dir. Returns (nr, path), or None if no lauf_*-folder
    exists or results_dir doesn't exist. Shared scan basis for
    next_lauf_nr() and find_resumable_run() -- both need the same
    'highest number' lookup, once to suggest the next free number,
    once to check whether exactly the last run is still open/
    resumable."""
    if not results_dir.exists():
        return None
    highest_nr = None
    highest_path = None
    for entry in results_dir.iterdir():
        if not entry.is_dir():
            continue
        match = re.match(r"^lauf_(\d+)_", entry.name)
        if match:
            nr = int(match.group(1))
            if highest_nr is None or nr > highest_nr:
                highest_nr = nr
                highest_path = entry
    if highest_nr is None:
        return None
    return highest_nr, highest_path


def next_lauf_nr(results_dir: Path) -> int:
    """Returns the highest found lauf_<nr>_*-number + 1. No counter
    kept in a separate state file -- derived directly from the actual
    folder state, so it can't drift out of sync. Returns 1 if no
    lauf_*-folders exist yet, or results_dir doesn't exist yet."""
    found = _highest_lauf_dir(results_dir)
    return (found[0] + 1) if found else 1


def find_resumable_run(results_dir: Path) -> Path | None:
    """Checks ONLY the most recently created lauf_<nr>_*-folder
    (highest number, same lookup as next_lauf_nr()) -- not every
    existing run folder. Counts as 'open'/resumable if it contains a
    mcp_llm_test_progress.jsonl but NO mcp_llm_test_done.marker next
    to it (see the write_results() call sites in
    mcp_llm_test_runner.py -- the marker is set only on genuine,
    regular run completion, NOT on a stop, even though a stop also
    writes a JSON/MD snapshot. A plain JSON-existence check would
    therefore wrongly treat a deliberately stopped, incomplete run as
    finished).

    Returns None if no lauf_*-folder exists, or if the last folder was
    either never started (no progress.jsonl) or already fully
    completed (marker present). Deliberately does NOT search across
    multiple older run folders -- only the most recent one counts."""
    found = _highest_lauf_dir(results_dir)
    if found is None:
        return None
    _, lauf_path = found

    progress_path = lauf_path / "mcp_llm_test_progress.jsonl"
    if not progress_path.exists():
        return None

    if (lauf_path / "mcp_llm_test_done.marker").exists():
        return None

    return lauf_path


_LAUF_ORDNER_PATTERN = re.compile(r"^lauf_(\d+)_(\d{8})_(.*)$")


def parse_lauf_ordner_name(name: str) -> tuple[str, str, str] | None:
    """Splits a folder name following the scheme
    lauf_<nr>_<date>_<rest> back into the three GUI field values
    (nr, date, rest). <rest> may itself contain underscores.
    Returns None if the name doesn't follow this scheme exactly (e.g.
    older, manually differently-named folders predating the GUI) --
    in that case the folder is simply ignored for pre-filling the
    resume fields, which is harmless since find_resumable_run() only
    ever looks at the most recent folder anyway."""
    match = _LAUF_ORDNER_PATTERN.match(name)
    if match is None:
        return None
    nr, datum, rest = match.groups()
    return nr, datum, rest


def build_lauf_ordner_name(nr: str, datum: str, freitext: str) -> str:
    """Assembles the run folder name following the scheme
    lauf_<nr>_<date>_<freitext>. nr/date come from the (pre-filled but
    editable) GUI fields, freitext is the part entered by hand (e.g.
    'V1719_health_fix3')."""
    nr = nr.strip()
    datum = datum.strip()
    freitext = freitext.strip()
    parts = [p for p in ["lauf", nr, datum, freitext] if p]
    return "_".join(parts)


def format_elapsed(seconds: float) -> str:
    """Formats a number of seconds as mm:ss for the elapsed-time display."""
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


# ── GUI ──────────────────────────────────────────────────────────────

class McpTestGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("MCP-LLM Test Runner")
        self.root.geometry("1000x700")

        # Run-time state (not Tkinter variables, since some of it is
        # read/set from the worker thread -- access exclusively via
        # the queue, see the class docstring above).
        self._catalog_paths_all: list[Path] = []
        self._catalog_paths: list[Path] = []
        self._selected_catalogs: list[Path] = []
        self._model_names_all: list[str] = []
        self._selected_model_names: list[str] = []
        self._prompt_entries_all: list[tuple[str, str]] = []
        self._prompt_display_all: list[str] = []
        self._prompt_entries: list[tuple[str, str]] = []
        self._selected_prompt_names: list[str] = []
        self._event_queue: "queue.Queue[dict]" = queue.Queue()
        self._stop_event: threading.Event | None = None
        self._worker_thread: threading.Thread | None = None
        self._run_start_time: float | None = None
        self._active_output_dir: Path | None = None
        self._resume_available = False
        self._console_log_path: Path | None = None

        self._build_widgets()
        self._reload_catalogs()
        self._reload_models()
        self._reload_system_prompts()
        self._suggest_lauf_felder()
        self._check_resumable_run()
        self._poll_queue()

    # ── Widget layout ────────────────────────────────────────────────

    def _build_widgets(self) -> None:
        # Top row: two selection lists side by side
        selection_frame = tk.Frame(self.root)
        selection_frame.pack(fill="both", expand=True, padx=10, pady=(10, 5))

        # Catalogs (left)
        catalog_frame = tk.LabelFrame(selection_frame, text="Question catalogs (click to multi-select)")
        catalog_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        self.catalog_listbox = tk.Listbox(catalog_frame, selectmode=tk.MULTIPLE, exportselection=False)
        self.catalog_listbox.pack(fill="both", expand=True, padx=5, pady=5)
        self.catalog_listbox.bind("<<ListboxSelect>>", self._on_catalog_browse_select)

        catalog_filter_frame = tk.Frame(catalog_frame)
        catalog_filter_frame.pack(fill="x", padx=5, pady=(0, 5))
        self.catalog_filter_var = tk.StringVar()
        self.catalog_filter_entry = tk.Entry(catalog_filter_frame, textvariable=self.catalog_filter_var)
        self.catalog_filter_entry.pack(side="left", fill="x", expand=True)
        self.catalog_filter_var.trace_add("write", lambda *_: self._apply_catalog_filter())
        self.catalog_reload_button = tk.Button(
            catalog_filter_frame, text="Reload list", command=self._reload_catalogs)
        self.catalog_reload_button.pack(side="left", padx=(5, 0))

        tk.Label(catalog_frame, text="Selected (click to remove):").pack(
            anchor="w", padx=5, pady=(0, 0))
        self.catalog_selected_listbox = tk.Listbox(catalog_frame, height=4, exportselection=False)
        self.catalog_selected_listbox.pack(fill="x", padx=5, pady=(0, 5))
        self.catalog_selected_listbox.bind("<<ListboxSelect>>", self._on_catalog_selected_select)

        # Models (right)
        model_frame = tk.LabelFrame(selection_frame, text="Ollama models (click to multi-select)")
        model_frame.pack(side="left", fill="both", expand=True, padx=(5, 0))

        self.model_listbox = tk.Listbox(model_frame, selectmode=tk.MULTIPLE, exportselection=False)
        self.model_listbox.pack(fill="both", expand=True, padx=5, pady=5)
        self.model_listbox.bind("<<ListboxSelect>>", self._on_model_browse_select)

        model_filter_frame = tk.Frame(model_frame)
        model_filter_frame.pack(fill="x", padx=5, pady=(0, 5))
        self.model_filter_var = tk.StringVar()
        self.model_filter_entry = tk.Entry(model_filter_frame, textvariable=self.model_filter_var)
        self.model_filter_entry.pack(side="left", fill="x", expand=True)
        self.model_filter_var.trace_add("write", lambda *_: self._apply_model_filter())
        self.model_reload_button = tk.Button(
            model_filter_frame, text="Query Ollama again", command=self._reload_models)
        self.model_reload_button.pack(side="left", padx=(5, 0))

        tk.Label(model_frame, text="Selected (click to remove):").pack(
            anchor="w", padx=5, pady=(0, 0))
        self.model_selected_listbox = tk.Listbox(model_frame, height=4, exportselection=False)
        self.model_selected_listbox.pack(fill="x", padx=5, pady=(0, 5))
        self.model_selected_listbox.bind("<<ListboxSelect>>", self._on_model_selected_select)

        # System prompts (right, third column)
        prompt_frame = tk.LabelFrame(selection_frame, text="System prompts (click to multi-select)")
        prompt_frame.pack(side="left", fill="both", expand=True, padx=(5, 0))

        self.prompt_listbox = tk.Listbox(prompt_frame, selectmode=tk.MULTIPLE, exportselection=False)
        self.prompt_listbox.pack(fill="both", expand=True, padx=5, pady=5)
        self.prompt_listbox.bind("<<ListboxSelect>>", self._on_prompt_browse_select)

        prompt_filter_frame = tk.Frame(prompt_frame)
        prompt_filter_frame.pack(fill="x", padx=5, pady=(0, 5))
        self.prompt_filter_var = tk.StringVar()
        self.prompt_filter_entry = tk.Entry(prompt_filter_frame, textvariable=self.prompt_filter_var)
        self.prompt_filter_entry.pack(side="left", fill="x", expand=True)
        self.prompt_filter_var.trace_add("write", lambda *_: self._apply_prompt_filter())
        self.prompt_reload_button = tk.Button(
            prompt_filter_frame, text="Reload list", command=self._reload_system_prompts)
        self.prompt_reload_button.pack(side="left", padx=(5, 0))

        tk.Label(prompt_frame, text="Selected (click to remove):").pack(
            anchor="w", padx=5, pady=(0, 0))
        self.prompt_selected_listbox = tk.Listbox(prompt_frame, height=4, exportselection=False)
        self.prompt_selected_listbox.pack(fill="x", padx=5, pady=(0, 5))
        self.prompt_selected_listbox.bind("<<ListboxSelect>>", self._on_prompt_selected_select)

        # Run folder fields
        lauf_frame = tk.LabelFrame(self.root, text="Run folder")
        lauf_frame.pack(fill="x", padx=10, pady=5)

        tk.Label(lauf_frame, text="No.:").grid(row=0, column=0, sticky="e", padx=(5, 2), pady=5)
        self.nr_var = tk.StringVar()
        self.nr_entry = tk.Entry(lauf_frame, textvariable=self.nr_var, width=6)
        self.nr_entry.grid(row=0, column=1, sticky="w", pady=5)
        self.nr_var.trace_add("write", lambda *_: self._update_preview())

        tk.Label(lauf_frame, text="Date:").grid(row=0, column=2, sticky="e", padx=(10, 2), pady=5)
        self.datum_var = tk.StringVar()
        self.datum_entry = tk.Entry(lauf_frame, textvariable=self.datum_var, width=10)
        self.datum_entry.grid(row=0, column=3, sticky="w", pady=5)
        self.datum_var.trace_add("write", lambda *_: self._update_preview())

        tk.Label(lauf_frame, text="Rest (e.g. V1719_some_label):").grid(
            row=0, column=4, sticky="e", padx=(10, 2), pady=5)
        self.freitext_var = tk.StringVar()
        self.freitext_entry = tk.Entry(lauf_frame, textvariable=self.freitext_var, width=30)
        self.freitext_entry.grid(row=0, column=5, sticky="w", padx=(0, 5), pady=5)
        self.freitext_var.trace_add("write", lambda *_: self._update_preview())

        self.preview_label = tk.Label(lauf_frame, text="", font=("TkDefaultFont", 9, "italic"), fg="#555555")
        self.preview_label.grid(row=1, column=0, columnspan=6, sticky="w", padx=5, pady=(0, 5))

        # Steuerung
        control_frame = tk.Frame(self.root)
        control_frame.pack(fill="x", padx=10, pady=5)

        self.start_button = tk.Button(control_frame, text="Start new run",
                                       command=self._on_start_new, bg="#2e7d32", fg="white")
        self.start_button.pack(side="left", padx=(0, 5))

        self.stop_button = tk.Button(control_frame, text="Stop", command=self._on_stop,
                                      state="disabled", bg="#c62828", fg="white")
        self.stop_button.pack(side="left", padx=5)

        self.resume_button = tk.Button(control_frame, text="Resume run",
                                        command=self._on_resume, state="disabled")
        self.resume_button.pack(side="left", padx=5)

        # Fortschritt
        progress_frame = tk.Frame(self.root)
        progress_frame.pack(fill="x", padx=10, pady=(5, 0))

        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        self.progress_bar.pack(fill="x")

        self.status_label = tk.Label(progress_frame, text="Ready.", justify="left", anchor="w")
        self.status_label.pack(fill="x", pady=(5, 0))

        # Log
        log_frame = tk.LabelFrame(self.root, text="Console")
        log_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.log_text = ScrolledText(log_frame, state="disabled", height=15, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.log_text.tag_configure("log_error", foreground="#c62828")
        self.log_text.tag_configure("log_success", foreground="#2e7d32")
        self.log_text.tag_configure("log_slow", foreground="#f57f17")
        self.log_text.tag_configure("log_section", background="#1565c0", foreground="white")

    # ── Populate catalog/model lists ─────────────────────────────────

    def _reload_catalogs(self) -> None:
        self._catalog_paths_all = runner.discover_question_catalogs(CATALOG_DIR)
        if not self._catalog_paths_all:
            self._append_log(f"No question_catalog*.py files found in {CATALOG_DIR}.")
        # Selected catalogs that no longer exist after reloading are
        # silently dropped from the selection -- everything else is
        # kept, regardless of the current filter text.
        self._selected_catalogs = [p for p in self._selected_catalogs if p in self._catalog_paths_all]
        self._apply_catalog_filter()
        self._refresh_selected_catalogs()

    def _apply_catalog_filter(self) -> None:
        """Filters the fully loaded catalog list by a free-text
        substring (case-insensitive) on the file name and rebuilds the
        listbox from it. self._catalog_paths is afterwards exactly the
        displayed/indexed subset -- _on_catalog_browse_select() indexes
        into it via the listbox click, never into the full list."""
        query = self.catalog_filter_var.get().strip().lower()
        self._catalog_paths = [
            p for p in self._catalog_paths_all if not query or query in p.name.lower()
        ]
        self.catalog_listbox.delete(0, tk.END)
        for path in self._catalog_paths:
            self.catalog_listbox.insert(tk.END, path.name)

    def _on_catalog_browse_select(self, event=None) -> None:
        """A click on an entry in the (possibly filtered) browse list
        toggles it in the persistent selection -- not present -> add,
        present -> remove. The native listbox highlight is cleared
        again immediately afterwards, since the selection state is
        shown exclusively via self._selected_catalogs and the separate
        "Selected" list -- so nothing is lost when the filter changes
        (which rebuilds the browse list from scratch)."""
        sel = self.catalog_listbox.curselection()
        if not sel:
            return
        path = self._catalog_paths[sel[0]]
        if path in self._selected_catalogs:
            self._selected_catalogs.remove(path)
        else:
            self._selected_catalogs.append(path)
        self.catalog_listbox.selection_clear(0, tk.END)
        self._refresh_selected_catalogs()

    def _on_catalog_selected_select(self, event=None) -> None:
        """A click on an entry in the "Selected" list removes it --
        the reliable way back if the entry is currently hidden from the
        browse list by the filter."""
        sel = self.catalog_selected_listbox.curselection()
        if not sel:
            return
        del self._selected_catalogs[sel[0]]
        self._refresh_selected_catalogs()

    def _refresh_selected_catalogs(self) -> None:
        self.catalog_selected_listbox.delete(0, tk.END)
        for path in self._selected_catalogs:
            self.catalog_selected_listbox.insert(tk.END, path.name)

    def _reload_models(self) -> None:
        try:
            models = runner.fetch_ollama_models()
        except Exception as exc:
            self._append_log(f"Could not query Ollama models: {exc}")
            self._model_names_all = []
            self._apply_model_filter()
            self._selected_model_names = []
            self._refresh_selected_models()
            return
        self._model_names_all = sorted(models)
        if not models:
            self._append_log("Ollama reports no installed models.")
        # Selected models Ollama no longer reports are silently dropped
        # from the selection.
        self._selected_model_names = [m for m in self._selected_model_names if m in self._model_names_all]
        self._apply_model_filter()
        self._refresh_selected_models()

    def _apply_model_filter(self) -> None:
        """Filters the fully loaded model list by a free-text substring
        (case-insensitive), e.g. "8b" or "en" (matches "qwen..." among
        others). No new Ollama call -- pure display filtering on names
        already loaded."""
        query = self.model_filter_var.get().strip().lower()
        shown = [n for n in self._model_names_all if not query or query in n.lower()]
        self.model_listbox.delete(0, tk.END)
        for name in shown:
            self.model_listbox.insert(tk.END, name)

    def _on_model_browse_select(self, event=None) -> None:
        """Same as _on_catalog_browse_select(), for models."""
        sel = self.model_listbox.curselection()
        if not sel:
            return
        name = self.model_listbox.get(sel[0])
        if name in self._selected_model_names:
            self._selected_model_names.remove(name)
        else:
            self._selected_model_names.append(name)
        self.model_listbox.selection_clear(0, tk.END)
        self._refresh_selected_models()

    def _on_model_selected_select(self, event=None) -> None:
        sel = self.model_selected_listbox.curselection()
        if not sel:
            return
        del self._selected_model_names[sel[0]]
        self._refresh_selected_models()

    def _refresh_selected_models(self) -> None:
        self.model_selected_listbox.delete(0, tk.END)
        for name in self._selected_model_names:
            self.model_selected_listbox.insert(tk.END, name)

    def _reload_system_prompts(self) -> None:
        """Loads the full prompt list. Index 0 is always the synthetic
        "(no system prompt)" entry (no file backing, empty prompt text)
        -- covers the no-prompt comparison case without needing an
        empty .md file for it. After that, every system_prompt*.md file
        from PROMPT_DIR, alphabetically. self._prompt_display_all holds
        the actually displayed text per entry in parallel (file name
        rather than stem) -- the filter matches against this display
        text, not the internal variant name."""
        self._prompt_entries_all = [(_NO_SYSTEM_PROMPT_LABEL, "")]
        self._prompt_display_all = [_NO_SYSTEM_PROMPT_LABEL]

        for path in runner.discover_system_prompts(PROMPT_DIR):
            try:
                text = runner.load_system_prompt(path)
            except OSError as exc:
                self._append_log(f"Could not read {path.name}: {exc}")
                continue
            self._prompt_entries_all.append((path.stem, text))
            self._prompt_display_all.append(path.name)

        if len(self._prompt_entries_all) == 1:
            self._append_log(f"No system_prompt*.md files found in {PROMPT_DIR}.")

        # Selected prompt variants that no longer exist after reloading
        # are silently dropped from the selection.
        known_names = {entry[0] for entry in self._prompt_entries_all}
        self._selected_prompt_names = [n for n in self._selected_prompt_names if n in known_names]

        self._apply_prompt_filter()
        self._refresh_selected_prompts()

    def _apply_prompt_filter(self) -> None:
        """Filters the fully loaded prompt list by a free-text substring
        (case-insensitive) on the display text and rebuilds the listbox
        from it. self._prompt_entries is afterwards exactly the
        displayed/indexed subset, from which _on_prompt_browse_select()
        picks the variant name for the selection on click."""
        query = self.prompt_filter_var.get().strip().lower()
        filtered = [
            (entry, display)
            for entry, display in zip(self._prompt_entries_all, self._prompt_display_all)
            if not query or query in display.lower()
        ]
        self._prompt_entries = [entry for entry, _display in filtered]
        self.prompt_listbox.delete(0, tk.END)
        for _entry, display in filtered:
            self.prompt_listbox.insert(tk.END, display)

    def _on_prompt_browse_select(self, event=None) -> None:
        """Same as _on_catalog_browse_select(), for prompt variants.
        Toggles by variant name (self._prompt_entries[i][0]), not by
        display text -- the name is the stable identity, the display
        text (file name) only serves the listbox."""
        sel = self.prompt_listbox.curselection()
        if not sel:
            return
        name = self._prompt_entries[sel[0]][0]
        if name in self._selected_prompt_names:
            self._selected_prompt_names.remove(name)
        else:
            self._selected_prompt_names.append(name)
        self.prompt_listbox.selection_clear(0, tk.END)
        self._refresh_selected_prompts()

    def _on_prompt_selected_select(self, event=None) -> None:
        sel = self.prompt_selected_listbox.curselection()
        if not sel:
            return
        del self._selected_prompt_names[sel[0]]
        self._refresh_selected_prompts()

    def _refresh_selected_prompts(self) -> None:
        display_by_name = dict(zip(
            (entry[0] for entry in self._prompt_entries_all), self._prompt_display_all))
        self.prompt_selected_listbox.delete(0, tk.END)
        for name in self._selected_prompt_names:
            self.prompt_selected_listbox.insert(tk.END, display_by_name.get(name, name))

    def _suggest_lauf_felder(self) -> None:
        self.nr_var.set(str(next_lauf_nr(RESULTS_DIR)))
        self.datum_var.set(datetime.now().strftime("%Y%m%d"))
        self._update_preview()

    def _check_resumable_run(self) -> None:
        """Checks at GUI startup whether the most recently created run
        folder is still open (progress.jsonl present but no
        mcp_llm_test_done.marker -- see find_resumable_run()). This
        covers the case where the GUI was closed, or the machine
        restarted, while a run was still active or after a stop (stop
        state should survive GUI restarts). If found, the Nr./Date/
        Rest fields are reset to the found folder (overwriting the
        NEXT free number just suggested by _suggest_lauf_felder() with
        the number of the open run), the resume button is activated,
        AND the three "Selected" lists are pre-filled with that run's
        original catalog/model/prompt selection (see
        _load_or_derive_run_selection()) -- otherwise you'd have to
        remember it by hand after every GUI restart. If nothing is
        found, everything stays as suggested by _suggest_lauf_felder(),
        no further action."""
        resumable_dir = find_resumable_run(RESULTS_DIR)
        if resumable_dir is None:
            return

        parsed = parse_lauf_ordner_name(resumable_dir.name)
        if parsed is not None:
            nr, datum, rest = parsed
            self.nr_var.set(nr)
            self.datum_var.set(datum)
            self.freitext_var.set(rest)
            self._update_preview()

        self._active_output_dir = resumable_dir
        self._console_log_path = resumable_dir / "console.log"
        self._resume_available = True
        self.resume_button.config(state="normal")

        saved = self._load_or_derive_run_selection(resumable_dir)
        catalog_by_name = {p.name: p for p in self._catalog_paths_all}
        self._selected_catalogs = [
            catalog_by_name[n] for n in saved.get("catalogs", []) if n in catalog_by_name
        ]
        model_set = set(self._model_names_all)
        self._selected_model_names = [n for n in saved.get("models", []) if n in model_set]
        prompt_name_set = {entry[0] for entry in self._prompt_entries_all}
        self._selected_prompt_names = [n for n in saved.get("prompts", []) if n in prompt_name_set]
        self._refresh_selected_catalogs()
        self._refresh_selected_models()
        self._refresh_selected_prompts()

        self._append_log(
            f"Incomplete run found: {resumable_dir.name} -- "
            "'Resume run' is available. Selection restored: "
            f"{len(self._selected_catalogs)} catalog(s), "
            f"{len(self._selected_model_names)} model(s), "
            f"{len(self._selected_prompt_names)} prompt variant(s)."
        )

    def _load_or_derive_run_selection(self, lauf_path: Path) -> dict:
        """Reads the gui_selection.json written at run start (see
        _start_run()) and returns it. If missing -- a run folder from
        before this file existed -- falls back to deriving it from the
        progress file: which catalogs/models/prompt variants actually
        appear there. That only covers combinations already reached,
        not necessarily the full original selection (combinations the
        run hadn't gotten to yet won't appear in the progress file) --
        but it's better than no pre-fill at all."""
        settings_path = lauf_path / "gui_selection.json"
        if settings_path.exists():
            try:
                return json.loads(settings_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self._append_log(f"Could not read saved selection: {exc}")

        catalogs: list[str] = []
        models: list[str] = []
        prompts: list[str] = []
        seen_c, seen_m, seen_p = set(), set(), set()
        progress_path = lauf_path / "mcp_llm_test_progress.jsonl"
        if progress_path.exists():
            with progress_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    c, m, p = record.get("catalog"), record.get("model"), record.get("prompt_variant")
                    if c and c not in seen_c:
                        seen_c.add(c)
                        catalogs.append(c)
                    if m and m not in seen_m:
                        seen_m.add(m)
                        models.append(m)
                    if p and p not in seen_p:
                        seen_p.add(p)
                        prompts.append(p)
        return {"catalogs": catalogs, "models": models, "prompts": prompts}

    def _update_preview(self) -> None:
        name = build_lauf_ordner_name(self.nr_var.get(), self.datum_var.get(), self.freitext_var.get())
        self.preview_label.config(text=f"Folder name: {name}")

    # ── Log-Ausgabe (nur aus dem Mainloop-Thread aufrufen) ───────────

    def _append_log(self, line: str) -> None:
        self.log_text.config(state="normal")
        # "end-1c", not tk.END: Tk always keeps an invisible trailing
        # newline at the end of the text, so tk.END already points one
        # line "too far" before every insert -- end-1c is exactly where
        # insert(tk.END, ...) actually writes.
        line_start = self.log_text.index("end-1c")
        self.log_text.insert(tk.END, line + "\n")
        self._colorize_log_line(line_start, line)
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        if self._console_log_path is not None:
            try:
                with self._console_log_path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass  # An unwritable log file must not crash the GUI

    def _colorize_log_line(self, line_start: str, line: str) -> None:
        """Highlights only the relevant part of a log line (the
        timestamp/log-level prefix stays unchanged) -- errors are
        checked first, then the tool-call result by duration, then
        section markers. A line gets at most one color; no match ->
        no change."""
        if "Error:" in line:
            start = line.index("Error:")
            self.log_text.tag_add("log_error", f"{line_start}+{start}c", f"{line_start} lineend")
            return

        match = re.search(r"-> (\d+) tool call\(s\), ([\d.]+)s", line)
        if match:
            call_count = int(match.group(1))
            duration = float(match.group(2))
            if call_count == 0:
                tag = "log_error"  # not an error, but no tool call -- not the expected outcome
            elif duration >= 30:
                tag = "log_slow"
            else:
                tag = "log_success"
            self.log_text.tag_add(tag, f"{line_start}+{match.start()}c", f"{line_start} lineend")
            return

        for marker in ("===", "---", ">>>"):
            idx = line.find(marker)
            if idx != -1:
                self.log_text.tag_add("log_section", f"{line_start}+{idx}c", f"{line_start} lineend")
                return

    # ── Start / Stop / Resume ────────────────────────────────────────

    def _selected_catalog_paths(self) -> list[Path]:
        return list(self._selected_catalogs)

    def _selected_models(self) -> list[str]:
        return list(self._selected_model_names)

    def _selected_system_prompts(self) -> list[tuple[str, str]]:
        by_name = {entry[0]: entry for entry in self._prompt_entries_all}
        return [by_name[n] for n in self._selected_prompt_names if n in by_name]

    def _on_start_new(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            messagebox.showwarning("Run active", "A test is already running. Stop it first.")
            return

        catalogs = self._selected_catalog_paths()
        models = self._selected_models()
        prompts = self._selected_system_prompts()
        if not catalogs:
            messagebox.showwarning("No selection", "Please select at least one question catalog.")
            return
        if not models:
            messagebox.showwarning("No selection", "Please select at least one model.")
            return
        if not prompts:
            messagebox.showwarning("No selection", "Please select at least one system prompt variant.")
            return

        ordner_name = build_lauf_ordner_name(self.nr_var.get(), self.datum_var.get(), self.freitext_var.get())
        if not ordner_name or ordner_name == "lauf":
            messagebox.showwarning("Folder name missing", "Please fill in the Nr./Date/Rest fields.")
            return

        output_dir = RESULTS_DIR / ordner_name
        self._start_run(catalogs, models, prompts, output_dir, resume=False)

    def _on_resume(self) -> None:
        if not self._resume_available or self._active_output_dir is None:
            return
        if self._worker_thread is not None and self._worker_thread.is_alive():
            messagebox.showwarning("Run active", "A test is already running.")
            return
        # Catalog/model/prompt selection is meant to stay the same as
        # for the original run (the runner skips already-completed
        # combinations via the progress file anyway) -- the current
        # GUI selection is passed through unchanged.
        catalogs = self._selected_catalog_paths()
        models = self._selected_models()
        prompts = self._selected_system_prompts()
        if not catalogs or not models or not prompts:
            messagebox.showwarning(
                "Selection missing",
                "For 'Resume run', catalogs/models/prompts must still be selected "
                "(same selection as the original start is recommended).")
            return
        self._start_run(catalogs, models, prompts, self._active_output_dir, resume=True)

    def _set_selection_locked(self, locked: bool) -> None:
        """Locks/unlocks all selection and run-folder widgets while a
        run is active -- the selection no longer affects the already-
        running worker thread anyway (it received catalogs/models/
        prompts as its own values already), but without a lock you
        could still accidentally change filter/selection/folder name
        during the run and confuse yourself (Timo's request,
        2026-09-22)."""
        state = "disabled" if locked else "normal"
        for widget in (
            self.catalog_listbox, self.catalog_filter_entry, self.catalog_reload_button,
            self.catalog_selected_listbox,
            self.model_listbox, self.model_filter_entry, self.model_reload_button,
            self.model_selected_listbox,
            self.prompt_listbox, self.prompt_filter_entry, self.prompt_reload_button,
            self.prompt_selected_listbox,
            self.nr_entry, self.datum_entry, self.freitext_entry,
        ):
            widget.config(state=state)

    def _start_run(self, catalogs: list[Path], models: list[str], prompts: list[tuple[str, str]],
                    output_dir: Path, resume: bool) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        # Remembers the selection made for this run in the run folder,
        # so _check_resumable_run() can restore it automatically after
        # a GUI restart -- see there.
        (output_dir / "gui_selection.json").write_text(
            json.dumps({
                "catalogs": [p.name for p in catalogs],
                "models": list(models),
                "prompts": [name for name, _text in prompts],
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._console_log_path = output_dir / "console.log"
        self._active_output_dir = output_dir
        self._stop_event = threading.Event()
        self._run_start_time = time.monotonic()
        self._resume_available = False

        self.start_button.config(state="disabled")
        self.resume_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self._set_selection_locked(True)
        self.progress_bar["value"] = 0
        self.status_label.config(text=f"Run started in {output_dir.name} ...")
        self._append_log(f"=== Run started: {output_dir.name} (resume={resume}) ===")

        stop_event = self._stop_event
        event_queue = self._event_queue

        def log_callback(line: str) -> None:
            event_queue.put({"type": "log", "line": line})

        def progress_callback(info: dict) -> None:
            event_queue.put({"type": "progress", **info})

        def worker() -> None:
            try:
                runner.run_test_session(
                    catalog_paths=catalogs,
                    model_list=models,
                    prompt_variants=prompts,
                    output_dir=output_dir,
                    log_callback=log_callback,
                    progress_callback=progress_callback,
                    stop_event=stop_event,
                    resume=resume,
                )
                event_queue.put({"type": "done"})
            except Exception as exc:  # noqa: BLE001 — error must surface in the GUI, not silently end the thread
                event_queue.put({"type": "error", "message": str(exc)})

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _on_stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
            self.stop_button.config(state="disabled")
            self._append_log("Stop requested -- current question is still being finished ...")

    # ── Queue-Polling (Mainloop-Thread) ───────────────────────────────

    def _poll_queue(self) -> None:
        try:
            while True:
                event = self._event_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass

        if self._run_start_time is not None and self._worker_thread is not None and self._worker_thread.is_alive():
            elapsed = time.monotonic() - self._run_start_time
            current = self.status_label.cget("text")
            # Elapsed time is tracked in the status line, see
            # _handle_event() for the rest of the line content -- here
            # only the time itself is updated, without losing the
            # other fields.
            if hasattr(self, "_last_status_prefix"):
                self.status_label.config(text=f"{self._last_status_prefix}  |  Verstrichene Zeit: {format_elapsed(elapsed)}")

        self.root.after(150, self._poll_queue)

    def _handle_event(self, event: dict) -> None:
        etype = event.get("type")
        if etype == "log":
            self._append_log(event["line"])
        elif etype == "progress":
            self._update_progress_display(event)
        elif etype == "done":
            self._on_run_finished()
            self._append_log("=== Run finished ===")
        elif etype == "error":
            self._on_run_finished()
            self._append_log(f"=== Run ended with error: {event['message']} ===")
            messagebox.showerror("Error in test run", event["message"])

    def _update_progress_display(self, info: dict) -> None:
        pct = (info["question_idx"] / info["question_total"]) * 100 if info["question_total"] else 0
        self.progress_bar["value"] = pct

        elapsed = time.monotonic() - self._run_start_time if self._run_start_time else 0
        self._last_status_prefix = (
            f"Current catalog: {info['catalog']} ({info['catalog_idx']}/{info['catalog_total']})   "
            f"Current model: {info['model']} ({info['model_idx']}/{info['model_total']})   "
            f"Prompt: {info['prompt']} ({info['prompt_idx']}/{info['prompt_total']})   "
            f"Question: {info['question_idx']}/{info['question_total']}"
        )
        self.status_label.config(text=f"{self._last_status_prefix}  |  Verstrichene Zeit: {format_elapsed(elapsed)}")

        # Stop was clicked while the worker was still running -- once
        # the worker has actually finished (see "done"/"error" events
        # above), the resume flag is set correctly. Here only the
        # live progress display, no state change.

    def _on_run_finished(self) -> None:
        """Called as soon as the worker thread returns -- whether it
        completed normally ('done'), was stopped via the Stop button
        (also returns 'done' from run_test_session(), since a stop is
        not an error case, see the return logic there), or ended with
        a real error ('error', e.g. MCP server unreachable). Resume
        only makes sense/is only offered if the run was actually
        stopped via the Stop button -- this is determined exclusively
        from the stop_event state, not the event type: a normally
        completed run has the same event type ('done') as a stopped
        one, and a genuine error BEFORE any Stop click should not
        offer resume (the folder may then contain no progress data at
        all, or only incomplete data up to an error point that has
        nothing to do with an intentional stop)."""
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled")
        self._set_selection_locked(False)
        self._resume_available = self._stop_event is not None and self._stop_event.is_set()
        self.resume_button.config(state="normal" if self._resume_available else "disabled")
        self._worker_thread = None


def main() -> None:
    root = tk.Tk()
    McpTestGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()

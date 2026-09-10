#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
mcp-llm-tester/mcp_test_gui.py
Tkinter GUI for mcp_llm_test_runner.py -- pick question catalogs and
Ollama models by clicking, start/stop/resume a test run, live log
display, progress display.

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
RESULTS_DIR = Path(__file__).parent / "results"


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
    mcp_llm_test_progress.jsonl but NO final mcp_llm_test_*.json next
    to it (see write_results() in mcp_llm_test_runner.py -- the final
    JSON is only written once the run either completed normally or
    was cleanly stopped; its absence alongside an existing progress
    file means the GUI was closed / the machine was restarted while
    the run was still active, without Stop having been pressed).

    Returns None if no lauf_*-folder exists, or if the last folder was
    either never started (no progress.jsonl) or already fully
    completed (final JSON present). Deliberately does NOT search
    across multiple older run folders -- only the most recent one
    counts."""
    found = _highest_lauf_dir(results_dir)
    if found is None:
        return None
    _, lauf_path = found

    progress_path = lauf_path / "mcp_llm_test_progress.jsonl"
    if not progress_path.exists():
        return None

    has_final_json = any(lauf_path.glob("mcp_llm_test_*.json"))
    if has_final_json:
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
        self._catalog_paths: list[Path] = []
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

        tk.Button(catalog_frame, text="Reload list", command=self._reload_catalogs).pack(
            anchor="e", padx=5, pady=(0, 5))

        # Models (right)
        model_frame = tk.LabelFrame(selection_frame, text="Ollama models (click to multi-select)")
        model_frame.pack(side="left", fill="both", expand=True, padx=(5, 0))

        self.model_listbox = tk.Listbox(model_frame, selectmode=tk.MULTIPLE, exportselection=False)
        self.model_listbox.pack(fill="both", expand=True, padx=5, pady=5)

        tk.Button(model_frame, text="Query Ollama again", command=self._reload_models).pack(
            anchor="e", padx=5, pady=(0, 5))

        # Run folder fields
        lauf_frame = tk.LabelFrame(self.root, text="Run folder")
        lauf_frame.pack(fill="x", padx=10, pady=5)

        tk.Label(lauf_frame, text="No.:").grid(row=0, column=0, sticky="e", padx=(5, 2), pady=5)
        self.nr_var = tk.StringVar()
        tk.Entry(lauf_frame, textvariable=self.nr_var, width=6).grid(row=0, column=1, sticky="w", pady=5)
        self.nr_var.trace_add("write", lambda *_: self._update_preview())

        tk.Label(lauf_frame, text="Date:").grid(row=0, column=2, sticky="e", padx=(10, 2), pady=5)
        self.datum_var = tk.StringVar()
        tk.Entry(lauf_frame, textvariable=self.datum_var, width=10).grid(row=0, column=3, sticky="w", pady=5)
        self.datum_var.trace_add("write", lambda *_: self._update_preview())

        tk.Label(lauf_frame, text="Rest (e.g. V1719_some_label):").grid(
            row=0, column=4, sticky="e", padx=(10, 2), pady=5)
        self.freitext_var = tk.StringVar()
        tk.Entry(lauf_frame, textvariable=self.freitext_var, width=30).grid(
            row=0, column=5, sticky="w", padx=(0, 5), pady=5)
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

    # ── Populate catalog/model lists ─────────────────────────────────

    def _reload_catalogs(self) -> None:
        self._catalog_paths = runner.discover_question_catalogs(CATALOG_DIR)
        self.catalog_listbox.delete(0, tk.END)
        for path in self._catalog_paths:
            self.catalog_listbox.insert(tk.END, path.name)
        if not self._catalog_paths:
            self._append_log(f"No question_catalog*.py files found in {CATALOG_DIR}.")

    def _reload_models(self) -> None:
        self.model_listbox.delete(0, tk.END)
        try:
            models = runner.fetch_ollama_models()
        except Exception as exc:
            self._append_log(f"Could not query Ollama models: {exc}")
            return
        for name in sorted(models):
            self.model_listbox.insert(tk.END, name)
        if not models:
            self._append_log("Ollama reports no installed models.")

    def _suggest_lauf_felder(self) -> None:
        self.nr_var.set(str(next_lauf_nr(RESULTS_DIR)))
        self.datum_var.set(datetime.now().strftime("%Y%m%d"))
        self._update_preview()

    def _check_resumable_run(self) -> None:
        """Checks at GUI startup whether the most recently created run
        folder is still open (progress.jsonl present but no final
        result JSON -- see find_resumable_run()). This covers the case
        where the GUI was closed, or the machine restarted, while a
        run was still active without Stop having been pressed (stop
        state should survive GUI restarts). If found, the Nr./Date/
        Rest fields are reset to the found folder (overwriting the
        NEXT free number just suggested by _suggest_lauf_felder() with
        the number of the open run) and the resume button is
        activated. If nothing is found, everything stays as suggested
        by _suggest_lauf_felder(), no further action."""
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
        self._append_log(
            f"Incomplete run found: {resumable_dir.name} -- "
            "'Resume run' is available."
        )

    def _update_preview(self) -> None:
        name = build_lauf_ordner_name(self.nr_var.get(), self.datum_var.get(), self.freitext_var.get())
        self.preview_label.config(text=f"Folder name: {name}")

    # ── Log-Ausgabe (nur aus dem Mainloop-Thread aufrufen) ───────────

    def _append_log(self, line: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        if self._console_log_path is not None:
            try:
                with self._console_log_path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass  # An unwritable log file must not crash the GUI

    # ── Start / Stop / Resume ────────────────────────────────────────

    def _selected_catalog_paths(self) -> list[Path]:
        return [self._catalog_paths[i] for i in self.catalog_listbox.curselection()]

    def _selected_models(self) -> list[str]:
        return [self.model_listbox.get(i) for i in self.model_listbox.curselection()]

    def _on_start_new(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            messagebox.showwarning("Run active", "A test is already running. Stop it first.")
            return

        catalogs = self._selected_catalog_paths()
        models = self._selected_models()
        if not catalogs:
            messagebox.showwarning("No selection", "Please select at least one question catalog.")
            return
        if not models:
            messagebox.showwarning("No selection", "Please select at least one model.")
            return

        ordner_name = build_lauf_ordner_name(self.nr_var.get(), self.datum_var.get(), self.freitext_var.get())
        if not ordner_name or ordner_name == "lauf":
            messagebox.showwarning("Folder name missing", "Please fill in the Nr./Date/Rest fields.")
            return

        output_dir = RESULTS_DIR / ordner_name
        self._start_run(catalogs, models, output_dir, resume=False)

    def _on_resume(self) -> None:
        if not self._resume_available or self._active_output_dir is None:
            return
        if self._worker_thread is not None and self._worker_thread.is_alive():
            messagebox.showwarning("Run active", "A test is already running.")
            return
        # Catalog/model selection is meant to stay the same as for the
        # original run (the runner skips already-completed combinations
        # via the progress file anyway) -- the current GUI selection is
        # passed through unchanged.
        catalogs = self._selected_catalog_paths()
        models = self._selected_models()
        if not catalogs or not models:
            messagebox.showwarning(
                "Auswahl fehlt",
                "For 'Resume run', catalogs/models must still be selected "
                "(same selection as the original start is recommended).")
            return
        self._start_run(catalogs, models, self._active_output_dir, resume=True)

    def _start_run(self, catalogs: list[Path], models: list[str], output_dir: Path, resume: bool) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._console_log_path = output_dir / "console.log"
        self._active_output_dir = output_dir
        self._stop_event = threading.Event()
        self._run_start_time = time.monotonic()
        self._resume_available = False

        self.start_button.config(state="disabled")
        self.resume_button.config(state="disabled")
        self.stop_button.config(state="normal")
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
        self._resume_available = self._stop_event is not None and self._stop_event.is_set()
        self.resume_button.config(state="normal" if self._resume_available else "disabled")
        self._worker_thread = None


def main() -> None:
    root = tk.Tk()
    McpTestGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()

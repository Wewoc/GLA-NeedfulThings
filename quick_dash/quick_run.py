#!/usr/bin/env python3
"""
quick_run.py -- GLA-Tools / Quick Dashboard Runner

Loads the most recently generated quick_*_dash.py specialist,
calls build() with the timeframe from quick_config.json,
and renders the output via GLA's plotters.

No GLA GUI required. Runs standalone from the quick_dash/ directory.
"""

import sys
import os
import json
import importlib.util
from pathlib import Path
from datetime import date, timedelta

CONFIG_FILE = Path(__file__).parent / "quick_config.json"


# ==============================================================================
#  Config
# ==============================================================================

def _load_config():
    if not CONFIG_FILE.exists():
        print("[Error] quick_config.json not found. Run config.py first.")
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


# ==============================================================================
#  Plotter loader
# ==============================================================================

_FORMAT_EXT = {
    "html":         ".html",
    "html_complex": ".html",
    "html_mobile":  ".html",
    "excel":        ".xlsx",
    "json":         ".json",
    "pdf":          ".pdf",
    "word":         ".docx",
}

_PLOTTER_MAP = {
    "html":         "dash_plotter_html_mobile",
    "html_complex": "dash_plotter_html_complex",
    "html_mobile":  "dash_plotter_html_mobile",
    "excel":        "dash_plotter_excel",
    "json":         "dash_plotter_json",
    "pdf":          "dash_plotter_pdf",
    "word":         "dash_plotter_word",
}

def _load_plotter(gla_path, fmt, mode="overview"):
    if fmt == "html" and mode == "intraday":
        module_name = "dash_plotter_html"
    else:
        module_name = _PLOTTER_MAP.get(fmt)
    if not module_name:
        print(f"[Error] Unknown format: {fmt}")
        sys.exit(1)
    mod_path = Path(gla_path) / "layouts" / f"{module_name}.py"
    if not mod_path.exists():
        print(f"[Error] Plotter not found: {mod_path}")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location(module_name, mod_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ==============================================================================
#  Specialist loader -- pick most recent quick_*_dash.py
# ==============================================================================

def _load_specialist(gla_path):
    dashboards_dir = Path(__file__).parent / "scripts"
    candidates = sorted(dashboards_dir.glob("quick_*_dash.py"), reverse=True)
    if not candidates:
        print("[Error] No quick_*_dash.py found in dashboards/.")
        print("        Run config.py first to generate a specialist.")
        sys.exit(1)
    path = candidates[0]
    print(f"  Specialist : {path.name}")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ==============================================================================
#  Run
# ==============================================================================

def run():
    cfg = _load_config()

    gla_path  = cfg.get("gla_path",  "")
    data_path = cfg.get("data_path", "")
    date_from = cfg.get("date_from", "")
    date_to   = cfg.get("date_to",   "")
    formats   = cfg.get("formats",   ["html"])
    name      = cfg.get("name",      "Quick Dashboard")

    # Resolve dates if missing
    if not date_to:
        date_to = date.today().isoformat()
    if not date_from:
        date_from = (date.today() - timedelta(days=30)).isoformat()

    # Set GARMIN_OUTPUT_DIR so garmin_config.py resolves data paths correctly
    os.environ["GARMIN_OUTPUT_DIR"] = data_path

    # Add GLA to sys.path
    if str(gla_path) not in sys.path:
        sys.path.insert(0, str(gla_path))

    # Output goes to quick_dash/dashboards/
    output_dir = Path(__file__).parent / "dashboards"
    output_dir.mkdir(parents=True, exist_ok=True)

    print()
    print(f"  Name       : {name}")
    print(f"  Timeframe  : {date_from} -> {date_to}")
    print(f"  Formats    : {', '.join(formats)}")
    print(f"  Output     : {output_dir}")
    print()

    specialist = _load_specialist(gla_path)
    settings   = {"base_dir": data_path}

    # Build once
    try:
        data = specialist.build(date_from, date_to, settings)
    except Exception as exc:
        print(f"[Error] build() failed: {exc}")
        sys.exit(1)

    # Render each format
    for fmt in formats:
        try:
            plotter = _load_plotter(gla_path, fmt, mode=cfg.get("mode", "overview"))
            ext      = _FORMAT_EXT.get(fmt, ".html")
            filename = specialist.META.get("formats", {}).get(fmt, f"quick_{fmt}{ext}")
            out_path = output_dir / filename
            plotter.render(data, out_path, settings)
            print(f"  [OK] {fmt.upper()} -> {out_path}")
        except Exception as exc:
            print(f"  [Error] {fmt.upper()} failed: {exc}")

    print()
    print("Done.")


if __name__ == "__main__":
    run()

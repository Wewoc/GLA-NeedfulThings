#!/usr/bin/env python3
"""
config.py -- GLA-Tools / Quick Dashboard Configurator
"""

import sys
import json
import subprocess
from pathlib import Path
from datetime import date, timedelta

CONFIG_FILE    = Path(__file__).parent / "quick_config.json"
BUILDER_SCRIPT = Path(__file__).parent / "quick_dash.py"


def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"{prompt}{suffix}: ").strip()
        if val:
            return val
        if default:
            return default


def ask_choice(prompt, options, default=None):
    joined = " / ".join(options)
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"{prompt} ({joined}){suffix}: ").strip().lower()
        if not val and default:
            return default
        if val in options:
            return val


def ask_numbers(prompt, max_n):
    while True:
        raw = input(f"{prompt}: ").strip()
        if raw == "":
            return []
        parts = raw.split()
        indices = []
        valid = True
        for p in parts:
            try:
                n = int(p)
                if 1 <= n <= max_n:
                    indices.append(n - 1)
                else:
                    print(f"  [!] {n} is out of range (1-{max_n})")
                    valid = False
                    break
            except ValueError:
                print(f"  [!] '{p}' is not a number")
                valid = False
                break
        if valid:
            return indices


def sep():
    print()


def get_gla_paths(existing):
    saved_gla  = existing.get("gla_path",  "")
    saved_data = existing.get("data_path", "")

    if (saved_gla and Path(saved_gla).exists()
            and saved_data and Path(saved_data).exists()):
        sep()
        print(f"GLA path  : {saved_gla}")
        print(f"Data path : {saved_data}")
        keep = ask_choice("Use these paths?", ["y", "n"], default="y")
        if keep == "y":
            return saved_gla, saved_data

    while True:
        sep()
        gla_path = input("GLA installation path (e.g. D:\\Garmin\\Garmin_Local_Archive): ").strip()
        if Path(gla_path).exists():
            break
        print(f"  [!] Path not found: {gla_path}")

    while True:
        sep()
        data_path = input("GLA data path -- folder containing garmin_data/ (e.g. D:\\Garmin\\Daten): ").strip()
        if Path(data_path).exists():
            break
        print(f"  [!] Path not found: {data_path}")

    return gla_path, data_path


def fetch_fields(gla_path, data_path, mode):
    tmp = {"gla_path": gla_path, "data_path": data_path, "mode": mode}
    CONFIG_FILE.write_text(json.dumps(tmp), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(BUILDER_SCRIPT), "--fields"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("[Error] Could not fetch fields:")
        print(result.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def main():
    print("=" * 54)
    print("  GLA-Tools -- Quick Dashboard Configurator")
    print("=" * 54)

    existing = {}
    if CONFIG_FILE.exists():
        try:
            existing = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    gla_path, data_path = get_gla_paths(existing)

    sep()
    print("Mode:")
    print("  overview  -- daily summary values (HRV, stress, sleep, ...)")
    print("  intraday  -- minute-by-minute series (heart rate, SpO2, ...)")
    mode = ask_choice("Select mode", ["overview", "intraday"], default="overview")

    sep()
    print("Fetching available fields ...")
    fields = fetch_fields(gla_path, data_path, mode)
    garmin_list  = fields.get("garmin", [])
    context_list = fields.get("context", [])

    sep()
    garmin_selected = []
    if not garmin_list:
        print(f"No Garmin fields available for mode '{mode}'.")
    else:
        print(f"Garmin fields ({mode}):")
        for i, f in enumerate(garmin_list):
            print(f"  {i+1:2}  {f}")
        indices = ask_numbers(
            "Select Garmin fields (e.g. 1 3 5 -- leave empty to skip)",
            len(garmin_list)
        )
        garmin_selected = [garmin_list[i] for i in indices]

    sep()
    context_selected = []
    context_meta     = []
    if mode == "intraday":
        print("Context fields are daily-only -- not available in intraday mode.")
    elif not context_list:
        print("No context fields available.")
    else:
        print("Context fields:")
        for i, f in enumerate(context_list):
            print(f"  {i+1:2}  {f['field']:<30}  [{f['source']}]")
        indices = ask_numbers(
            "Select context fields (e.g. 2 4 -- leave empty to skip)",
            len(context_list)
        )
        context_selected = [context_list[i]["field"] for i in indices]
        context_meta     = [context_list[i] for i in indices]

    if not garmin_selected and not context_selected:
        print("\n[Error] No fields selected. Aborting.")
        sys.exit(1)

    sep()
    print("Output format:")
    print("  html   -- HTML")
    print("  excel  -- Excel workbook")
    print("  json   -- raw JSON")
    fmt_raw = ask("Formats (e.g. html  or  html excel)", default="html")
    formats = [f.strip() for f in fmt_raw.split() if f.strip()]

    sep()
    print("Timeframe:")
    print("  Number of days back  (e.g. 30)")
    print("  Or date range        (e.g. 2026-01-01 2026-04-30)")
    time_raw = ask("Timeframe", default="30")
    parts = time_raw.strip().split()
    if len(parts) >= 2:
        date_from = parts[0]
        date_to   = parts[1]
    else:
        try:
            days = int(parts[0])
        except ValueError:
            days = 30
        date_to   = date.today().isoformat()
        date_from = (date.today() - timedelta(days=days)).isoformat()

    sep()
    name        = ask("Dashboard name", default="Quick Dashboard")
    description = input("Description (optional): ").strip()

    config = {
        "gla_path":       gla_path,
        "data_path":      data_path,
        "mode":           mode,
        "name":           name,
        "description":    description,
        "formats":        formats,
        "garmin_fields":  garmin_selected,
        "context_fields": context_selected,
        "_context_meta":  context_meta,
        "date_from":      date_from,
        "date_to":        date_to,
    }
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")

    sep()
    print("Config saved.")
    sep()
    subprocess.run([sys.executable, str(BUILDER_SCRIPT)])


if __name__ == "__main__":
    main()

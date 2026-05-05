# quick_dash — Quick Dashboard Generator

Generates throw-away GLA dashboards from an interactive config.
No Python knowledge required. No Ollama. No changes to GLA itself.

---

## What it does

Asks a few questions, builds a specialist from fixed code blocks,
renders the output directly — HTML, Excel, or JSON.
Everything stays in the `quick_dash/` folder, nothing touches GLA's code.

---

## Requirements

- GLA v1.4+ installed locally
- Python 3.10+

---

## Usage

Double-click `start.bat` — that's it.

```bash
# Or from the terminal:
python config.py
```

---

## Workflow

1. `start.bat` opens the configurator
2. Answer the questions:
   - GLA path + data path (saved after first run)
   - Mode: overview (daily) or intraday (hourly)
   - Fields: numbered list, pick by number
   - Format: html / excel / json
   - Timeframe: days back or date range
   - Name + description
3. Specialist is generated in `scripts/`
4. Output is rendered to `dashboards/`
5. Done — open the file directly, no GLA needed

---

## Modes

| Mode | Data | Plotter |
|---|---|---|
| overview | daily summary values | mobile HTML, Excel, JSON |
| intraday | hourly aggregated series | HTML with tab navigation |

Context fields (weather, pollen, air quality) are available in overview mode only.

---

## Files

| File | Purpose |
|---|---|
| `start.bat` | Entry point — double-click to run |
| `config.py` | Interactive configurator |
| `quick_dash.py` | Specialist builder |
| `quick_run.py` | Renderer — calls GLA plotters directly |
| `quick_config.json` | Saved config — reused on next run |
| `scripts/` | Generated specialists |
| `dashboards/` | Generated output files |

---

## Notes

- Generated specialists are not production-ready — no tests, no docs
- `quick_config.json` is not meant to be edited manually
- GLA path and data path are saved after the first run
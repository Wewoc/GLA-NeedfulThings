"""
netz2_diagnostics/netz2_config.example.py

Local configuration template for the run_netz2*.py scripts.

Copy this file to `netz2_config.py` (same folder) and fill in your own
paths. `netz2_config.py` is listed in .gitignore and never committed —
this keeps the diagnostic scripts themselves generic and portable, while
your personal archive path stays local.

Report numbering (REPORT_ID) does NOT live here — it is assigned at
runtime by run_netz2_all.bat (environment variable NETZ2_REPORT_ID),
derived from the existing output/ folders.
"""

from pathlib import Path

# Path to the main repo (Garmin Local Archive), relative to this folder.
PROJECT_ROOT_REL = "../Garmin_Local_Archive"

# Path to your REAL archive (the parent folder of garmin_data/), used
# READ-ONLY — source for a real raw/ file used as a fixture template.
# ❗ Set this to your actual GARMIN_OUTPUT_DIR path.
REAL_ARCHIVE_BASE_DIR = Path(r"C:\path\to\your\garmin_data_parent")

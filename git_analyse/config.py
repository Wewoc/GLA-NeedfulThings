#!/usr/bin/env python3
"""
config.py — git_analyse
Central configuration for github_insights.py and repo_diff.py.

Edit this file to configure both tools — no other files need to be changed.
Requires a .env file with GITHUB_TOKEN (see .env.example).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── GitHub ─────────────────────────────────────────────────────────────────────

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")   # loaded from .env
REPO_OWNER   = "your-name"                 # your github name
REPO_NAME    = "your-project"              # your github project
BRANCH       = "main"

# ── repo_diff ──────────────────────────────────────────────────────────────────

LOCAL_DIR      = Path(r".")          # local folder to compare against GitHub
SHOW_IDENTICAL = False               # True = also show unchanged files

# Files / folders to ignore in local comparison
IGNORE = {
    ".git",
    ".bat",
    "screenshots",
    "__pycache__",
    ".env",
    "*.pyc",
    "*.log",
    "garmin_data",
    "local_config.csv",
}

# ── github_insights ────────────────────────────────────────────────────────────

ROOT_DIR          = Path(".")
SOURCE_DIR        = ROOT_DIR / "source"
MASTER_CSV        = "master_insights_combined.csv"
DASHBOARD_SINGLE  = "index_combined.html"
DASHBOARD_STACKED = "index_stacked.html"
CLEANUP_INTERVAL  = 13               # Days between kept snapshot folders

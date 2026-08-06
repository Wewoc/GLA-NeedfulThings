# git_analyse

Two tools for analyzing a GitHub repository — traffic insights and local diff.

---

## Tools

### github_insights.py
Fetches traffic data (views, clones, commits, releases) from the GitHub API,
builds a cumulative CSV, and generates two Plotly HTML dashboards.
Snapshots are stored in `source/YYYY-MM-DD/` and accumulated over time.
Old intermediate snapshots are cleaned up automatically.

**Output:**
- `source/` — daily snapshots
- `master_insights_combined.csv` — accumulated data
- `index_combined.html` — all metrics in one chart
- `index_stacked.html` — one chart per metric
- `DOWNLOADS.md` — release download stats

### repo_diff.py
Compares a local folder against the current GitHub repo state (HEAD).
Uses Git blob SHA1 for comparison — detects every content difference.

**Output:**
- Console: categorized list (MODIFIED / NEW / DELETED / IDENTICAL)
- `diff.md` — same output written to file

---

## Requirements

```
pip install pandas plotly python-dotenv
```

---

## Setup

1. Create a GitHub Personal Access Token:
   GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
   Required scope: `repo` (for traffic data on private repos) or just `public_repo`

2. Copy `.env.example` to `.env` and add your token:
   ```
   GITHUB_TOKEN=your_token_here
   ```

3. Edit `config.py` — set `REPO_OWNER`, `REPO_NAME`, and `LOCAL_DIR`

4. Run:
   ```
   run_insights.bat
   run_repo_diff.bat
   ```
   Or directly: `python github_insights.py` / `python repo_diff.py`

---

## Configuration

All parameters in `config.py`:

| Parameter | Default | Description |
|---|---|---|
| `REPO_OWNER` | `"Wewoc"` | GitHub username or organization |
| `REPO_NAME` | `"Garmin_Local_Archive"` | Repository name |
| `BRANCH` | `"main"` | Branch to compare against |
| `LOCAL_DIR` | `.` | Local folder for repo_diff comparison |
| `SHOW_IDENTICAL` | `False` | Also show unchanged files in diff |
| `IGNORE` | see config.py | Files/folders excluded from diff |
| `CLEANUP_INTERVAL` | `13` | Days between kept snapshot folders |

---

## Notes

- Traffic data is only available for repositories where you have push access
- GitHub retains traffic data for 14 days — run insights regularly to build history
- `.env` is listed in `.gitignore` by default — never commit your token

#!/usr/bin/env python3
"""
github_insights.py
Fetches GitHub traffic data (views, clones, commits, releases) for a repository,
builds a cumulative CSV, and generates two Plotly HTML dashboards.

Snapshots are stored in source/YYYY-MM-DD/ and accumulated over time.
Old intermediate snapshots are cleaned up automatically (see CLEANUP_INTERVAL in config.py).

Usage:
  python github_insights.py

Requirements:
  pip install pandas plotly python-dotenv
"""

import os
import urllib.request
import json
import datetime
import shutil

import pandas as pd
import plotly.express as px

from config import (
    GITHUB_TOKEN, REPO_OWNER, REPO_NAME,
    ROOT_DIR, SOURCE_DIR, MASTER_CSV,
    DASHBOARD_SINGLE, DASHBOARD_STACKED, CLEANUP_INTERVAL,
)

# ── GitHub API ─────────────────────────────────────────────────────────────────

def github_request(url: str):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "git-analyse")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

# ── Traffic snapshot ───────────────────────────────────────────────────────────

def fetch_traffic():
    print(f"-> Fetching traffic data for {REPO_OWNER}/{REPO_NAME} ...")
    SOURCE_DIR.mkdir(exist_ok=True)
    today_str  = datetime.datetime.now().strftime("%Y-%m-%d")
    target_dir = SOURCE_DIR / today_str
    target_dir.mkdir(exist_ok=True)

    base_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/traffic"
    try:
        views_data  = github_request(f"{base_url}/views")["views"]
        clones_data = github_request(f"{base_url}/clones")["clones"]
        files = [
            ("Total views in last 14 days.csv",      views_data,  "Total"),
            ("Unique visitors in last 14 days.csv",  views_data,  "Unique"),
            ("Clones in last 14 days.csv",           clones_data, "Total"),
            ("Unique cloners in last 14 days.csv",   clones_data, "Unique"),
        ]
        for filename, data, col_type in files:
            with open(target_dir / filename, "w", encoding="utf-8") as f:
                f.write(f'"Category";"{col_type}"\n')
                for entry in data:
                    dt  = datetime.datetime.strptime(entry["timestamp"][:10], "%Y-%m-%d")
                    val = entry["count"] if col_type == "Total" else entry["uniques"]
                    f.write(f'"{dt.strftime("%m/%d")}";{val}\n')
        print(f"   Saved to /{today_str}")
    except Exception as e:
        print(f"   ERROR fetching traffic: {e}")


def get_commits() -> pd.DataFrame:
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits?per_page=100"
    try:
        data         = github_request(url)
        commit_dates = [c["commit"]["author"]["date"][:10] for c in data]
        df           = pd.DataFrame(commit_dates, columns=["Date"])
        df["Date"]   = pd.to_datetime(df["Date"])
        return df.groupby("Date").size().reset_index(name="Commits").set_index("Date")
    except:
        return pd.DataFrame(columns=["Date", "Commits"]).set_index("Date")


def generate_release_stats():
    print("-> Generating release download stats ...")
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases"
    try:
        releases    = github_request(url)
        md          = f"# Release Download Stats\n\n*Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
        md         += "| Version | File | Downloads | Size | Date |\n| :--- | :--- | :--- | :--- | :--- |\n"
        total       = 0
        for release in releases:
            tag  = release.get("tag_name", "N/A")
            date = release.get("published_at", "").split("T")[0]
            for asset in release.get("assets", []):
                count  = asset.get("download_count", 0)
                size   = round(asset.get("size", 0) / (1024 * 1024), 2)
                total += count
                md    += f"| {tag} | `{asset.get('name')}` | **{count}** | {size} MB | {date} |\n"
        md += f"\n\n**Total downloads: {total}**\n"
        (ROOT_DIR / "DOWNLOADS.md").write_text(md, encoding="utf-8")
        print("   DOWNLOADS.md updated.")
    except Exception as e:
        print(f"   ERROR generating release stats: {e}")


def cleanup_snapshots():
    print(f"-> Cleaning up snapshot folders (interval: {CLEANUP_INTERVAL} days) ...")
    folders = sorted([f for f in SOURCE_DIR.glob("202*") if f.is_dir()])
    if len(folders) <= 2:
        print("   Nothing to clean up.")
        return

    def force_delete(func, path, exc_info):
        os.chmod(path, 0o777)
        func(path)

    anchor        = folders[0]
    deleted_count = 0
    print(f"   [ANCHOR] Keeping oldest: {anchor.name}")

    for folder in folders[1:-1]:
        try:
            diff = (datetime.datetime.strptime(folder.name, "%Y-%m-%d") -
                    datetime.datetime.strptime(anchor.name, "%Y-%m-%d")).days
            if diff < CLEANUP_INTERVAL:
                print(f"   [DELETE] {folder.name} (gap: {diff}d) ...", end="")
                try:
                    shutil.rmtree(folder, onerror=force_delete)
                    print(" OK")
                    deleted_count += 1
                except Exception as e:
                    print(f" FAILED ({e})")
            else:
                anchor = folder
                print(f"   [ANCHOR] New anchor: {folder.name}")
        except ValueError:
            continue

    print(f"   [KEEP] Latest: {folders[-1].name}")
    print(f"   Cleanup done: {deleted_count} folders removed.")


def add_weekly_shading(fig, df):
    if df.empty:
        return fig
    start = df["Date"].min()
    end   = df["Date"].max()
    curr  = (start - datetime.timedelta(days=start.weekday())).replace(hour=0, minute=0, second=0)
    while curr <= end:
        nxt = curr + datetime.timedelta(days=7)
        if curr.isocalendar()[1] % 2 == 0:
            fig.add_vrect(x0=curr, x1=nxt, fillcolor="gray", opacity=0.1, layer="below", line_width=0)
        curr = nxt
    return fig

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if not GITHUB_TOKEN:
        print("ERROR: GITHUB_TOKEN not set — create a .env file (see .env.example)")
        return

    fetch_traffic()

    mapping = {
        "Clones in last 14 days.csv":          "Clones",
        "Total views in last 14 days.csv":     "Views",
        "Unique cloners in last 14 days.csv":  "Unique_Cloners",
        "Unique visitors in last 14 days.csv": "Unique_Visitors",
    }
    collected = {}
    for fname, col in mapping.items():
        snaps = []
        for folder in sorted(SOURCE_DIR.glob("202*")):
            p = folder / fname
            if p.exists():
                df         = pd.read_csv(p, sep=";", quotechar='"', engine="python")
                df["Date"] = pd.to_datetime(folder.name[:4] + "-" + df.iloc[:, 0].str.replace("/", "-"), errors="coerce")
                snaps.append(df.dropna(subset=["Date"])[["Date", df.columns[1]]].rename(columns={df.columns[1]: col}))
        if snaps:
            collected[col] = pd.concat(snaps).drop_duplicates(subset=["Date"], keep="last").set_index("Date")

    if not collected:
        print("No data collected.")
        return

    master_df = pd.concat(collected.values(), axis=1, join="outer").sort_index()
    master_df = master_df.join(get_commits(), how="outer").fillna(0)
    master_df = master_df.infer_objects(copy=False).astype(int)
    master_df.to_csv(MASTER_CSV, sep=";", index=True)

    pdf = master_df.reset_index()
    px.line(pdf, x="Date", y=[c for c in master_df.columns if c != "Date"], title="Combined").write_html(DASHBOARD_SINGLE)

    order = [
        ("Commits",         "Commits"),
        ("Clones",          "Clones"),
        ("Unique Cloners",  "Unique_Cloners"),
        ("Views",           "Views"),
        ("Unique Visitors", "Unique_Visitors"),
    ]
    html = ["<html><body style='background:#f4f4f9; padding:20px;'><h1 style='text-align:center;'>Stacked Insights</h1>"]
    for title, col in order:
        if col in pdf.columns:
            fig = add_weekly_shading(px.line(pdf, x="Date", y=col, title=title, markers=True, template="plotly_white"), pdf)
            fig.update_layout(height=350, margin=dict(l=20, r=20, t=50, b=20), hovermode="x unified")
            html.append(
                f"<div style='margin-bottom:20px; border:1px solid #ddd; background:#fff;'>"
                f"{fig.to_html(full_html=False, include_plotlyjs='cdn' if title == order[0][0] else False)}"
                f"</div>"
            )
    with open(DASHBOARD_STACKED, "w", encoding="utf-8") as f:
        f.write("\n".join(html) + "</body></html>")

    print("-> Done. CSV and dashboards updated.")
    generate_release_stats()
    cleanup_snapshots()
    print("\n=== All done. ===")


if __name__ == "__main__":
    main()

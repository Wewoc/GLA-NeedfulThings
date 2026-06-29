"""
gemini_exporter_gla.py
======================
Based on Liyue2341/gemini-exporter.
Adapted for selective export: only GLA-relevant chats.

Changes from original:
  - Keyword filter: only chats with GLA-relevant titles are exported
  - Title is read from the page (document.title)
  - Filename: sanitized title + timestamp instead of conv_id.json
  - Output: .md (amazingpaddy extension remains unchanged)

Requirements:
  1. Chrome started with --remote-debugging-port=9222
  2. amazingpaddy/ai-chat-exporter extension installed (unpacked)
  3. Logged in at https://gemini.google.com/app, sidebar expanded

Usage:
  python gemini_exporter_gla.py
  python gemini_exporter_gla.py --output-dir ./my_export
  python gemini_exporter_gla.py --no-filter   (export all chats)
"""

import argparse
import asyncio
import os
import random
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

# ============== Configuration ==============
GEMINI_APP_URL = "https://gemini.google.com/app"

SCROLL_STABLE_THRESHOLD = 12
SCROLL_WAIT = 1.5

PLUGIN_SELECT_WAIT_MIN = 3.0
PLUGIN_SELECT_WAIT_MAX = 4.5
PLUGIN_SELECT_MAX_ROUNDS = 40
PLUGIN_SCROLL_STABLE_ROUNDS = 4
PLUGIN_EXPORT_WAIT_AFTER_CLICK = 1.5
PLUGIN_POPUP_DISMISS_WAIT = 0.8
PLUGIN_DOWNLOAD_POLL_SEC = 25

SLEEP_MIN, SLEEP_MAX = 3, 6

# ============== GLA Keyword Filter ==============
# A chat is exported if its title contains at least one of these keywords.
# Case-insensitive matching.

GLA_KEYWORDS = [
    # Directly GLA
    "garmin",
    "GLA",
    "garmin local archive",
    "refactoring plan",
    "gui/controller",
    "fit-pipeline",
    "pyqt6 migration",
    "readme-analyse",
    "code-analyse",
    "architektur-analyse",
    "technisches review",
    "selfhosted garmin",
    "code review für garmin",
    "branding analyse",
    "substack episode",
    "kritisches testprotokoll",
    "chat-analyser",
    "gemini export analyse",
    "gemini chat-verläufe",
    "schema versioning",
    "token-persistenz",
    "projekt gla-tools",
    "garminconnect",
    # Context / Story
    "softwarearchitektur als ingenieur",
    "ki-gestützte archivierung",
    "ai-assisted coding",
    "kehrseite des vibecodings",
    "vibe coding",
    "ki-nutzung in softwareentwicklung",
    "digitalen souveränität",
    "ki-zusammenarbeit",
    "refactoring.md",
    "libhunt",
    "github stars",
    "github pull shark",
    "pipeline-umbau",
    "llm-identifikation",
    "small language models",
    "claude code lokal",
    "open webui",
    "sichere lokale ki",
    "terminologie-engine",
    "llms für python",
    "deerflow",
    "lokales repo mit github",
    "bild im gla-stil",
    # Category C — semantically relevant
    "dsgvo-datenportabilität",
    "datenportabilität",
    "fitness-tracker",
    "ollama",
    "proton drive",
    "proton mail",
    "proton:",
    "cloud vs. lokal",
    "cloud vs lokal",
    "nutzungs-limit",
    "browser-vergleich",
    "datenschutz",
    "whisper",
    "spracherkennung lokal",
    "manus ai",
    "gemma",
    "maschinelle übersetzung",
    "markdown-dateien zusammen",
    "enigma verschlüsselung",
    "git pull",
    "git clone",
    "powershell python",
    "ordnernamen",
    "markdown als pdf",
    "needful things",
    "repository-wachstum",
    "github insights",
    "open webu",
]
# ================================================


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export GLA-relevant Gemini chats as Markdown files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--cdp-port", type=int, default=9222)
    parser.add_argument("--output-dir", type=str, default="gemini_gla_export")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--no-confirm", action="store_true")
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Export all chats (disable keyword filter)",
    )
    parser.add_argument("--no-skip", action="store_true")
    return parser.parse_args()


def _url_to_id(url: str) -> str:
    m = re.search(r"/app/([a-f0-9]+)", (url or "").rstrip("/"))
    return m.group(1) if m else "unknown"


def _sanitize_filename(title: str) -> str:
    """Convert a chat title into a safe filename."""
    title = title.strip()
    # Remove common Gemini title prefixes
    for prefix in ["Unterhaltung mit Gemini", "Chat with Gemini", "Gemini"]:
        if title.startswith(prefix):
            title = title[len(prefix):].strip(" -–—")
    # Replace invalid characters
    title = re.sub(r'[\\/:*?"<>|]', "_", title)
    title = re.sub(r"\s+", "_", title)
    title = title.strip("._")
    return title[:80] if title else "unknown"


def _is_gla_relevant(title: str) -> bool:
    """Check whether a chat title matches the GLA keyword filter."""
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in GLA_KEYWORDS)


async def _get_page_title(page) -> str:
    """Read the chat title from the page."""
    try:
        title = await page.evaluate("() => document.title")
        return title or ""
    except Exception:
        return ""


async def _scroll_sidebar_by_js(page, delta: int = 400):
    return await page.evaluate(
        """(delta) => {
        const links = document.querySelectorAll('a[href^="/app/"]');
        if (!links.length) return false;
        let el = links[0];
        while (el && el !== document.body) {
            const style = window.getComputedStyle(el);
            const overflow = style.overflowY || style.overflow;
            const scrollable = overflow === 'auto' || overflow === 'scroll' || overflow === 'overlay';
            if (scrollable && el.scrollHeight > el.clientHeight) {
                el.scrollTop += delta;
                return true;
            }
            el = el.parentElement;
        }
        const main = document.querySelector('nav') || document.querySelector('[role="navigation"]') || document.documentElement;
        if (main && main.scrollHeight > main.clientHeight) {
            main.scrollTop += delta;
            return true;
        }
        window.scrollBy(0, delta);
        return true;
    }""",
        delta,
    )


async def discover_conversation_urls(page) -> list:
    """Phase 1: Collect all /app/ URLs from the sidebar."""
    seen_count = 0
    stable_rounds = 0
    all_urls = []

    while stable_rounds < SCROLL_STABLE_THRESHOLD:
        count = await page.evaluate(
            """() => {
            const links = document.querySelectorAll('a[href^="/app/"]');
            const urls = new Set();
            links.forEach(a => { if (a.href) urls.add(a.href); });
            return urls.size;
        }"""
        )
        all_urls = await page.evaluate(
            """() => {
            const links = document.querySelectorAll('a[href^="/app/"]');
            const urls = [];
            links.forEach(a => { if (a.href && !urls.includes(a.href)) urls.push(a.href); });
            return urls;
        }"""
        )
        if count > seen_count:
            seen_count = count
            stable_rounds = 0
            print(f"   Links found: {count}")
        else:
            stable_rounds += 1
            print(f"   No new links ({count}), stable {stable_rounds}/{SCROLL_STABLE_THRESHOLD}")

        try:
            scrolled = await _scroll_sidebar_by_js(page, 400)
            if not scrolled:
                box = await page.locator("a[href^='/app/']").first.bounding_box()
                if box:
                    await page.mouse.move(
                        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    )
                await page.mouse.wheel(0, 400)
        except Exception:
            await page.mouse.wheel(0, 400)
        await asyncio.sleep(SCROLL_WAIT)

    return list(dict.fromkeys(all_urls))


async def _wait_for_plugin_buttons(page, timeout_sec: float = 20):
    """Wait for the amazingpaddy 4.x 'Export Chat' button."""
    step = 1.0
    elapsed = 0
    while elapsed < timeout_sec:
        found = await page.evaluate(
            """() => {
            const text = document.body ? document.body.innerText || '' : '';
            return text.includes('Export Chat');
        }"""
        )
        if found:
            return True, True
        await asyncio.sleep(step)
        elapsed += step
    return False, False


LOCATOR_SELECT_OR_CANCEL = (
    ".MuiButtonGroup-groupedOutlinedSecondary.MuiButtonGroup-lastButton, "
    ".MuiButtonGroup-groupedOutlinedError.MuiButtonGroup-lastButton"
)


async def _open_select_dropdown_and_choose_all(page):
    try:
        await page.locator(LOCATOR_SELECT_OR_CANCEL).first.click(timeout=8000)
    except Exception:
        return False
    await asyncio.sleep(0.7)
    try:
        await page.get_by_role("button", name="All (default)").click(timeout=5000)
    except Exception:
        return False
    return True


async def _get_scroll_state(page):
    return await page.evaluate(
        """() => {
        const main = document.querySelector('main') || document.querySelector('[role="main"]');
        const el = main || document.documentElement;
        return { scrollTop: el.scrollTop || 0, scrollHeight: el.scrollHeight || 0 };
    }"""
    )


async def run_select_all_until_top(page):
    last_state = None
    stable_rounds = 0
    for round_num in range(PLUGIN_SELECT_MAX_ROUNDS):
        ok = await _open_select_dropdown_and_choose_all(page)
        if not ok and round_num == 0:
            print("      [!] SELECT / All (default) button not found")
        delay = random.uniform(PLUGIN_SELECT_WAIT_MIN, PLUGIN_SELECT_WAIT_MAX)
        await asyncio.sleep(delay)
        state = await _get_scroll_state(page)
        key = (state.get("scrollTop"), state.get("scrollHeight"))
        if last_state is not None and key == last_state:
            stable_rounds += 1
            if stable_rounds >= PLUGIN_SCROLL_STABLE_ROUNDS:
                print(f"      Reached top after {round_num + 1} rounds")
                return True
        else:
            stable_rounds = 0
        last_state = key
        if round_num > 0 and round_num % 5 == 0:
            print(f"      SELECT All round {round_num + 1}")
    print("      Max rounds reached")
    return True


async def _dismiss_popup(page):
    try:
        await page.get_by_text("导出成功！").first.press("Escape", timeout=3000)
    except Exception:
        pass
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass


async def _recover_page_after_timeout(context, page, home_url: str, timeout_nav: float = 20):
    try:
        await asyncio.wait_for(
            page.goto(home_url, wait_until="domcontentloaded", timeout=int(timeout_nav * 0.75)),
            timeout=timeout_nav,
        )
        print("      [~] Left stuck page, continuing with current tab")
        return page
    except Exception:
        pass
    try:
        new_page = await context.new_page()
        old_page = page
        try:
            await asyncio.wait_for(old_page.close(), timeout=3)
        except Exception:
            pass
        print("      [~] Opened new tab")
        return new_page
    except Exception as e:
        print(f"      [!] Tab recovery failed: {e}")
        return page


async def _export_one_via_plugin(
    page, context, url: str, download_dir: Path, skip_existing: bool, use_filter: bool
) -> bool:
    """Open one chat, check title against filter, export."""
    conv_id = _url_to_id(url)

    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(4)

    # Read title
    title = await _get_page_title(page)
    safe_title = _sanitize_filename(title)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_filename = f"{safe_title}_{timestamp}.json"
    out_path = download_dir / out_filename

    # Apply filter
    if use_filter and not _is_gla_relevant(title):
        print(f"      → Skipped (no GLA keyword): {title[:60]}")
        return False

    print(f"      → Exporting: {title[:60]}")

    # Skip if already exported (title-based, not ID-based)
    if skip_existing:
        existing = list(download_dir.glob(f"{safe_title}_*.json"))
        if existing:
            print(f"      → Already exists, skipping")
            return True

    export_ok, _ = await _wait_for_plugin_buttons(page)
    if not export_ok:
        print("      [x] Plugin 'Export Chat' button not found")
        return False

    # Output as .md
    out_filename = f"{safe_title}_{timestamp}.md"
    out_path = download_dir / out_filename

    # Snapshot before export — all known file types
    before_files = set()
    before_mtimes = {}
    for pattern in ["*.md", "*.json", "*.txt"]:
        for f in download_dir.glob(pattern):
            before_files.add(f)
            before_mtimes[f] = f.stat().st_mtime

    download_dir_abs = str(download_dir.resolve())
    try:
        cdp = await context.new_cdp_session(page)
        await cdp.send(
            "Browser.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": download_dir_abs},
        )
    except Exception as e:
        print(f"      [!] CDP download path: {e}")
    await asyncio.sleep(0.2)

    # First click — opens the popup
    try:
        await page.get_by_role("button", name="Export Chat").click(timeout=8000)
    except Exception as e:
        print(f"      [x] EXPORT click 1 failed: {e}")
        await _dismiss_popup(page)
        return False

    await asyncio.sleep(1.5)  # Let popup load

    # Second click — triggers the actual export
    try:
        await page.get_by_role("button", name="Export Chat").click(timeout=8000)
    except Exception as e:
        print(f"      [x] EXPORT click 2 failed: {e}")
        await _dismiss_popup(page)
        return False

    await asyncio.sleep(PLUGIN_EXPORT_WAIT_AFTER_CLICK)

    # Wait for new file — all types
    start = time.time()
    found = None
    while (time.time() - start) < PLUGIN_DOWNLOAD_POLL_SEC:
        await asyncio.sleep(0.5)
        for pattern in ["*.md", "*.json", "*.txt"]:
            for f in download_dir.glob(pattern):
                is_new = f not in before_files
                is_modified = f in before_mtimes and f.stat().st_mtime > before_mtimes.get(f, 0)
                if not is_new and not is_modified:
                    continue
                try:
                    target = out_path.with_suffix(f.suffix)
                    if f.resolve() != target.resolve():
                        shutil.move(str(f), str(target))
                    found = target
                    break
                except Exception as e:
                    print(f"      [!] Rename failed: {e}")
                    found = f
                    break
            if found:
                break
        if found:
            break

    if found:
        print(f"      [ok] {found.name}")
    else:
        print("      [x] No new file detected")
    await asyncio.sleep(PLUGIN_POPUP_DISMISS_WAIT)
    await _dismiss_popup(page)
    return bool(found)


async def main(args):
    from playwright.async_api import async_playwright

    cdp_url = f"http://localhost:{args.cdp_port}"
    output_dir = Path(args.output_dir)
    timeout_per_conv = args.timeout
    skip_existing = not args.no_skip
    use_filter = not args.no_filter

    print("=" * 60)
    print("Gemini GLA-Exporter")
    print(f"  Filter: {'ON — GLA chats only' if use_filter else 'OFF — all chats'}")
    print(f"  Output: {output_dir}")
    print("=" * 60)

    if not args.no_confirm:
        print(
            f"\nRequirements:"
            f"\n  1. Chrome started with --remote-debugging-port={args.cdp_port}"
            f"\n  2. amazingpaddy/ai-chat-exporter extension installed"
            f"\n  3. Logged in to Gemini, sidebar expanded"
        )
        input("\nPress Enter to start...")

    output_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = None
        try:
            print("\nConnecting to Chrome...")
            browser = await p.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            err = str(e).lower()
            if "econnrefused" in err or str(args.cdp_port) in err:
                print(
                    f"\n[x] Connection to localhost:{args.cdp_port} failed."
                    f"\n    Start Chrome with: --remote-debugging-port={args.cdp_port}"
                    f"\n"
                    f"\n    Windows example:"
                    f'\n    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222'
                )
            raise

        contexts = browser.contexts
        if not contexts:
            print("[x] No browser context found")
            return
        context = contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        print("[ok] Connected\n")

        # Phase 1: Collect URLs
        print("=" * 50)
        print("Phase 1: Collecting chat links from sidebar")
        print("=" * 50)
        await page.goto(GEMINI_APP_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        urls = await discover_conversation_urls(page)
        print(f"\n[ok] {len(urls)} chats found")

        if not urls:
            print("[!] No chats found. Logged in? Sidebar expanded?")
            return

        # Phase 2: Export
        print(f"\n{'='*50}")
        print("Phase 2: Exporting chats")
        print(f"{'='*50}")
        ok_count = 0
        skipped_count = 0
        failed_list = []

        for i, url in enumerate(urls):
            conv_id = _url_to_id(url)
            print(f"\n[{i+1}/{len(urls)}] {conv_id[:20]}...")
            success = False
            for attempt in range(2):
                try:
                    result = await asyncio.wait_for(
                        _export_one_via_plugin(
                            page, context, url, output_dir, skip_existing, use_filter
                        ),
                        timeout=timeout_per_conv,
                    )
                    if result:
                        ok_count += 1
                    else:
                        skipped_count += 1
                    success = True
                    break
                except asyncio.TimeoutError:
                    print(f"   [!] Timeout ({timeout_per_conv}s), skipping")
                    failed_list.append((conv_id, url))
                    page = await _recover_page_after_timeout(context, page, GEMINI_APP_URL)
                    break
                except Exception as e:
                    err = str(e)
                    if attempt == 0 and (
                        "Execution context was destroyed" in err or "navigation" in err.lower()
                    ):
                        print("   [!] Retrying...")
                        await asyncio.sleep(1)
                        continue
                    print(f"   [x] {e}")
                    failed_list.append((conv_id, url))
                    if "closed" in err.lower() or "destroyed" in err.lower():
                        try:
                            page = await context.new_page()
                            print("      [~] New tab opened")
                        except Exception:
                            pass
                    break

            while len(context.pages) > 1:
                try:
                    await context.pages[-1].close()
                except Exception:
                    break

            delay = random.uniform(SLEEP_MIN, SLEEP_MAX)
            print(f"   Waiting {delay:.1f}s...")
            await asyncio.sleep(delay)

        print(f"\n{'='*50}")
        print(f"Done:")
        print(f"  Exported : {ok_count}")
        print(f"  Skipped (no keyword / already exists): {skipped_count}")
        print(f"  Failed   : {len(failed_list)}")
        print(f"  Output   : {output_dir}/")
        print(f"{'='*50}")

        if failed_list:
            report_name = f"failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            report_path = output_dir / report_name
            with open(report_path, "w", encoding="utf-8") as f:
                for conv_id, url in failed_list:
                    f.write(url + "\n")
            print(f"\n[!] {len(failed_list)} failed chats → {report_path}")

        try:
            await browser.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main(parse_args()))

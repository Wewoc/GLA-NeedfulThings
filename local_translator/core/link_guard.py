"""
link_guard.py

Protects URLs, file paths, and markdown links from being mangled by the
translation pipeline (S1/S2). Uses the same placeholder-protect/restore
pattern as TermEngine, but with an independent namespace (§Lxxxxxxxx§)
to avoid collisions with §Txxxxxxxx§.

Pipeline position (mindset-independent, sits OUTSIDE TermEngine):

    raw_text
        -> link_guard.protect()
        -> TermEngine.protect()
        -> S1 (translate)
        -> TermEngine.restore()
        -> link_guard.restore()
        -> output

Rationale: link text (if plain prose, e.g. "Firmenwebseite") should still
be translatable, so only the URL/path itself is wrapped, not the whole
markdown link construct (except where the anchor-text heuristic decides
the link text itself is non-translatable, e.g. a filename).

Detection order matters — earlier rules consume matches before later,
broader rules could misfire on them:

    1. Markdown links   [text](url)
    2. Bare URLs        https://...
    3. Windows paths    C:\\... 
    4. UNC paths        \\\\server\\share...
    5. Backtick codespans containing a path separator, e.g. `src/docs/x.md`

Anything else (bare prose paths without backticks, e.g. "liegt unter
src/docs/") is intentionally left untouched — see project notes on the
open grey-zone decision (possible future LLM batch-call candidate).
"""

from __future__ import annotations

import re
import secrets
import string
from dataclasses import dataclass, field


PLACEHOLDER_PREFIX = "§L"
PLACEHOLDER_SUFFIX = "§"
PLACEHOLDER_ID_LEN = 8
PLACEHOLDER_ALPHABET = string.digits  # keep numeric, mirrors TermEngine §Txxxxxxxx§ style

FILE_EXTENSIONS = {
    ".md", ".pdf", ".docx", ".json", ".txt", ".csv",
    ".yaml", ".yml", ".py", ".xlsx", ".zip",
}

# --- Regex patterns -----------------------------------------------------

# [text](url) — capture text and url separately so we can decide per-part
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")

# bare URLs (http/https), stops at whitespace or a closing paren/bracket
_BARE_URL_RE = re.compile(r"https?://[^\s)\]}>]+")

# Windows drive paths: C:\... (stops at whitespace)
_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s]+")

# UNC paths: \\server\share\...
_UNC_PATH_RE = re.compile(r"\\\\[^\s]+")

# backtick codespans, evaluated for path-likeness after matching
_CODESPAN_RE = re.compile(r"`([^`]+)`")


@dataclass
class LinkGuardResult:
    """Result of protect(): the placeholder-substituted text plus the
    mapping needed to restore the originals."""
    protected_text: str
    mapping: dict[str, str] = field(default_factory=dict)


def _new_placeholder(used_ids: set[str]) -> str:
    while True:
        pid = "".join(secrets.choice(PLACEHOLDER_ALPHABET) for _ in range(PLACEHOLDER_ID_LEN))
        if pid not in used_ids:
            used_ids.add(pid)
            return f"{PLACEHOLDER_PREFIX}{pid}{PLACEHOLDER_SUFFIX}"


def _should_protect_linktext(text: str) -> bool:
    """Anchor-text heuristic for markdown links: True = treat as
    non-translatable (e.g. filename), False = leave translatable prose."""
    stripped = text.strip()
    if any(stripped.lower().endswith(ext) for ext in FILE_EXTENSIONS):
        return True
    if " " in stripped:
        return False  # looks like prose ("Firmenwebseite", "Company Website")
    return True  # grey zone (e.g. "Docs", "Link") — default to protect


def _is_pathlike(codespan_content: str) -> bool:
    return "/" in codespan_content or "\\" in codespan_content


def protect(text: str) -> LinkGuardResult:
    """Replace URLs/paths/links in `text` with placeholders.
    Returns the substituted text plus a mapping for restore()."""
    mapping: dict[str, str] = {}
    used_ids: set[str] = set()
    result = text

    # 1. Markdown links
    def _md_link_sub(m: re.Match) -> str:
        link_text, url = m.group(1), m.group(2)
        url_ph = _new_placeholder(used_ids)
        mapping[url_ph] = url
        if _should_protect_linktext(link_text):
            text_ph = _new_placeholder(used_ids)
            mapping[text_ph] = link_text
            return f"[{text_ph}]({url_ph})"
        return f"[{link_text}]({url_ph})"

    result = _MD_LINK_RE.sub(_md_link_sub, result)

    # 2. Bare URLs (that weren't already consumed by rule 1)
    def _bare_url_sub(m: re.Match) -> str:
        ph = _new_placeholder(used_ids)
        mapping[ph] = m.group(0)
        return ph

    result = _BARE_URL_RE.sub(_bare_url_sub, result)

    # 3. Windows paths
    def _win_path_sub(m: re.Match) -> str:
        ph = _new_placeholder(used_ids)
        mapping[ph] = m.group(0)
        return ph

    result = _WIN_PATH_RE.sub(_win_path_sub, result)

    # 4. UNC paths
    def _unc_path_sub(m: re.Match) -> str:
        ph = _new_placeholder(used_ids)
        mapping[ph] = m.group(0)
        return ph

    result = _UNC_PATH_RE.sub(_unc_path_sub, result)

    # 5. Backtick codespans containing a path separator
    def _codespan_sub(m: re.Match) -> str:
        content = m.group(1)
        if not _is_pathlike(content):
            return m.group(0)  # leave non-path codespans untouched
        ph = _new_placeholder(used_ids)
        mapping[ph] = m.group(0)  # store WITH backticks, restore verbatim
        return ph

    result = _CODESPAN_RE.sub(_codespan_sub, result)

    return LinkGuardResult(protected_text=result, mapping=mapping)


def restore(text: str, mapping: dict[str, str]) -> str:
    """Reinsert originals for every placeholder in `mapping`."""
    result = text
    for placeholder, original in mapping.items():
        result = result.replace(placeholder, original)
    return result


if __name__ == "__main__":
    # quick manual smoke test — not a substitute for real pipeline testing
    sample = (
        "Snapshot from repo documentation.\n"
        "[CHANGELOG.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/CHANGELOG.md) · "
        "[Firmenwebseite](https://example.com)\n"
        "See also `src/docs/REFERENCE_GARMIN.md` and `ppr/core/` for details.\n"
        "Path on disk: C:\\Users\\Timo\\Documents\\notes.txt\n"
        "und/oder sollte hier NICHT geschützt werden."
    )

    guarded = protect(sample)
    print("--- protected ---")
    print(guarded.protected_text)
    print("--- restored ---")
    print(restore(guarded.protected_text, guarded.mapping))

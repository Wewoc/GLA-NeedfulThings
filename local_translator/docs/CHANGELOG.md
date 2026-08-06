# Changelog — LocalTranslate

## 2026-08-06

### Added
- `core/link_guard.py` — protects URLs, markdown links, and file paths from
  translation pipeline mangling (S1 was spelling out protocol prefixes like
  `https://` as plain text). Placeholder namespace `§Lxxxxxxxx§`, independent
  from TermEngine's `§Txxxxxxxx§`.
- Wired into both `/translate/chunk` and `/translate` endpoints in `app.py`,
  wrapping outside TermEngine — protect before S1, restore after S2 (if active).

### Notes
- Grey-zone case (bare prose paths without backticks or markdown syntax,
  e.g. "liegt unter src/docs/") intentionally left unprotected — see
  session notes for rationale.
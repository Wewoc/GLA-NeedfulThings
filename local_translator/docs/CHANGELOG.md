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

### Added
- Dedicated model selection for mindset auto-detection (`/mindset/detect`),
  decoupled from the S1 translation model. Previously `detect_mindset()`
  reused `state.active_model` — a translation model repurposed for
  classification, which likely explains the observed unreliability
  (near-constant fallback to `"general"`).
- New config key `pipeline_mindset_model` in `config.yaml` (default `""`,
  falls back to S1 model — no breaking change).
- New UI dropdown "Mindset AI" in the statusbar (`mindsetModelSelect`),
  populated from the same Ollama model list as S1/S2. Follows the S2
  pattern (request-scoped, no server state) rather than the S1 pattern
  (stateful `/ollama/set_model`) — see `REFERENCE_translator.md` for
  rationale.
- New "AI: {mindset}" label next to the mindset dropdown, shows what
  the model actually picked. Persists after translation completes —
  only cleared by `clearAll()` (✕ Clear) or overwritten by the next
  detection run, not reset automatically when translation finishes.
- Fixed: mindset auto-detection was incorrectly coupled to
  `mode === 'debounce'` (pre-existing behavior, not introduced this
  session) — Manual/Sentence modes never triggered it. First fix
  attempt (separate `mindsetDebounceTimer`, decoupled from mode) was
  itself flawed — fired on every keystroke regardless of mode, ahead
  of the actual translation trigger. Final fix: detection moved inside
  `translate()` itself as the first step, so it fires exactly once per
  translation run, uniformly across all three triggers (button, Enter,
  debounce timeout) — no separate timer needed.
- 8 new mindset classification test texts added to `test/source/`
  (`mindset_test_*.md`, one per mindset: general, technical, legal,
  medical, editorial, academic, marketing, political) — no prior test
  data existed for classification quality, only translation-quality
  benchmarks (NTREX-128).

### Changed
- `engines/ollama.py` → `detect_mindset()` signature: new optional
  `model` parameter. `app.py` → `DetectMindsetRequest` gained
  `mindset_model: str = ""`.

### Added (this session, follow-up fix)
- `detect_mindset()` now sends `options: {temperature: 0}` to Ollama.
  Without it, classification was non-deterministic — same input text
  could flip between e.g. "medical" and "general" across runs, since
  no temperature was set and the model default (~0.7–0.8) allows
  sampling variance. Fix scoped to `detect_mindset()` only —
  `translate_ollama()` and `run_s2()` intentionally keep default
  sampling.

### Known issue — NOT fixed, logged for a future session
- S2 language drift check (`run_s2()` in `engines/ollama.py`) only
  catches drift back to the *source* language (non-ASCII ratio
  threshold, calibrated for German umlauts). Observed case: S2 model
  `aya-expanse:latest` translated EN→ES instead of editing EN in
  place — Spanish has too low a non-ASCII ratio to trip the existing
  `output_non_ascii > input_non_ascii + 0.15` check. Result: S2
  silently returns Spanish text instead of falling back to S1.
  Needs a proper fix (e.g. language detection, not just ASCII ratio)
  — out of scope for the mindset-detection session, tracked here for
  follow-up.

### Not part of this session (deliberately out of scope)
- Floating Mindset (per-chunk detection) — separate roadmap item,
  mindset is still detected once for the whole text, before chunking.
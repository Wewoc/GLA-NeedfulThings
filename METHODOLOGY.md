# Methodology — Disciplined AI-Delegated Engineering

**Most AI coding workflows optimize for autonomous code generation.**
**This methodology optimizes for human ownership, auditability, and controlled change.**

> This is not a "vibe coding" guide in the common sense of the term. Vibe coding
> usually means: the AI generates, the human accepts, speed is the point. This
> document describes the opposite trade-off — using AI to generate code fast,
> while keeping every change reviewable, reversible, and owned by a human.
>
> The tools in this repository (`change_script/`, `scanner/`, `build_dep_map/`,
> `scope_snapshot/`) exist to support this workflow. This document explains the
> *why* behind them, independent of any single project. A full worked example
> — [Garmin Local Archive](https://github.com/Wewoc/Garmin_Local_Archive) —
> is linked at the end.
>
> **In one sentence:** Disciplined AI-delegated engineering is a workflow for
> building software with AI while preserving human ownership, auditability,
> and deterministic change control.

---

## 1. Why this exists

AI coding assistants are fast at generating plausible-looking code and bad at
knowing when they're wrong. Left unchecked, that combination produces code
that works today and breaks silently later — because nobody actually read the
diff, or because the AI "helpfully" touched something outside the requested
scope.

The methodology below trades some of that speed for a property that matters
more in the long run: **every change stays legible to the human who owns the
project.** The AI proposes, the human reviews and applies, nothing lands
without both.

---

## 2. Core principles

### Evaluate ≠ Decide

Tools report, humans decide. A dependency scanner, a linter, an AI code
review — none of them get veto power. They surface information; a human
makes the call. This applies recursively: the AI assistant itself only
evaluates and proposes changes, it never applies them directly.

### Single Owner

Every piece of state — a file, a config value, a section of a data
structure — has exactly one module or script that writes it. Everything else
may read, nothing else writes. This eliminates an entire class of bugs where
two pieces of code silently fight over the same file, and makes it trivial
to answer "what could have changed this?" during debugging.

In practice this shows up as a simple table: module → what it exclusively
owns. Any change that would give a second module write access to the same
resource is treated as a regression, not a design choice to weigh.

Note the scope of "owns": it means *exclusive write access*, not exclusive
knowledge. Other modules may still read the resource — they just never
write to it. Confusing the two leads to unnecessarily rigid designs where
nothing is allowed to even look at data it doesn't own.

### Silent failure is the primary audit lens

A tool that exists to prevent silent data loss must not itself introduce
silent data loss or silent scope creep. Every proposed change is evaluated
against the question: *could this fail quietly and I wouldn't notice until
much later?* Prefer loud, early failure over graceful-looking degradation
that hides a real problem.

### Read before you write

An AI proposing a change to a file must have actually read the current
content of that file in this session — never reconstruct it from memory or
from an earlier version. This sounds obvious; it is also the single most
common source of broken anchors and phantom diffs in practice.

---

## 3. Hard rules — process

These are process invariants, not style preferences. Violating them isn't
technical debt to pay down later, it's a defect to fix now.

- No build instruction without a current dependency report for the affected
  scope. Know what a change touches before touching it.
- No anchor/diff written without first reading the target file's current
  state.
- No release without a clean lint pass and a green test suite.
- Full-file delivery only above a change threshold, configurable per project
  (this repo defaults to 30%); everything below that is a targeted
  anchor/diff.
- Every non-trivial change is documented at the point it's made, not
  reconstructed afterward.

---

## 4. Session workflow — the general pattern

A disciplined AI-assisted change session follows four phases, regardless of
project size. Skipping a phase is where scope creep and untracked breakage
come from.

```
1. Dependency Scan   →  what does the target area currently touch,
                         and what touches it?
2. Scope Freeze      →  lock the exact set of files this session is
                         allowed to change, based on the scan
3. Build              →  AI proposes changes as anchors/diffs against
                         the frozen scope only
4. Review Gate        →  human applies, tests run, AI and/or external
                         models review before it's considered done
```

**1. Dependency Scan.** Before any change, run a scan of the target area to
surface what currently depends on it and what it depends on. In this repo:
`scanner/`. The output is a report the human (or the AI, evaluating on the
human's behalf) filters for false positives — pattern-based scanners flag
more than is actually relevant.

**2. Scope Freeze.** Turn the confirmed relevant hits from the scan into an
explicit, closed list of files this session is allowed to touch. In this
repo: `scope_snapshot/`. No build instruction is issued until this snapshot
exists. This is the step that prevents an AI assistant from "helpfully"
wandering into adjacent files.

**3. Build.** The AI proposes changes strictly within the frozen scope, as
anchor/diff blocks (see §5) — never as a full rewrite unless justified by
the change-threshold rule. One item at a time, with explicit confirmation
before moving to the next, is strongly preferred over batching multiple
unrelated changes into one delivery.

**4. Review Gate.** The human applies every anchor manually — the AI never
applies its own changes directly. Tests run after each meaningful change,
not just at the end. For cross-cutting refactors or anything security-
relevant, an additional multi-model review (§6) is mandatory, not optional.

This is deliberately more overhead than "just ask the AI to fix it." That
overhead is the point — it's what keeps a fast-moving AI-assisted codebase
auditable months later.

### Worked example

Request: *"Add timeout support to the API client."*

```
1. Dependency Scan
   → scan api_client.py
   → hits: api_client.py, config.py, request_handler.py (false positive:
     logging_utils.py — flagged by pattern match, filtered out on review)

2. Scope Freeze
   → api_client.py
   → config.py
   (request_handler.py excluded: only reads response objects, no timeout
    logic needed there — confirmed during scan review)

3. Build
   → anchor delivered for api_client.py: add `timeout` param, wire into
     the request call
   → anchor delivered for config.py: add `DEFAULT_TIMEOUT` constant
   → nothing else touched, even though the AI "noticed" an unrelated
     retry-logic gap while reading api_client.py — out of scope, reported
     separately instead of silently fixed

4. Review Gate
   → human applies both anchors
   → test suite run: green
   → single-file, non-critical change → no multi-model review required
     (see §6 for when it would be)
```

The value isn't the timeout feature itself — it's that `logging_utils.py`
and the unrelated retry-logic issue never entered the change, even though an
unconstrained AI session would likely have touched both "while it was in
the area."

---

## 5. Anchor delivery format

A precise, parseable diff format that both a human and a tool can apply
mechanically, without the AI ever touching the filesystem directly.

### Format

````markdown
## FILE: path/to/file.py

### OLD
```python
# exact code as it currently stands in the file
```

### NEW
```python
# replacement code
```
````

**Rules:**

- `OLD` / `NEW` labels sit outside the code fences, as plain text.
- Code fences are mandatory — a missing fence is a parser error, not a
  cosmetic issue.
- Multiple anchors per file are allowed, each as its own `OLD`/`NEW` pair.
- Deletion: the `NEW` block contains only `#DELETE`.
- The target file must have been read in-session before the anchor is
  written — never reconstructed from memory.
- Full-file delivery only above the change-threshold (this repo: 30%) or on
  explicit request.

### Applying anchors

A two-pass parser applies these mechanically:

1. **Pass 1 — Locate:** find every `OLD` block in every referenced file.
2. **Pass 2 — Write:** apply every `NEW` block.

Overlap detection catches `OLD` blocks that overlap each other — a reliable
signal that the anchor itself has a bug. In this repo: `change_script/`
(`apply_anchors.py` + `run_anchors.bat`).

---

## 6. Multi-model review gate

For cross-module refactors or anything touching security-relevant code,
independent review from more than one AI model is mandatory, not optional.
The intersection of findings across models is treated as high-priority
signal — three or four independent models flagging the same issue is a much
stronger signal than one model's opinion, however confident it sounds.

Two ways to run this:

- **Ad hoc**, by pasting the diff into separate sessions with different
  models (Gemini, ChatGPT, Copilot, etc.) and comparing findings manually.
- **Structured**, using [agent-discussion-arena](https://github.com/Wewoc/agent-discussion-arena)
  — a local, Ollama-only multi-agent discussion setup built for exactly this
  kind of structured cross-model review, with presets and a dedicated
  code-review setting.

Either way, the AI that proposed the original change evaluates each finding
critically before anything is adopted — a flagged issue isn't automatically
correct just because a model raised it.

---

## 7. Case study: Garmin Local Archive

The full version of this methodology, applied to a real multi-layer project
over many releases, is documented in the
[GLA Developer Handbook](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs).
It shows the same four-phase session workflow, the same anchor format, and
the same review gate — plus the project-specific architecture rules
(sole-write ownership tables, layer boundaries, hard rules) that sit on top
of this general methodology but aren't part of it.

Use that handbook as the "what it looks like at scale" reference; use this
document as the portable pattern for any new project.

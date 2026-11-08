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
>
> The workflow exists in two modes that share the same principles (§2):
> working in a **chat** without file access (§4.1) and working in
> **Claude Code / CLI** with direct file access (§4.2). The tools listed
> above were built for the chat mode; in the CLI mode the model does part of
> their job itself.

---

## 1. Why this exists

AI coding assistants are fast at generating plausible-looking code and bad at
knowing when they're wrong. Left unchecked, that combination produces code
that works today and breaks silently later — because nobody actually read the
diff, or because the AI "helpfully" touched something outside the requested
scope.

The methodology below trades some of that speed for a property that matters
more in the long run: **every change stays legible to the human who owns the
project.** The AI proposes, the human reviews and releases each change (in a chat
by applying it, in a CLI by confirming it), nothing lands without both.

---

## 2. Core principles

### Evaluate ≠ Decide

Tools report, humans decide. A dependency scanner, a linter, an AI code
review — none of them get veto power. They surface information; a human
makes the call. This applies recursively: the AI assistant itself only
evaluates and proposes changes. A change lands only after the human has
confirmed that specific step — in a chat the human applies it, in a CLI the
assistant applies it under that confirmation, never on its own.

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
  scope (chat: the scanner report; CLI: a repository-wide search for every
  symbol involved, §4.2). Know what a change touches before touching it.
- No anchor/diff written without first reading the target file's current
  state.
- No release without a clean lint pass and a green test suite.
- Full-file delivery only above a change threshold, configurable per project
  (this repo defaults to 30%); everything below that is a targeted
  anchor/diff.
- Every non-trivial change is documented at the point it's made, not
  reconstructed afterward.

---

## 4. Session workflow

The principles in §2 and the rules in §3 hold in every mode. What changes
between modes is who can see the files and who is allowed to touch them.

| | Chat (§4.1) | Claude Code / CLI (§4.2) |
|---|---|---|
| The model sees the files | No — only what the human pastes in | Yes — reads and searches them itself |
| "What does this touch?" | Scanner report and scope snapshot | Reading plus a repository-wide search per symbol, result named before the build order |
| Who changes the files | The human applies the anchors | The model edits in place, after the human confirmed that step |
| Where the gate sits | The human applying each anchor | Confirmation per step, enforced by the tool's permission mode |
| Role of the anchor | The delivery — what gets applied | The record — written afterwards from the actual state |
| Traceability | Anchors and test run | Anchor record and change journal |

### 4.1 Working in a chat (no file access)

In a chat the model cannot see the project. The human is the only bridge
between the model and the files, and the workflow is built around that gap.
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
anchor/diff blocks (see §5.1) — never as a full rewrite unless justified by
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

#### Worked example (chat mode)

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

### 4.2 Working in Claude Code / CLI (direct file access)

When the assistant runs inside the project (Claude Code or a comparable CLI
agent), the gap that shaped §4.1 is gone: it can read files and search the
code itself. The principles do not change; the mechanics do, and the
human's gate moves from *applying* a change to *confirming* it.

```
1. Cross-check      →  read the target files, then search the whole
                       repository for every symbol the change touches
2. Scope            →  name the files this step will change, nothing else
3. Build            →  one confirmed step at a time, edited in place
4. Verify & Record  →  run the checks, then write the change record
```

**1. Cross-check.** Read the file first, in this session — directly from
disk, never from memory of an earlier session. Before an edit is proposed
for a symbol (a function, constant, class attribute, label set), search the
whole repository for every reference to it and name the result — files and
places — before the build order is worded. In most projects this replaces
the scanner and the scope snapshot of §4.1: the same question ("what does
this touch?"), answered on the live files instead of from a report that may
already be stale. The scanner tools remain useful where a persistent,
comparable report is wanted, for example a dependency delta between
versions. Reading and searching never need confirmation.

**2. Scope.** The files this step will change are stated before anything
is written. A file the model notices while reading that is not on the list
is reported, not changed — the same discipline as in the chat example,
without a separate snapshot.

**3. Build.** The gate is a confirmation per step: no write, edit, or
state-changing command until the human has confirmed that specific step,
and a confirmation never carries over to the next one. Treat this as a
technical gate, not just a convention — run the agent in a permission mode
that asks before edits. A rule that exists only as text is a request; a
rule the tool enforces is a gate. Exceptions are explicit and narrow (for
example, the change journal below may be written as part of the confirmed
step). Edits are small and targeted; a whole-file rewrite only above the
change threshold of §3.

**4. Verify & Record.** The model runs the checks that exist and reports
them as they are — red as red, skipped as skipped. Its own run is evidence,
not approval; the human confirms. The change is then recorded in two layers
with separate jobs and no overlap:

- **The change record** — an anchor file (§5.2). It answers: which file
  changed how.
- **The change journal** — everything else: the reason, the evaluation and
  options, the cross-check result, findings with their root cause, how it
  was verified, and what was deliberately left alone. It answers: why, what
  was found, how was it checked.

What is in one is not repeated in the other (the journal names the anchor
file, nothing more). A step without a journal entry, or a changed file
without a change record, cannot be reconstructed by a later session.

#### Worked example (CLI mode)

Request: *"Add timeout support to the API client."*

```
1. Cross-check
   → read api_client.py; search the repo for every use of the request call
     and the config constants involved
   → result named: api_client.py, config.py, request_handler.py
     (reads response objects only — no timeout logic needed there);
     the logging_utils.py hit is a false positive

2. Scope
   → api_client.py, config.py

3. Build
   → plan summarized, human confirms this step
   → two in-place edits: `timeout` param in api_client.py,
     DEFAULT_TIMEOUT in config.py
   → the unrelated retry-logic gap noticed while reading is reported
     as a separate finding, not touched

4. Verify & Record
   → test suite run, reported with its numbers: green
   → anchor record for both files, written from the real state and
     checked read-only
   → journal entry: reason, cross-check result, the retry-logic gap
```

The result matches the chat example — `logging_utils.py` and the unrelated
retry-logic issue never entered the change — and the record shows a later
session exactly what changed and why.

---

## 5. Anchor format

A precise, parseable diff format that both a human and a tool can read
mechanically. What it is for depends on the mode (§4): in a chat it is the
**delivery** — the model hands it over and never touches the filesystem; in
Claude Code / CLI it is the **record** of an edit that has already been
made. The format is the same in both.

### 5.1 Format and delivery

```markdown
## FILE: path/to/file.py

### ALT
<<<ALT>>>
# exact code as it currently stands in the file
<<<ALT_END>>>
### NEU
<<<NEU>>>
# replacement code
<<<NEU_END>>>
```

**Rules:**

- The headings `### ALT` and `### NEU` are each followed by a block between
  sentinel markers (`<<<ALT>>>` … `<<<ALT_END>>>`, `<<<NEU>>>` …
  `<<<NEU_END>>>`), each marker on its own line. Sentinels replace code
  fences because a fence inside the content (for example an embedded
  example in documentation) can be mistaken for the closing fence and
  silently truncate the block. Older deliveries that use plain backtick
  fences are still read as a fallback.
- The path after `## FILE:` is relative to the project root; the file must
  exist.
- `ALT` must occur exactly once in the target file (compared without
  line-ending differences and trailing whitespace) — otherwise the anchor
  is reported as not found or ambiguous. Too-short anchors get neighbouring
  lines until they are unique.
- Multiple `ALT`/`NEU` pairs per file are allowed; their `ALT` regions must
  not overlap.
- Deletion: the `NEU` block contains only `#DELETE`; an empty `NEU` block
  is an error.
- Re-running a delivery is harmless: an anchor whose `NEU` text is already in
  the file is reported as already applied and skipped instead of being
  applied twice (which would, for example, duplicate appended text). Write
  `NEU` as a complete block.
- The target file must have been read in-session before the anchor is
  written — never reconstructed from memory.
- Full-file delivery only above the change-threshold (this repo: 30%) or on
  explicit request.

### Applying anchors (chat mode)

A two-pass parser applies a delivery mechanically:

1. **Pass 1 — Locate:** find every `ALT` block in every referenced file;
   nothing is written.
2. **Pass 2 — Write:** apply every `NEU` block, only if Pass 1 found all
   of them.

Overlap detection catches `ALT` blocks that overlap each other — a reliable
signal that the anchor itself has a bug. In this repo: `change_script/`
(`apply_anchors.py` + `run_anchors.bat`).

### 5.2 Anchor as record (CLI mode)

In Claude Code / CLI the model edits the file in place, after the human
confirmed the step. The anchor file is written afterwards, from the actual
file state — `ALT` is the text before the edit, `NEU` the text after —
never from memory. It is not an instruction to be applied but a record: it
answers *which file changed how*, and it holds the state before the change,
which keeps the edit reversible even in a project without version control.
Before it counts, it is checked read-only: every anchor parses and every
`NEU` text is present in its target file (`parse_delivery` in
`change_script/apply_anchors.py` does the parsing; the applier itself is
not run). Why the change was made, what was found and how it was verified
belong in the change journal (§4.2), not in the anchor — and the other way
round.

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

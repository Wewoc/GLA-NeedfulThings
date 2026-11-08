---
name: disciplined-ai-engineering-cli
description: Governs how Claude works on an existing codebase from Claude Code or another CLI agent with direct file access, when the project owner wants to stay in control of every change. Use this whenever Claude is about to edit, create or delete files in a project the user owns and reviews, especially when the user says things like "erst bewerten", "nicht gleich umsetzen", "assess first", "don't just implement this", and whenever a task touches more than a trivial snippet of working code. It adds per-step confirmation, a repository-wide cross-check before every edit and a traceable change record, so that no edit is silent, unreviewed or out of scope. For chat sessions without file access use the skill disciplined-ai-engineering instead; where both are installed, this one applies in Claude Code.
---

# Disciplined AI-Delegated Engineering — Claude Code / CLI

A workflow for changing a codebase from inside it while keeping every change
legible, reviewable and owned by the human. It is the CLI counterpart of the
chat workflow: same principles, different mechanics. Because you can read and
edit files yourself, the owner's gate moves from *applying* a change to
*confirming* it. Optimizes for auditability and controlled change over speed.

## Core principle: Evaluate ≠ Decide

You evaluate and propose. The owner decides.

- **Reading, searching and grepping are always allowed** and never need
  confirmation.
- **Writing, editing, deleting, or running a command that changes state needs
  a confirmation of that specific step**, given in chat. A confirmation never
  carries over to the next step. Explaining what you would do and then doing it
  in the same turn is not a confirmation.
- A permissive permission mode (auto-accept) is the owner's tool setting, not a
  confirmation. Where the tool allows it, recommend a mode that asks before
  edits: a rule that exists only as text is a request, a rule the tool enforces
  is a gate.

## Name the stage first

State the stage before the content of every response:

- **Assess** (Bewerten) — an opinion on what is asked, what it touches, what
  could go wrong. No changes.
- **Analyze** (Analyse) — investigate causes or options: read files, trace a
  bug, map dependencies. Still no changes.
- **Build** (Bauauftrag) — the change itself, only after the owner confirmed
  the plan from the stage before.
- **Correction** (Korrektur) — fix exactly the named spot, nothing next to it.

For small, self-contained changes, fold Analyze into Assess. An emergency stop
("Stopp — prüf mal X" / "stop — check X") halts everything and returns to
Assess.

## The four phases of a change

```
1. Cross-check      →  read the target files, then search the whole
                       repository for every symbol the change touches
2. Scope            →  name the files this step will change, nothing else
3. Build            →  one confirmed step at a time, edited in place
4. Verify & Record  →  run the checks, then write the change record
```

**1. Cross-check.** Read each file you will touch in this session, directly
from disk — never from memory of an earlier session or an earlier version in a
long conversation. Before proposing an edit for a symbol (function, constant,
class attribute, label set), search the repository for every reference to it
and name the result in a line or two (files, places) before you word the
build order. Scale this to the change: for a small self-contained script,
reading the file is enough; for anything that could ripple (shared state,
imports, config read elsewhere), the search is mandatory.

**2. Scope.** State the files this step will change before anything is written.
A file you notice while reading that is not on the list is reported, not
changed.

**3. Build.** Summarize the planned diff briefly before writing. One change per
confirmation — no "while I was at it". Make small, targeted in-place edits; a
whole-file rewrite only when more than about 30 % of the file changes or the
owner asks for it. Standalone files (scripts, entry points, configs) are
handled explicitly, never implicitly through another file's edit. Working code
is not touched without necessity: "it could be cleaner" is an aside, not an
action.

**4. Verify & Record.** Run the checks that exist and fit the change (tests,
lint, build) and report them as they are: red is red, skipped is skipped,
not-run is not-run. Your own run is evidence, not approval — the owner
confirms. Then record the change in two layers with separate jobs and no
overlap:

- **Change record** — what changed in which file: an anchor or diff written
  *after* the edit from the actual file state (before text, after text), never
  from memory, and checked read-only against the file.
- **Change journal** — everything else: the reason, the evaluation and options,
  the cross-check result, findings with their root cause, how it was verified,
  and what was deliberately left alone.

Follow the project's own convention for both if it has one. If it has none,
end the step with a short summary instead: files changed, what changed, how it
was verified, what was not verified.

## Ownership and audit lens

- **Single Owner.** Each piece of state (a file, a config value, a section of a
  data structure) is written by exactly one place. Other code may read it. A
  change that adds a second writer is a regression, not a design choice — flag
  it even when not asked.
- **Silent failure is the primary audit lens.** For every proposed change ask:
  could this fail quietly and go unnoticed until much later? Prefer loud, early
  failure over degradation that looks fine but drops data, skips a step or
  falls back to a default. Say so explicitly when reviewing.
- **Findings are not fixed on the spot.** A bug or risk you notice outside the
  scope is reported separately with its evidence; the owner decides when and
  whether to act.

## Debugging discipline

- Runtime errors: read the actual console output or log first, then theorize.
- After two hypotheses that are not confirmed by real file content or real
  output, stop guessing: read the file, ask for the log or the exact error text.

## Second opinion

For high-stakes changes (security-relevant, cross-module, hard to reverse),
recommend a second source — another model, a linter, a test run, a colleague —
rather than treating your own review as sufficient. Findings that show up from
several independent sources are a stronger signal than any single opinion; you
still evaluate each one on its merits.

## Documentation

Match the effort to the project: for small personal scripts a short summary or
changelog line is enough; for larger or shared projects document every
non-trivial change at the point it is made, and treat drift between docs and
code as a defect, not cosmetic debt.

## Precedence

If the project has its own instructions (a `CLAUDE.md` or similar) with
stricter or more detailed rules — required steps, file locations, naming,
tooling — those take precedence. This skill is the baseline, not a ceiling.

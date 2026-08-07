# Audit Methodology — Structured Periodic Assessment for AI-Delegated Systems

> This document is the periodic-assessment counterpart to
> [`METHODOLOGY.md`](./METHODOLOGY.md). That document governs the moment of
> *change* — how a single modification gets proposed, reviewed, and applied.
> This document governs the moment of *standing back* — how the system as a
> whole gets assessed, independent of any single change, in a way that stays
> comparable across repeated runs over the project's lifetime.
>
> The two are designed to be read independently. Someone only interested in
> the anchor-delivery workflow doesn't need this document; someone only
> interested in running a reliability or security audit doesn't need the
> change workflow. Where they touch — evidence discipline, source-of-truth
> rules — the same principle is restated here rather than assumed.

---

## 1. Why this exists

A single AI-reviewed change can be verified in isolation: read the diff,
check it against the stated intent, done. A system's overall health cannot
be verified that way — it requires deliberately stepping back from any one
change and asking a different kind of question: *given everything that has
accumulated over many changes, where does this system actually stand right
now, and is that assessment worth anything six months from now when it's
run again?*

AI models are reasonably good at generating a plausible-sounding assessment
on request. They are not reliably good at making that assessment
*consistent* — with itself internally, across sections, and across repeat
runs — unless the prompt structurally forces it. Two findings describing
the same root cause drift into different severity scores. A second run six
months later silently re-derives everything from scratch instead of
tracking what changed. A finding gets stated with the confidence of
something read in the code when it was actually inferred by analogy.

This document generalizes the guardrails that prevent that drift, extracted
from repeated real audit runs on a production project. It does not
prescribe *what* to audit (reliability, security, performance, licensing —
any framework can sit inside this skeleton) — it prescribes the structural
discipline that keeps any such audit trustworthy and comparable over time.

The entry point into this pattern was not a software-engineering idea that
happened to cite a standard for credibility. It runs the other way: the
underlying logic — bound the system, identify hazards, assess and evaluate
risk, mitigate, document residual risk — is CE-marking / Machinery
Directive risk assessment (ISO 12100), carried over from a mechanical
engineering background into software. The three-stage mitigation hierarchy
in particular (§2, below) is inherited directly from that world, not
invented for this context. Framing an audit this way is itself a deliberate
transfer of an established, regulator-grade discipline onto a domain that
doesn't otherwise require it.

---

## 2. Core principles

### Precondition Gate

A model cannot reliably self-report its own configuration — which model,
what effort/thinking setting, whether it actually has repository access —
from inside the running session. If the audit's evidence discipline depends
on repository access, that has to be confirmed by the human *before* the
prompt is sent, not checked by the model after the fact. When a stated
precondition isn't met, the correct behavior is to abort and name the
missing precondition — not to proceed with reduced rigor and present the
result as if it were the full audit.

### Evidence-Tiered Findings

Every finding carries an explicit confidence label — not just a severity.
A three-tier scheme works well:

- **Confirmed** — a specific code location was read that directly shows the
  described behavior. A citation that only makes a finding *plausible*
  ("this threading pattern could cause X") is not Confirmed; the causal
  path itself has to be visible in the code, not merely adjacent to it.
- **Probable** — strong indirect evidence (a pattern repeated elsewhere in
  the codebase, a documented but unverified architecture decision) without
  a direct code citation for this specific instance.
- **Hypothesis / Assumption** — plausible, but not verifiable from what was
  available (e.g. would require runtime measurement, or the relevant file
  wasn't accessible). Never allowed to silently read as a confirmed fact;
  collected in its own "open items" section rather than folded into the
  main findings.

Findings marked Hypothesis/Assumption do not feed into an aggregate
severity or risk score without that caveat traveling with them.

### Fixed Scoring Grid, Deterministic Aggregation

Score each finding along a small number of independent dimensions (e.g.
likelihood, impact, detectability) on a fixed scale, then combine them with
an explicit, unchanging rule — not case-by-case judgment. A useful default:
one dimension has veto power for the worst outcome (a rare-but-catastrophic
finding cannot be diluted by averaging), two dimensions being "worst" also
triggers the worst outcome, and everything else lands in the middle tier.

The rule matters less than that it stays *identical* across every future
run. The moment the aggregation logic is re-invented per run, scores from
different points in time stop being comparable — which defeats the purpose
of running the audit more than once.

### ID Stability Across Runs

Every finding gets a durable ID (module-prefixed, e.g. `GP-1`, `SI-3`). On a
repeat run:

- If the underlying issue still exists, keep its ID — don't renumber.
- If it's resolved, mark it "resolved, see rationale" — don't delete the ID
  and don't reuse the number for something unrelated.
- New findings get the next free number in their category.

This is what makes "did this get better or worse since the last run"
answerable at a glance instead of requiring a full re-diff of two
unstructured reports.

### Explicit Non-Goals per Audit

State up front what this audit type is *not* covering, and point to the
sibling audit that does. A reliability audit and a security audit looking
at the same codebase will otherwise re-discover and re-score the same root
cause from two angles with two different severity numbers — which looks
like disagreement between the audits rather than two views of one issue.
Naming the boundary explicitly ("threat actors are out of scope here, see
the security assessment for that") prevents this.

### Source-of-Truth Hierarchy

Diagrams, architecture docs, and prior reports are orientation, not
verified fact. Where any of them conflicts with what the code actually
does, the code wins — and the conflict itself is worth noting, since a
stale diagram is its own kind of finding.

### Read Before You Judge

The same discipline `METHODOLOGY.md` states for writing — never propose a
change to a file without having read its current state in this session —
applies here to reading: never write a finding based on a diagram,
docstring, or memory of an earlier version. The file has to have been
opened in this session.

### Mitigation Hierarchy over Flat Recommendation List

Countermeasures are not delivered as an unordered list of suggestions —
they follow the same three-stage hierarchy ISO 12100 uses for machinery
risk reduction, carried over directly:

1. **Inherently safe / secure by design** — remove the hazard through the
   architecture itself, so the failure mode can no longer occur at all
2. **Technical safeguard** — the hazard can still occur, but a mechanism
   detects or contains it (a guard, a lock, an atomic write, a validation
   gate)
3. **User information** — the hazard is accepted as a residual risk and
   surfaced to the human instead of engineered away (a warning, a
   documented limitation)

The point of ordering it this way is the same in both domains: a stage-3
mitigation ("document it") is only acceptable once stages 1 and 2 have
genuinely been considered and ruled out for that specific finding — not
reached for by default because it's the cheapest option. When a finding's
proposed countermeasure lands at stage 2 or 3, the audit states briefly why
stage 1 wasn't achievable, rather than skipping straight to the easier fix.

### Duplicate Suppression Across Tables

When an audit is broken into multiple tables (per module, plus one or more
cross-cutting tables), a single root cause gets scored *once*, in the table
it primarily belongs to. If it resurfaces in a cross-cutting table, it's
referenced by ID with a note on what the cross-cutting view adds — not
re-scored as if it were a second, independent finding. Otherwise the same
issue quietly inflates the total finding count and can double-count toward
an aggregate risk picture.

---

## 3. Anatomy of an audit prompt

A reusable skeleton, independent of which framework sits inside it
(ISO/IEC 25010 + FMEA, STRIDE + a regulatory annex, or something else
entirely):

1. **Precondition check** — model/effort/access requirements, human-confirmed
2. **Role & methodology statement** — what framework is being applied and why
3. **Project context** — stack, distribution, data handling; reused from
   the project's own reference documentation rather than restated by hand
4. **Explicit non-goals** — boundary against sibling audits
5. **Reference architecture** — diagram or doc, with the disclaimer that
   code has final authority over it
6. **Audit questions/dimensions** — the actual substance being probed
7. **Fixed scoring grid + aggregation rule**
8. **Finding status & evidence requirement**
9. **Output format** — one table per component, plus cross-cutting tables
   where a question genuinely spans components; duplicate-suppression rule
   stated alongside
10. **Closing** — prioritized findings and candidate countermeasures at the
    *concept* level only; explicitly not an implementation, so the human
    architect decides what becomes a build order

---

## 4. Repeat-run protocol

Audits are only worth their setup cost if they get run again. On a repeat
run:

1. Treat the prior report as a starting point, not a fact — re-verify every
   line against current code rather than carrying it forward unchanged.
2. State explicitly what changed since the last run (new modules, new data
   flows, entries from the changelog since the referenced version).
3. Keep finding IDs stable per the rule above.
4. Plan for an independent second opinion after the first pass is done —
   the same multi-model review gate `METHODOLOGY.md` describes for code
   changes, applied here to the audit's own findings instead. The first
   pass should judge on its own merits, without shaping itself to be
   "compatible" with an anticipated second opinion.

---

## 5. Audit workflow vs. change workflow

| | Change workflow (`METHODOLOGY.md`) | Audit workflow (this document) |
|---|---|---|
| Trigger | A specific change is being made | Periodic, or before a major milestone |
| Scope | The files touched by this change | The system as a whole, or a defined subsystem |
| Output | An anchor/diff, applied by the human | A report; no code touched |
| Comparability | N/A — each change is its own event | Explicitly designed to compare across runs |
| Follow-up | Tests, then done | Human reviews, *then* decides what becomes a build order |

Neither replaces the other. A clean audit doesn't mean changes can skip
their own review gate, and a disciplined change process doesn't mean the
system's accumulated state never needs a standalone look.

---

## 6. Case study

A worked example of this pattern — reliability and security audits run
against a real multi-layer project, with the fixed scoring grid, ID
tracking across versions, and the repeat-run protocol all in active use —
lives alongside the
[GLA Developer Handbook](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs).
Use it as the "what this looks like applied" reference; use this document
as the portable pattern for any new project.

---

*Draft — not yet reviewed or applied. Companion to `METHODOLOGY.md`.*

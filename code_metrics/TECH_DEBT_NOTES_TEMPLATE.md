# TECH_DEBT_NOTES.md

Living document — memory for metric-based code analyses (`code_metrics/`
reports) across versions. Purpose: not just documentation for humans, but
context-loading aid for an AI assistant in future sessions — "we already
looked at this, back then we decided X, is that still valid?" instead of
starting from zero every time.

**Relationship to a findings/issues tracker (if you have one):** a
findings tracker holds the current state of concrete, technical findings
(what's in the code, where exactly). This file holds the decision history
around metric runs — what a given analysis showed, what from it became a
tracked task, what was consciously deferred and why. An entry here can
give rise to a tracked finding; not every entry here necessarily produces
one (some things are accepted outright, without becoming a tracked item).

**Format per entry:**
- **Version/Date** — which code_metrics run, when
- **Found** — what the analysis showed, briefly
- **Roadmap** — what from this was picked up as a concrete task
- **Accepted** — what was consciously deferred, and why
- **Reference** — link to a findings-tracker entry/cluster, if any

**Order:** newest entry on top — when picking this back up, the current
state should be visible immediately, without reading through the whole
history.

---

## Analysis procedure (apply on every new comparison)

When two code_metrics snapshots (old + new) are available, work through
them in this order — not free-form looking, but a fixed checklist, so
different runs stay comparable:

1. **Place growth in rough context** (files/lines/functions from
   PROJECT_PROFILE.md) — context only, not a judgment by itself.
2. **Identify new entries over threshold** in LONGEST_FUNCTIONS.md and
   COMPLEXITY_MAP.md that were not over the respective warning threshold
   in the old snapshot.
3. **Weight nesting depth over raw line length** — in most codebases,
   length outliers turn out to be UI construction, string assembly, or
   similarly linear and harmless once actually read, while depth outliers
   are more likely to point at a real structural issue. Read new depth
   candidates first, before spending time on new length candidates. (This
   is a starting bias from experience, not a rule — verify it against
   your own project's first few runs and adjust if the pattern doesn't
   hold.)
4. **Cross-check disappeared entries** — fixed, file deleted/renamed, or
   did it just drift under the threshold by chance?
5. **Match against existing findings-tracker clusters** (if you keep one)
   — does a new finding belong to an existing pattern, or is it something
   standalone?
6. **Only for genuinely new patterns** (not for every number fluctuation)
   make a concrete proposal — actually read the code before treating a
   finding as verified, rather than acting on the metric alone.
7. **Write a new TECH_DEBT_NOTES.md entry** — Found/Roadmap/
   Accepted/Reference, insert at the top (newest first).

---

## vX.Y.Z — YYYY-MM-DD

**Found:** _What this run's code_metrics output showed, and how it
compares to the previous snapshot (files/lines/functions delta as
context; new threshold crossings; anything that lines up with active
development you already know about)._

**Roadmap:** _What from this run was picked up as a concrete task, if
anything._

**Accepted:** _What was looked at and consciously left as-is, with the
reasoning — "known and fine" is a valid outcome, but the reasoning should
be written down so it doesn't need re-deriving next run._

**Reference:** _Link to a findings-tracker entry/cluster, if you keep
one._

---

## v0.0.0 — YYYY-MM-DD (baseline, first code_metrics run)

**Found:** _Baseline numbers from the first full run of all reports:
file count, line count, function count (module/method/closure split),
class count, binding count. Note anything the length-vs-depth comparison
already shows at baseline — e.g. whether the top line-length outliers
also show up as depth outliers, or not._

**Roadmap:** _Usually none yet — a baseline run establishes the starting
point rather than producing findings on its own, unless spot-checking
already turned up something concrete._

**Accepted:** _Anything noted as "large/complex but not itself a
problem" at this stage, plus the reasoning._

**Reference:** _None yet, or a pointer to wherever findings get tracked
going forward._

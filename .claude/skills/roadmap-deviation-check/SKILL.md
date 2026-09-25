---
name: roadmap-deviation-check
description: Run a plan-vs-actual review of the portfolio roadmap (index.html) — walk through each project's Gantt milestones and work items due in a review window, ask the user whether each is on plan or has deviated, and record any deviation with a red diamond milestone plus a preserved "planned" bar showing the original plan. Use this when the user asks to "review the roadmap," "check for deviations," "do a plan check-in," "go through last month's roadmap," "did anything slip," "audit the plan vs actual," or wants a periodic/manual roadmap review (as opposed to roadmap-redmine-sync, which is about refreshing live % complete from Redmine — this skill is about the human judgment call of "did the plan itself change").
---

# Roadmap Deviation Check

This skill is a structured, conversational review of `index.html`'s Gantt (`GROUPS`)
against what actually happened. The roadmap exists to track the company's projects
against their **planned** timeline — this skill's whole job is finding where reality
diverged from the plan and recording that divergence visibly, not just updating
percentages.

This is a companion to `roadmap-redmine-sync`, not a replacement:
- `roadmap-redmine-sync` answers "how much of the scope is done" (pulled from Redmine,
  objective, per-release).
- `roadmap-deviation-check` (this skill) answers "did the plan itself change" (a human
  judgment call, per-project, walked through with the user) — a milestone slipping, a
  scope pivot, a blocker, a resequencing. This can't be pulled from an API; it has to
  be asked.

Read this whole file before editing anything — the same corruption risk called out in
`roadmap-redmine-sync` (regex find/replace eating adjacent JS fields) applies here too,
since you're editing the same file.

## Files involved

| File | Role |
|---|---|
| `index.html` | Contains `PRODUCTS` (portfolio cards) and `GROUPS` (the Gantt — each group is a project/product, each group has `rows` = workstreams, each row has `tracks` = current bars, `planned` = original-plan bars kept for contrast, and `ms` = milestone diamonds). |
| `.claude/skills/roadmap-deviation-check/scripts/validate_groups.py` | Validator for this skill — JS syntax check + GROUPS/row structural sanity (dates parse, `ms` well-formed, every `pivotReason` has a matching `planned[]` and vice versa). |

## Step 1 — Ask for the review window first

Before touching anything, ask the user what period they want to review — e.g. "review
from last month," "since our last check-in," "last two weeks," or a specific date
range. Don't guess a default; this determines which milestones and bars you'll walk
through. Convert whatever they say to an absolute date range (today's date is available
to you) and confirm it back in one line before proceeding.

## Step 2 — Build the review list for that window

For each `GROUPS` entry (each project), collect every "capsule" — a `tracks[]` bar or
an `ms[]` milestone diamond — whose date falls inside the review window:
- A bar counts if its `s` (start) or `e` (end) falls in the window, or if the window
  falls entirely inside `[s, e]` (i.e. it was "in flight" during the window).
- A milestone counts if its `d` falls in the window.

Use the bundled helper — it handles extracting the `<script>` blocks and sandboxing
`document`/`window` for you:

```bash
python3 .claude/skills/roadmap-deviation-check/scripts/list_capsules.py index.html <WINDOW_START> <WINDOW_END>
```

`<WINDOW_START>`/`<WINDOW_END>` are `YYYY-MM-DD`, from Step 1. This gives you a JSON
list, per project/row, of every capsule due for review (bars include `s`/`e`/`st`;
milestones include `d`/`color`). Group it by `group` (project) for the walkthrough.

Don't skip a project just because it looks quiet — a project with nothing in the
window is worth a one-line "nothing scheduled here in this window, skip?" rather than
silently dropping it, so the user knows it wasn't missed.

## Step 3 — Walk through each project one at a time

**Confirmed user preference: one project per message, not the whole portfolio dumped
at once.** Do not list every project's capsules in a single message and ask one
catch-all question at the end — that's the wrong shape for this step. Instead:

1. Pick the first project with capsules in the window.
2. Send **one message** covering only that project: its capsules from the window
   (label, dates, current `st`/milestone), then ask **is this on plan, or did
   something change?**
3. Wait for the user's reply before doing anything else — don't queue up the next
   project's message in the same turn.
4. Record the reply (on-plan, or a deviation with what/why — see below), then move to
   the next project and repeat.

A project with nothing in the window still gets acknowledged (a short "nothing
scheduled here in this window, skip?" as its own turn, or folded into the handoff to
the next project) rather than silently dropped — but don't stop and wait on it the way
you would a project with real capsules to review.

For each capsule the user responds to, get:
- On plan / done as planned → no edit needed, move on.
- Deviated → what changed (new date, blocker, scope cut, resequencing, pivot) and why.
  This "why" is what becomes the `pivotReason` / milestone `tip` — don't accept a bare
  date change without a reason, since the whole point of this roadmap is an audit trail
  of *why* the company's plan moved, not just that it did.

Don't move to the next project until the current one's capsules in-window are all
accounted for (on-plan or recorded as a deviation).

## Step 4 — Record each deviation in `index.html`

For every capsule the user flagged as deviated, on the matching `row` inside `GROUPS`:

1. **Preserve the original plan.** If the row doesn't already have a `planned[[...]]`
   array capturing the bar being changed, move the original bar (as it stood before
   this edit) into `planned`, and add a `pivot:` field on it explaining what changed —
   this is what renders as the faded "⚠️ PLANNED" bar for contrast against the new
   current bar. If `planned` already has a track (a prior deviation was already
   recorded here), add to the existing track array rather than starting a new one.
2. **Update `tracks[]`** to reflect the new, actual timeline/scope for that bar.
3. **Set/update `row.pivotReason`** with the user's explanation. If the row already has
   a `pivotReason` from an earlier deviation, don't overwrite it — prepend a note like
   `RESEQUENCED AGAIN: ...` in the same style as existing entries in this file (search
   `pivotReason` for examples), so the history of why a project's plan keeps moving is
   legible, not overwritten.
4. **Add a red diamond milestone** to `row.ms` marking the deviation:
   ```js
   { d: '<date the deviation became known or takes effect>', label: '<short label>', color: C.red, tip: '🔴 <what changed and why, in the user\'s words>' }
   ```
   Use `color: C.red` (`'#E24B4A'`) — this is the existing convention in this file for
   blockers/pivots (search `color:C.red` for precedent), so a deviation is visually
   distinct from a normal on-plan milestone at a glance. Prefix the `tip` with 🔴 to
   match existing red-milestone tips in the file.
5. If the bar carries a `releaseId` (it opens a Release Scorecard), tell the user this
   project also has a live-tracked release — the scorecard's dates/health note may need
   a matching update via `roadmap-redmine-sync`, but don't run that skill yourself
   unless asked; just flag it.
6. **Update the matching `PRODUCTS` entry** (`healthNote`, `currentPhase`,
   `nextMilestone`, `nextMilestoneDate` as relevant) so the portfolio card agrees with
   the Gantt — same "all three places" rule as `roadmap-redmine-sync` step 4: if you
   only edit `GROUPS`, the Products-at-a-Glance tab will show stale text.

**⚠️ Same edit-safety rule as `roadmap-redmine-sync`:** never use a lazily-bounded
regex capture to splice a new `planned`/`ms` block into a row — use precise
`str_replace` with unique surrounding context (row `title:` + enough of the
`tracks`/`ms` array to be unambiguous), or rebuild the whole row object when several
fields change at once.

## Step 5 — Validate before presenting (MANDATORY)

```bash
python3 .claude/skills/roadmap-deviation-check/scripts/validate_groups.py index.html
```

This checks: JS syntax validity, every `ms`/bar date parses, and that every
`pivotReason` has a matching `planned[]` and vice versa (a deviation recorded without
preserving the original plan, or a plan/actual split with no explanation, both get
flagged as warnings — fix them before presenting). It also reports how many red
diamonds exist in the file so you can confirm the ones you just added actually landed.

If it exits non-zero, fix the specific error and re-run — do not guess and skip
re-validation.

## Step 6 — Summarize

Report back grouped by project: which capsules were confirmed on-plan (can be a brief
one-liner per project, e.g. "3 items on track, no changes"), and for each deviation —
what changed, why, and where the red diamond landed (row + date). This is the audit
trail the roadmap exists for, so lead with the deviations, not a recap of mechanical
steps.

Don't commit or push unless the user asks — same as `roadmap-redmine-sync`, editing
the file is not itself authorization to commit.

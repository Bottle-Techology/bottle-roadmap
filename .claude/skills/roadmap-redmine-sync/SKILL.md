---
name: roadmap-redmine-sync
description: Fetch live data from Redmine (redmine.bottle.com.np) and update the multi-product portfolio roadmap (index.html) — the Release Scorecards, Products at a Glance table, and roadmap Gantt/health notes. Use this whenever the user asks to "fetch/pull/refresh/re-fetch Redmine data," "update [product]'s progress," "sync the release," or wants to add a brand-new product/release to live Redmine tracking (e.g. "just like Abhyas's release page, track project X"). Also use it if the user reports a sprint/phase transition (e.g. "we're on S3 now") that should be reflected in the roadmap file, since the same file and validation steps are involved. Covers both refreshing existing tracked releases (Abhyas, 977/Olive OTT, and any added since) and onboarding new Redmine projects into the sync pipeline.
---

# Roadmap ↔ Redmine Sync

This skill updates a single static portfolio-roadmap file (`index.html`) using live
data pulled from a self-hosted Redmine instance at `redmine.bottle.com.np`. The file
has no backend — all data is embedded directly in `<script>` blocks as JS objects/arrays.

**Read this whole file before touching the roadmap.** The most common failure mode
(hit and fixed once already) is a regex-based find/replace that silently corrupts
adjacent JS fields. Step 6 (validation) is not optional — always run it before
presenting a file to the user.

## Files involved

| File | Role |
|---|---|
| `index.html` | The roadmap itself. Contains `PRODUCTS` (portfolio-level cards), `RELEASES` (per-release scorecards), `REDMINE_SNAPSHOT` (embedded live data blob), and render functions. |
| `fetch_redmine.py` | Standalone script (bundled in `scripts/`) that hits the Redmine REST API and writes `data/redmine.json`. Also runs daily via a GitHub Action in the real repo — this skill's manual run is for making an immediate update inside a conversation. |
| `data/redmine.json` | Output of the fetch script. Structure: `{generated_at, redmine_base, status_weights, releases: {<portfolio_id>: {...}}}`. |

## Step 1 — Locate and stage the files

The user will usually have uploaded `index.html` and `fetch_redmine.py` earlier in
the conversation, or they already exist in a working directory from prior turns.

```bash
mkdir -p /home/claude/work
cp /mnt/user-data/uploads/index.html /home/claude/work/index.html   # if freshly uploaded
cp /mnt/user-data/uploads/fetch_redmine.py /home/claude/work/fetch_redmine.py
```

If they're already in `/home/claude/work/` from earlier in the conversation, just
keep using that copy — don't re-copy over live edits.

## Step 2 — Get the API key

`fetch_redmine.py` requires `REDMINE_API_KEY` as an environment variable. If the
user hasn't supplied one this conversation, ask for it (Redmine → My account → API
access key). Never hardcode it into a file that gets presented to the user.

## Step 3 — Run the fetch

```bash
cd /home/claude/work
export REDMINE_API_KEY=<key>
python3 fetch_redmine.py
```

This re-fetches **every** release currently listed in `RELEASES_TO_SYNC` inside the
script (not just one), even if the user only asked about one product — that's fine
and expected, report all movement you see, not just the one they asked about.

Compare the new `scope_pct` per release against what's currently in `index.html`'s
`healthNote` / `PRODUCTS.progress` fields (or the previous `data/redmine.json` if you
kept it) so you can tell the user what actually moved — which epics, how much.

```bash
python3 -c "
import json
d = json.load(open('data/redmine.json'))
r = d['releases']['<portfolio_id>']
print('scope', r['scope_pct'], 'dev', r['dev_pct'], 'qa', r['qa_pct'])
print('status_counts', r['status_counts'])
for e in sorted(r['epics'], key=lambda x:-x['weighted_pct']):
    print(e['weighted_pct'], e['subject'], e['status_counts'])
"
```

## Step 4 — Update `index.html`

There are three places to touch. **Do all three, or the file will show inconsistent
numbers in different tabs.**

### 4a. The release's `scope[]` array (in `RELEASES`)

Each release object (e.g. `abhyas-R1`, `977-R1`) has a `scope` array of ~13-16
feature/epic objects, each with `weight` (sums to 100 across the release),
`status` (one of `backlog|ready|in-dev|code-complete|qa|uat|ready-release|released|blocked`),
`tShirt`, `ac: {total, passed}`, `note`, and `redmineEpicId`.

Map each epic's live `weighted_pct` (from the fetch) to a local `status`:
- 0% → `backlog`
- Some movement but not majority (roughly <35-40%) → `in-dev`
- Majority of children in QA → `qa`
- All/most Done → `released`

**⚠️ CRITICAL — how to edit this safely:** Do NOT write a regex that searches
forward from a `status:` field to a nearby `redmineEpicId:` and replaces everything
in between via a capture group with a bounded-but-generous window (e.g.
`(?:(?!redmineEpicId)[\s\S]){0,400}?`). This has already corrupted a scope array
once in production use of this exact file — the lazy match can jump into the
*next* feature's block if the window is wide enough, deleting `tShirt`/`ac`/`note`/
`redmineEpicId` for every entry it touches and mangling the status string (e.g.
`'qain-dev'`, `'backlogbacklog'`).

Instead:
- For 1-3 status changes: use a precise `str_replace` with enough unique
  surrounding context (e.g. include the `name:` field) to guarantee a single match,
  and replace only the single line `status: 'X',` → `status: 'Y',`.
- For a full release refresh touching many epics at once: rebuild and replace the
  **entire `scope: [...]` array** in one `str_replace` call (old array → new array,
  both written out in full). This is slower to write but categorically avoids the
  overlap bug. This is what worked cleanly on retry after the corruption above.

### 4b. `REDMINE_SNAPSHOT` (embedded live data blob)

This is a big embedded JSON blob plus a wiring snippet, located right after the
`RELEASES` array closes:

```js
const REDMINE_SNAPSHOT = { ...huge json... };

RELEASES.forEach(r => {
  if (r.redmineSync && REDMINE_SNAPSHOT.releases[r.id]) {
    r.liveData = REDMINE_SNAPSHOT.releases[r.id];
  }
});
```

Replace it wholesale after every fetch:

```python
import json, re

with open('data/redmine.json') as f:
    d = json.load(f)

js = json.dumps(d, separators=(',',':'))
new_snapshot_block = 'const REDMINE_SNAPSHOT = ' + js + ';\n\nRELEASES.forEach(r => {\n  if (r.redmineSync && REDMINE_SNAPSHOT.releases[r.id]) {\n    r.liveData = REDMINE_SNAPSHOT.releases[r.id];\n  }\n});\n'

with open('index.html') as f:
    content = f.read()

pattern = re.compile(r"const REDMINE_SNAPSHOT = \{.*?\}\);\n", re.DOTALL)
new_content, n = pattern.subn(lambda m: new_snapshot_block, content, count=1)
assert n == 1, f"expected exactly 1 replacement, got {n}"

with open('index.html', 'w') as f:
    f.write(new_content)
```

The `computeScopePct`/`computeDevPct`/`computeQaPct` functions (in the `<script>`,
search for `function computeScopePct`) already prefer `release.liveData.scope_pct`
etc. over the manual `scope[]`-weighted approximation whenever `liveData` is
present — so refreshing this blob is what actually moves the numbers shown in the
UI, not the `scope[]` status edits (those mainly affect the human-readable
per-feature table). Don't skip this step.

### 4c. Health notes / product cards (in `PRODUCTS`)

Update the matching `PRODUCTS` entry's `healthNote`, `currentGoal`, and (if the
product's `execStatus` is sprint-based, e.g. `977`) `currentPhase` /
`nextMilestone` / `nextMilestoneDate` to reflect the real numbers and any sprint
transition the user mentioned. `progress` on `PRODUCTS` is usually a fallback only
— `productLiveProgress(productId)` (search for it) pulls the live number from
whichever release is `in-progress`, so keep the static `progress` field roughly in
sync but know the UI won't use it while a live release exists.

If the user reports something that **contradicts** existing static text (e.g. "RMS
Phase 1 is 90%, not delivered" when the file says "released, 100%"), don't silently
overwrite — ask which interpretation is correct before touching downstream fields
that depend on it (see the RMS Phase 1 correction precedent: confirm before
cascading changes to Gantt/health/gates).

### Adding a brand-new project to track (not just refreshing one)

1. Find the Redmine project slug: `GET /projects.json`, filter by name.
2. Find its version/sprint id: `GET /projects/<slug>/versions.json`. If empty, there's
   no clean version boundary — either ask the user to create one in Redmine, or fall
   back to fetching all issues in the project without a version filter (see "Projects
   without a version" below).
3. Add an entry to `RELEASES_TO_SYNC` in `fetch_redmine.py`:
   ```python
   {"portfolio_id": "<product>-R1", "redmine_project": "<slug>", "redmine_version_id": <id>, "release_label": "<name>"},
   ```
4. Run the fetch, inspect epics + weighted_pct per epic (Step 3 query above).
5. Build a new release object for `RELEASES`: `weight` per feature proportional to
   story count, scaled to sum to 100 (`round(stories_count/total_stories*100)`,
   nudge one entry by ±1 if rounding doesn't land exactly on 100 — verify with
   the validator in Step 6, which checks this).
6. Add the release's product id to the `productList` array inside `renderReleases`
   (search for `const productList = [`) so it shows up as a filter on the Releases tab.
7. Set `redmineSync: true` on the release object, then do 4b as normal.

### Projects without a Redmine version (e.g. Apple Entertainment Website)

Some Redmine projects have no version/sprint configured. In that case you can still
pull a useful snapshot — fetch all issues for the project without a
`fixed_version_id` filter — but note it can't be wired into the auto-sync
(`redmineSync`/`REDMINE_SNAPSHOT`) pipeline without either (a) a version being
created in Redmine, or (b) modifying `fetch_redmine.py` to support
project-without-version fetches. Default to (a): tell the user a version needs to
exist in Redmine for live tracking, and in the meantime just update the `PRODUCTS`
card manually with the one-off snapshot (see the Apple Entertainment Website
precedent — full weighted rollup computed inline, reported to the user, product
card updated, no `RELEASES` entry created).

## Step 5 — Sprint/phase transitions reported by the user

If the user says something like "we're on S3 now, next milestone is completing S3"
for a sprint-based product (not release-scorecard-based), this is a separate,
simpler update:
1. Update `PRODUCTS.<id>.currentPhase`, `nextMilestone`, `nextMilestoneDate`.
2. Find the product's row in the big roadmap `GROUPS`-style array near the bottom
   of the file (search for the product's `label:` in the Gantt row definitions) and
   mark the just-finished sprint's bar as complete (e.g. append "(COMPLETE)" to the
   label, change its color to a "done" color, update the tooltip with a ✓), and mark
   the new current sprint's bar/tooltip as active.
3. Check milestone dates for off-by-one drift (e.g. a sprint's `e:` end date should
   line up with the next sprint's `s:` start date — fix any day-boundary
   inconsistencies you spot while you're in there).
4. Still run the fetch (Step 3) and refresh `REDMINE_SNAPSHOT` (Step 4b) at the same
   time if the user's ask implies "update the overall file" — sprint transitions and
   data refreshes are usually asked for together.

## Step 6 — Validate before presenting (MANDATORY)

Always run the bundled validator after any edit round, before copying to outputs:

```bash
python3 scripts/validate_roadmap.py /home/claude/work/index.html
```

This checks (in order): JS syntax validity, no duplicate release IDs, every
release's `scope[]` weights sum to 100, no corrupted/invalid status strings, all
`redmineSync` releases have complete per-feature fields, and — critically —
`computeScopePct(release)` matches `release.liveData.scope_pct` for every
live-synced release (confirms the wiring in 4b actually worked).

If it exits non-zero, **do not present the file**. Read the specific error, fix it,
and re-run. Do not guess at a fix and skip re-validating.

If you don't have the script available for some reason, at minimum reproduce its
first check manually:

```bash
python3 -c "
import re
content = open('index.html').read()
scripts = re.findall(r'<script>([\s\S]*?)</script>', content)
open('/tmp/extracted.js','w').write('\n'.join(scripts))
"
node --check /tmp/extracted.js && echo OK
```

## Step 7 — Copy to outputs and present

```bash
mkdir -p /mnt/user-data/outputs/data
cp /home/claude/work/index.html /mnt/user-data/outputs/index.html
cp /home/claude/work/data/redmine.json /mnt/user-data/outputs/data/redmine.json
```

Then call `present_files` with both. In your summary to the user, lead with what
actually moved (scope % deltas per release, which epics jumped, any new risks like
untouched high-priority items near a deadline) — not a recap of the mechanical
steps you took.

## Status weighting reference

Current convention (`STATUS_WEIGHT` in `fetch_redmine.py`, confirmed with the user):

| Redmine status | Weight |
|---|---:|
| Done | 100% |
| QA | 75% |
| Re-Open / Reopen | 30% |
| In Progress | 20% |
| Hold | 0% |
| To Do | 0% |
| Backlogs | 0% |

If the user asks to change a weight, edit `STATUS_WEIGHT` in `fetch_redmine.py`
(both the version in `/home/claude/work/` and the copy you present back to them),
and also update the parallel `SCOPE_STATUS_WEIGHT` constant inside `index.html`
(search for it) so the local per-feature approximation stays roughly aligned —
though note per 4b that the live numbers come from `liveData`, not this local
constant, once a release has `redmineSync: true`.

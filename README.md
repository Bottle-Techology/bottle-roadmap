# Redmine Sync — Release Data Pipeline

Feeds live Redmine data into the Release Scorecards on `index.html`.

## How it works

```
┌─── GitHub Actions (daily 00:15 UTC / 06:00 NPT) ───┐
│                                                     │
│   scripts/fetch_redmine.py                          │
│           ↓                                         │
│   REDMINE_API_KEY (from Secrets)                    │
│           ↓                                         │
│   Redmine REST API (redmine.bottle.com.np)          │
│           ↓                                         │
│   data/redmine.json  ← committed to repo            │
│           ↓                                         │
│   GitHub Pages serves the JSON                      │
│           ↓                                         │
│   Browser fetches on Releases tab load              │
│                                                     │
└─────────────────────────────────────────────────────┘
```

The `index.html` is still 100% static — no backend, no server. The daily job just writes an updated JSON file.

## One-time setup

1. **Create a Redmine API key** (or use a service account — recommended):
   - Log in to Redmine as the service user
   - Go to My account → API access key → Show / Reset
   - Copy the 40-char hex key

2. **Add the key to GitHub Secrets**:
   - Repo → Settings → Secrets and variables → Actions → New repository secret
   - Name: `REDMINE_API_KEY`
   - Value: paste the key
   - Save

3. **Trigger the first run**:
   - Repo → Actions → "Refresh Redmine Snapshot" → Run workflow
   - Once it succeeds, `data/redmine.json` will exist in the repo
   - GitHub Pages will serve it within a minute

## Adding a new release to sync

Edit `scripts/fetch_redmine.py`, find `RELEASES_TO_SYNC`, and append:

```python
{
    "portfolio_id": "rms-R1",              # matches RELEASES array id in index.html
    "redmine_project": "formula-rms",      # slug from redmine.bottle.com.np/projects/<slug>
    "redmine_version_id": 42,              # from redmine.bottle.com.np/versions/<id>
    "release_label": "Phase 2",            # display name
},
```

Then either wait for the next scheduled run or trigger the workflow manually.

The `index.html` scorecard for that release will need one line changed to point at the new `portfolio_id` — currently only `abhyas-R2` reads from Redmine.

## Rotating the API key

1. Generate a new key in Redmine (My account → Reset API key)
2. Update the `REDMINE_API_KEY` value in GitHub Secrets
3. Next scheduled or manual run uses the new key

## Running locally

```bash
export REDMINE_API_KEY=<your-key>
python3 scripts/fetch_redmine.py
```

Writes `data/redmine.json`. No commit / push happens locally — that's Actions' job.

## Status → weight mapping

Configured at the top of `fetch_redmine.py`. Current:

| Status       | Weight |
|--------------|-------:|
| Done         |   100% |
| QA           |    75% |
| In Progress  |    40% |
| Reopen       |    30% |
| Hold         |    20% |
| To Do        |     5% |
| Backlogs     |     0% |

Adjust per your reality. "Done" = prod-ready per PM decision.

## What the JSON contains

For each release configured in `RELEASES_TO_SYNC`:

- **Release-level rollup**: total issues, status counts, weighted scope %, dev %, QA %
- **Per-Epic breakdown**: subject, child count, status counts, weighted %
- **Flat issue list**: all Stories/other with tracker, status, assignee, epic parent, direct Redmine URL

Snapshot timestamp at the top of the file.

## Troubleshooting

**Workflow fails with 403** — API key is missing, wrong, or the service account lacks read access to the project. Check Redmine → Project → Members and ensure the API-key owner is on the project.

**No commit happens** — the JSON hasn't changed since last run. Not an error; the workflow logs "No changes; skipping commit."

**Scope % is 0** — All issues are in Backlogs / Todo. Expected for a freshly-planned release. Will move as engineers change statuses.

**Some tickets don't appear on the drill-down** — They're not in the version. Set the Version field on the ticket in Redmine.

**Epic breakdown missing children** — The Stories don't have their `parent` field pointing to the Epic. Check the story in Redmine and set "Parent task" to the Epic ID.

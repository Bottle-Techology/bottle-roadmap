#!/usr/bin/env python3
"""
Fetch V2 Revamp release data from Redmine and write a snapshot JSON.

Runs daily via GitHub Actions. Reads REDMINE_API_KEY from env.
Writes to data/redmine.json for the static portfolio HTML to consume.

Adding a new release later:
    Edit RELEASES_TO_SYNC below. Each entry is (portfolio_release_id, redmine_version_id, project_slug).
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

REDMINE_BASE = "https://redmine.bottle.com.np"
API_KEY = os.environ.get("REDMINE_API_KEY")
if not API_KEY:
    print("ERROR: REDMINE_API_KEY env var not set", file=sys.stderr)
    sys.exit(1)

# ─── What to sync ─────────────────────────────────────────────────
# Portfolio-side release id (matches RELEASES array in index.html) → Redmine version id
RELEASES_TO_SYNC = [
    {
        "portfolio_id": "abhyas-R1",  # Abhyas — Revamp (V2) row in the Release Scorecards
        "redmine_project": "abhyas-dev",
        "redmine_version_id": 29,
        "release_label": "V2 Revamp",
    },
    # Add more releases here as they get set up in Redmine:
    # {"portfolio_id":"abhyas-R3","redmine_project":"abhyas-dev","redmine_version_id":??,...},
    # {"portfolio_id":"rms-R1","redmine_project":"formula-rms","redmine_version_id":??,...},
]

# ─── Status → % weight for Scope computation ──────────────────────
# Adjust these if the interpretation feels off. Done = prod-ready per PM.
STATUS_WEIGHT = {
    "Done":        1.00,
    "QA":          0.75,
    "In Progress": 0.20,
    "Reopen":      0.30,
    "Re-Open":     0.30,
    "Hold":        0.00,
    "To Do":       0.00,
    "Todo":        0.00,
    "Backlogs":    0.00,
    "Backlog":     0.00,
    "New":         0.00,
}

# Statuses considered "development-complete" for a coarse Dev% metric
DEV_DONE_STATUSES = {"QA", "Done"}
QA_DONE_STATUSES  = {"Done"}

TRACKER_EPIC = "Epic"

# ─── HTTP helper ──────────────────────────────────────────────────
def redmine_get(path, **params):
    """GET request against Redmine API. Handles pagination."""
    params = {k: v for k, v in params.items() if v is not None}
    all_items = []
    offset = 0
    limit = 100
    while True:
        q = dict(params)
        q["limit"] = limit
        q["offset"] = offset
        url = f"{REDMINE_BASE}{path}?" + urllib.parse.urlencode(q, doseq=True)
        req = urllib.request.Request(url, headers={
            "X-Redmine-API-Key": API_KEY,
            "Accept": "application/json",
            "User-Agent": "bottle-portfolio-sync/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code} for {url}: {e.read().decode('utf-8', errors='replace')[:400]}", file=sys.stderr)
            raise
        # Find the list key ('issues','versions', etc.)
        list_key = None
        for k, v in data.items():
            if isinstance(v, list):
                list_key = k
                break
        if list_key is None:
            return data
        all_items.extend(data[list_key])
        total = data.get("total_count", len(data[list_key]))
        offset += limit
        if offset >= total:
            break
        time.sleep(0.15)  # Be nice to the server
    return {list_key: all_items, "total_count": len(all_items)}

# ─── Fetch + compute one release ──────────────────────────────────
def fetch_release(spec):
    print(f"\n[{spec['portfolio_id']}] Fetching Redmine data for '{spec['release_label']}'...")

    # 1. Version metadata (name, due_date, status)
    ver_url = f"/versions/{spec['redmine_version_id']}.json"
    req = urllib.request.Request(f"{REDMINE_BASE}{ver_url}",
        headers={
            "X-Redmine-API-Key": API_KEY,
            "Accept": "application/json",
            "User-Agent": "bottle-portfolio-sync/1.0",
        })
    with urllib.request.urlopen(req, timeout=30) as resp:
        version = json.loads(resp.read().decode("utf-8"))["version"]

    # 2. All issues in this version
    issues_data = redmine_get("/issues.json",
        project_id=spec["redmine_project"],
        fixed_version_id=spec["redmine_version_id"],
        status_id="*",
    )
    issues = issues_data["issues"]
    print(f"  Fetched {len(issues)} issues")

    # 3. Split Epics vs Stories/other
    epics = [i for i in issues if i.get("tracker", {}).get("name") == TRACKER_EPIC]
    non_epics = [i for i in issues if i.get("tracker", {}).get("name") != TRACKER_EPIC]
    print(f"  {len(epics)} Epics, {len(non_epics)} Stories/other")

    # 4. Build epic → children map
    epic_by_id = {e["id"]: e for e in epics}
    children_by_epic = {e["id"]: [] for e in epics}
    orphans = []  # Non-epic issues with no epic parent
    for i in non_epics:
        parent = i.get("parent") or {}
        pid = parent.get("id")
        if pid and pid in epic_by_id:
            children_by_epic[pid].append(i)
        else:
            orphans.append(i)

    # 5. Compute per-Epic breakdown
    epic_summaries = []
    for e in epics:
        children = children_by_epic[e["id"]]
        status_counts = {}
        for c in children:
            s = c.get("status", {}).get("name", "Unknown")
            status_counts[s] = status_counts.get(s, 0) + 1
        total = len(children)
        # Weighted % done
        done_weight = sum(STATUS_WEIGHT.get(c.get("status", {}).get("name"), 0) for c in children)
        pct = round((done_weight / total) * 100) if total else 0
        # Stories only for size
        stories = [c for c in children if c.get("tracker", {}).get("name") == "Story"]
        epic_summaries.append({
            "id": e["id"],
            "subject": e["subject"],
            "status": e.get("status", {}).get("name"),
            "children_count": total,
            "stories_count": len(stories),
            "status_counts": status_counts,
            "weighted_pct": pct,
        })

    # 6. Overall release rollup
    total_issues = len(non_epics)  # count Stories + non-Epic work items, not Epics themselves
    story_count = len([i for i in non_epics if i.get("tracker", {}).get("name") == "Story"])
    all_status_counts = {}
    for i in non_epics:
        s = i.get("status", {}).get("name", "Unknown")
        all_status_counts[s] = all_status_counts.get(s, 0) + 1
    scope_pct = round(
        sum(STATUS_WEIGHT.get(i.get("status", {}).get("name"), 0) for i in non_epics) / total_issues * 100
    ) if total_issues else 0
    dev_pct = round(
        len([i for i in non_epics if i.get("status", {}).get("name") in DEV_DONE_STATUSES]) / total_issues * 100
    ) if total_issues else 0
    qa_pct = round(
        len([i for i in non_epics if i.get("status", {}).get("name") in QA_DONE_STATUSES]) / total_issues * 100
    ) if total_issues else 0

    # 7. Flat issue list (for the drill-down table)
    flat_issues = []
    for i in non_epics:
        parent = i.get("parent") or {}
        flat_issues.append({
            "id": i["id"],
            "subject": i["subject"],
            "tracker": i.get("tracker", {}).get("name"),
            "status": i.get("status", {}).get("name"),
            "assignee": (i.get("assigned_to") or {}).get("name"),
            "epic_id": parent.get("id") if parent.get("id") in epic_by_id else None,
            "epic_subject": epic_by_id[parent["id"]]["subject"] if parent.get("id") in epic_by_id else None,
            "created_on": i.get("created_on"),
            "updated_on": i.get("updated_on"),
            "done_ratio": i.get("done_ratio"),
            "url": f"{REDMINE_BASE}/issues/{i['id']}",
        })

    return {
        "portfolio_id": spec["portfolio_id"],
        "release_label": spec["release_label"],
        "redmine_version_id": spec["redmine_version_id"],
        "redmine_project": spec["redmine_project"],
        "redmine_url": f"{REDMINE_BASE}/versions/{spec['redmine_version_id']}",
        "version_status": version.get("status"),
        "due_date": version.get("due_date"),
        "created_on": version.get("created_on"),
        "updated_on": version.get("updated_on"),
        "total_issues": total_issues,
        "story_count": story_count,
        "epic_count": len(epics),
        "orphan_count": len(orphans),
        "status_counts": all_status_counts,
        "scope_pct": scope_pct,
        "dev_pct": dev_pct,
        "qa_pct": qa_pct,
        "epics": epic_summaries,
        "issues": flat_issues,
    }

# ─── Main ─────────────────────────────────────────────────────────
def main():
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "redmine_base": REDMINE_BASE,
        "status_weights": STATUS_WEIGHT,
        "releases": {},
    }
    for spec in RELEASES_TO_SYNC:
        try:
            data = fetch_release(spec)
            output["releases"][spec["portfolio_id"]] = data
            print(f"  ✓ {spec['portfolio_id']}: {data['total_issues']} issues, scope {data['scope_pct']}%")
        except Exception as e:
            print(f"  ✗ {spec['portfolio_id']} FAILED: {e}", file=sys.stderr)
            # Don't fail the whole run for one release
            output["releases"][spec["portfolio_id"]] = {
                "error": str(e),
                "portfolio_id": spec["portfolio_id"],
                "release_label": spec["release_label"],
            }

    # Write output
    os.makedirs("data", exist_ok=True)
    out_path = "data/redmine.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, sort_keys=False)
    print(f"\n✓ Wrote {out_path} ({os.path.getsize(out_path)} bytes)")

if __name__ == "__main__":
    main()

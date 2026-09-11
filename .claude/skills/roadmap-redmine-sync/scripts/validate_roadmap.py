#!/usr/bin/env python3
"""
Validate index.html after editing RELEASES / REDMINE_SNAPSHOT / PRODUCTS.

Usage:
    python3 validate_roadmap.py /path/to/index.html

Does two things:
1. Extracts all <script> blocks and runs `node --check` on them (catches
   syntax errors from bad string replacements before they reach the user).
2. Runs a sandboxed eval of the JS to sanity-check the data itself:
   - no duplicate release IDs
   - every release's scope[] weights sum to 100
   - no corrupted status strings (e.g. 'qain-dev', 'backlogbacklog' — a
     symptom of overlapping regex replacements eating adjacent fields)
   - every scope feature has tShirt/ac/redmineEpicId if the release is
     redmineSync'd
   - computeScopePct(release) matches release.liveData.scope_pct when
     liveData is present (confirms the "live" numbers are actually live)

Exits non-zero and prints a clear reason on any failure. Run this BEFORE
copying the file to outputs — do not present a file that fails this check.
"""
import re
import subprocess
import sys
import tempfile
import os

VALID_STATUSES = {
    'backlog', 'ready', 'in-dev', 'code-complete',
    'qa', 'uat', 'ready-release', 'released', 'blocked'
}

SANDBOX_PRELUDE = """
global.document = {
  getElementById: () => ({ innerHTML: '', addEventListener:()=>{} }),
  addEventListener: ()=>{},
  querySelectorAll: () => [],
  querySelector: () => null,
  createElement: () => ({ style:{}, addEventListener:()=>{}, appendChild:()=>{}, setAttribute:()=>{} }),
  body: { appendChild:()=>{} },
};
global.window = global;
global.localStorage = { getItem:()=>null, setItem:()=>{} };
"""

SANDBOX_CHECKS = """
const report = { errors: [], warnings: [] };

// 1. Duplicate release IDs
const ids = RELEASES.map(r => r.id);
const dupes = ids.filter((id,i,arr) => arr.indexOf(id) !== i);
if (dupes.length) report.errors.push('Duplicate release IDs: ' + dupes.join(', '));

RELEASES.forEach(r => {
  if (!r.scope || !r.scope.length) return;

  // 2. Weights sum to 100
  const wsum = r.scope.reduce((s,f) => s + (f.weight||0), 0);
  if (wsum !== 100) report.warnings.push(`${r.id}: scope weights sum to ${wsum}, not 100`);

  // 3. Corrupted status strings
  r.scope.forEach(f => {
    if (!VALID_STATUSES_JS.includes(f.status)) {
      report.errors.push(`${r.id}/${f.id}: invalid/corrupted status '${f.status}'`);
    }
  });

  // 4. Required fields present when redmineSync
  if (r.redmineSync) {
    r.scope.forEach(f => {
      if (!f.tShirt || !f.ac || !f.redmineEpicId) {
        report.errors.push(`${r.id}/${f.id}: missing tShirt/ac/redmineEpicId (possible corruption)`);
      }
    });
  }

  // 5. computeScopePct matches liveData when present
  if (r.liveData && typeof r.liveData.scope_pct === 'number') {
    const computed = computeScopePct(r);
    if (computed !== r.liveData.scope_pct) {
      report.errors.push(`${r.id}: computeScopePct()=${computed} but liveData.scope_pct=${r.liveData.scope_pct} (live wiring broken?)`);
    }
  }
});

console.log(JSON.stringify(report));
"""


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 validate_roadmap.py /path/to/index.html", file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1]
    with open(path) as f:
        content = f.read()

    scripts = re.findall(r"<script>([\s\S]*?)</script>", content)
    if not scripts:
        print("ERROR: no <script> blocks found — is this the right file?", file=sys.stderr)
        sys.exit(1)

    combined = "\n".join(scripts)

    with tempfile.TemporaryDirectory() as tmp:
        js_path = os.path.join(tmp, "extracted.js")
        with open(js_path, "w") as f:
            f.write(combined)

        # Step 1: syntax check
        r = subprocess.run(["node", "--check", js_path], capture_output=True, text=True)
        if r.returncode != 0:
            print("SYNTAX ERROR — do not ship this file:\n", file=sys.stderr)
            print(r.stderr, file=sys.stderr)
            sys.exit(1)
        print("✓ JS syntax OK")

        # Step 2: sandboxed sanity checks
        valid_statuses_js = "[" + ",".join(f"'{s}'" for s in VALID_STATUSES) + "]"
        wrapped = (
            SANDBOX_PRELUDE
            + f"const VALID_STATUSES_JS = {valid_statuses_js};\n"
            + combined
            + SANDBOX_CHECKS
        )
        wrapped_path = os.path.join(tmp, "check.js")
        with open(wrapped_path, "w") as f:
            f.write(wrapped)

        r = subprocess.run(["node", wrapped_path], capture_output=True, text=True)
        if r.returncode != 0:
            print("RUNTIME ERROR during sanity check:\n", file=sys.stderr)
            print(r.stderr, file=sys.stderr)
            sys.exit(1)

        try:
            import json
            report = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            print("Could not parse sanity-check output:\n" + r.stdout, file=sys.stderr)
            sys.exit(1)

        if report["warnings"]:
            print("⚠ Warnings:")
            for w in report["warnings"]:
                print("  -", w)

        if report["errors"]:
            print("\n✗ ERRORS — do not ship this file:")
            for e in report["errors"]:
                print("  -", e)
            sys.exit(1)

        print("✓ Data sanity checks passed (no duplicate IDs, no corrupted statuses, live % matches)")


if __name__ == "__main__":
    main()

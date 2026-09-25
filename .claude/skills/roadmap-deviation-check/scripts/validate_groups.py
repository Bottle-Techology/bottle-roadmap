#!/usr/bin/env python3
"""
Validate index.html after editing GROUPS (the Gantt) for a deviation check-in.

Usage:
    python3 validate_groups.py /path/to/index.html

Does two things:
1. Extracts all <script> blocks and runs `node --check` on them (catches
   syntax errors from a bad edit before they reach the user).
2. Runs a sandboxed eval of the JS to sanity-check GROUPS/row structure:
   - every row's ms[] entries have d/label/color and d parses as YYYY-MM-DD
   - every row's planned[] and tracks[] bars have s/e that parse as YYYY-MM-DD
   - a row with pivotReason set but an empty/missing planned[] (a deviation
     was described but the original bar was never preserved for contrast)
   - a row with a non-empty planned[] but no pivotReason (a plan/actual split
     exists but there's no explanation of why)
   - counts how many red diamonds (color === C.red, '#E24B4A') exist, so you
     can confirm the ones you just added actually landed

Exits non-zero and prints a clear reason on any failure. Run this BEFORE
telling the user the deviation has been recorded.
"""
import re
import subprocess
import sys
import tempfile
import os
import json

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
const report = { errors: [], warnings: [], redDiamonds: 0 };
const DATE_RE = /^\\d{4}-\\d{2}-\\d{2}$/;

function checkDate(d, where) {
  if (!d || !DATE_RE.test(d)) {
    report.errors.push(`${where}: bad or missing date '${d}'`);
  }
}

const groupIds = GROUPS.map(g => g.id);
const dupeGroups = groupIds.filter((id,i,arr) => arr.indexOf(id) !== i);
if (dupeGroups.length) report.errors.push('Duplicate GROUPS ids: ' + dupeGroups.join(', '));

GROUPS.forEach(grp => {
  (grp.rows || []).forEach(row => {
    const rowTag = `${grp.id} / "${row.title}"`;

    (row.ms || []).forEach(ms => {
      checkDate(ms.d, `${rowTag} ms "${ms.label}"`);
      if (!ms.label) report.errors.push(`${rowTag}: a milestone is missing a label`);
      if (!ms.color) report.errors.push(`${rowTag} ms "${ms.label}": missing color`);
      if (ms.color === (typeof C !== 'undefined' ? C.red : '#E24B4A') || ms.color === '#E24B4A') {
        report.redDiamonds++;
      }
    });

    (row.tracks || []).forEach(track => {
      track.forEach(bar => {
        checkDate(bar.s, `${rowTag} bar "${bar.label}" start`);
        checkDate(bar.e, `${rowTag} bar "${bar.label}" end`);
      });
    });

    const plannedLen = (row.planned || []).reduce((n, t) => n + t.length, 0);
    (row.planned || []).forEach(track => {
      track.forEach(bar => {
        checkDate(bar.s, `${rowTag} planned bar "${bar.label}" start`);
        checkDate(bar.e, `${rowTag} planned bar "${bar.label}" end`);
      });
    });

    if (row.pivotReason && plannedLen === 0) {
      report.warnings.push(`${rowTag}: has pivotReason but no planned[] bars — original plan not preserved for contrast`);
    }
    if (!row.pivotReason && plannedLen > 0) {
      report.warnings.push(`${rowTag}: has planned[] bars but no pivotReason — deviation not explained`);
    }
  });
});

console.log(JSON.stringify(report));
"""


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 validate_groups.py /path/to/index.html", file=sys.stderr)
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

        r = subprocess.run(["node", "--check", js_path], capture_output=True, text=True)
        if r.returncode != 0:
            print("SYNTAX ERROR — do not ship this file:\n", file=sys.stderr)
            print(r.stderr, file=sys.stderr)
            sys.exit(1)
        print("✓ JS syntax OK")

        wrapped = SANDBOX_PRELUDE + combined + SANDBOX_CHECKS
        wrapped_path = os.path.join(tmp, "check.js")
        with open(wrapped_path, "w") as f:
            f.write(wrapped)

        r = subprocess.run(["node", wrapped_path], capture_output=True, text=True)
        if r.returncode != 0:
            print("RUNTIME ERROR during sanity check:\n", file=sys.stderr)
            print(r.stderr, file=sys.stderr)
            sys.exit(1)

        try:
            report = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            print("Could not parse sanity-check output:\n" + r.stdout, file=sys.stderr)
            sys.exit(1)

        if report["warnings"]:
            print("⚠ Warnings:")
            for w in report["warnings"]:
                print("  -", w)

        print(f"ℹ {report['redDiamonds']} red deviation diamond(s) found in GROUPS")

        if report["errors"]:
            print("\n✗ ERRORS — do not ship this file:")
            for e in report["errors"]:
                print("  -", e)
            sys.exit(1)

        print("✓ GROUPS sanity checks passed (dates parse, ms well-formed, plan/pivot pairing consistent)")


if __name__ == "__main__":
    main()

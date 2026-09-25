#!/usr/bin/env python3
"""
List every Gantt "capsule" (a tracks[] bar or an ms[] milestone diamond) in
index.html whose date falls inside a review window. Used to build the
project-by-project review list for a roadmap-deviation-check.

Usage:
    python3 list_capsules.py /path/to/index.html 2026-08-25 2026-09-25
"""
import re
import subprocess
import sys
import tempfile
import os
import json

SANDBOX_PRELUDE = """
global.document = {
  getElementById: () => ({ innerHTML: '', addEventListener:()=>{}, style:{} }),
  addEventListener: ()=>{},
  querySelectorAll: () => [],
  querySelector: () => null,
  createElement: () => ({ style:{}, addEventListener:()=>{}, appendChild:()=>{}, setAttribute:()=>{} }),
  body: { appendChild:()=>{} },
};
global.window = global;
global.localStorage = { getItem:()=>null, setItem:()=>{} };
"""

QUERY_TMPL = """
const start = %s, end = %s;
const inWindow = (d) => d >= start && d <= end;
const out = [];
GROUPS.forEach(g => {
  g.rows.forEach(row => {
    (row.tracks||[]).flat().forEach(b => {
      if (inWindow(b.s) || inWindow(b.e) || (b.s <= start && b.e >= end)) {
        out.push({group: g.label, row: row.title, kind: 'BAR', label: b.label, s: b.s, e: b.e, st: b.st||null});
      }
    });
    (row.ms||[]).forEach(m => {
      if (inWindow(m.d)) out.push({group: g.label, row: row.title, kind: 'MS', label: m.label, d: m.d, color: m.color});
    });
  });
});
console.log(JSON.stringify(out, null, 2));
"""


def main():
    if len(sys.argv) != 4:
        print("Usage: python3 list_capsules.py /path/to/index.html <start:YYYY-MM-DD> <end:YYYY-MM-DD>", file=sys.stderr)
        sys.exit(2)

    path, start, end = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(path) as f:
        content = f.read()

    scripts = re.findall(r"<script>([\s\S]*?)</script>", content)
    if not scripts:
        print("ERROR: no <script> blocks found — is this the right file?", file=sys.stderr)
        sys.exit(1)
    combined = "\n".join(scripts)

    query = QUERY_TMPL % (json.dumps(start), json.dumps(end))
    wrapped = SANDBOX_PRELUDE + combined + query

    with tempfile.TemporaryDirectory() as tmp:
        js_path = os.path.join(tmp, "list_capsules.js")
        with open(js_path, "w") as f:
            f.write(wrapped)
        r = subprocess.run(["node", js_path], capture_output=True, text=True)
        if r.returncode != 0:
            print("RUNTIME ERROR:\n", file=sys.stderr)
            print(r.stderr, file=sys.stderr)
            sys.exit(1)
        print(r.stdout)


if __name__ == "__main__":
    main()

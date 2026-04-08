#!/usr/bin/env python3
"""Check that all viewer documents resolve to real files or valid URLs."""
import json
import os
import sys

DOCS_PATH = os.path.join(os.path.dirname(__file__), "../viewer/documents.json")
BASE = os.path.join(os.path.dirname(__file__), "..")

def main():
    m = json.load(open(DOCS_PATH))
    errors = []
    for f in m:
        p = f["path"]
        if p.startswith("http"):
            continue  # skip external URLs
        resolved = p.replace("/viewer/..", BASE)
        if not os.path.exists(resolved):
            errors.append(p)
    if errors:
        print("FAIL:", errors)
        sys.exit(1)
    print("OK: all", len(m), "entries resolve")
    sys.exit(0)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate the published debrief site's integrity. Exit non-zero on any problem.

Run in CI on every push (and locally before publishing). Catches exactly the
class of defects that used to ship when the manifest was hand-edited by an LLM:
404 entries, orphaned debriefs, duplicates, drifted card counts, non-canonical
filenames, and out-of-order entries.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEBRIEFS = REPO / "debriefs"
MANIFEST = REPO / "manifest.json"

NAME_RE = re.compile(r"^debriefs/debrief-(\d{4})-(\d{2})-(\d{2})-(\d{2})\.(html|md)$")
ARXIV_CARD_RE = re.compile(r'class="card"')
WEB_CARD_RE = re.compile(r'class="card web-card"')

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def main() -> int:
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"FAIL: manifest.json is not valid JSON: {e}")
        return 1
    if not isinstance(manifest, list):
        print("FAIL: manifest.json is not a list")
        return 1

    seen_html: set[str] = set()
    last_key = None
    for i, e in enumerate(manifest):
        html = e.get("html", "")
        md = e.get("md", "")
        if not NAME_RE.match(html):
            err(f"entry {i}: non-canonical html path {html!r}")
            continue
        if md and not NAME_RE.match(md):
            err(f"entry {i}: non-canonical md path {md!r}")
        if not (REPO / html).exists():
            err(f"entry {i}: html file missing on disk: {html}")
        if md and not (REPO / md).exists():
            err(f"entry {i}: md file missing on disk: {md}")
        if html in seen_html:
            err(f"entry {i}: duplicate html entry {html}")
        seen_html.add(html)
        if not isinstance(e.get("papers"), int) or not isinstance(e.get("findings"), int):
            err(f"entry {i}: papers/findings must be integers")
        else:
            # counts must match the actual rendered cards
            try:
                page = (REPO / html).read_text(encoding="utf-8", errors="replace")
                web = len(WEB_CARD_RE.findall(page))
                arxiv = len(ARXIV_CARD_RE.findall(page))
                if e["papers"] != arxiv or e["findings"] != web:
                    err(f"entry {i} ({html}): counts {e['papers']}/{e['findings']} "
                        f"!= rendered {arxiv}/{web}")
            except OSError:
                pass
        key = NAME_RE.match(html).groups()[:4]
        if last_key is not None and key > last_key:
            err(f"entry {i}: not sorted newest-first ({html})")
        last_key = key

    # every debrief html on disk must have a manifest entry
    for p in sorted(DEBRIEFS.glob("debrief-*.html")):
        rel = f"debriefs/{p.name}"
        if not NAME_RE.match(rel):
            err(f"non-canonical filename on disk: {p.name}")
        elif rel not in seen_html:
            err(f"debrief on disk has no manifest entry: {rel}")

    if errors:
        print(f"FAIL: {len(errors)} integrity problem(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: {len(manifest)} entries, all files present, counts correct, sorted, no orphans.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

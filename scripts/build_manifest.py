#!/usr/bin/env python3
"""Deterministically rebuild manifest.json from the debrief files on disk.

The manifest is the dashboard's index. Historically it was hand-edited by the
LLM debrief job, which produced drift: 404 entries pointing at filenames that
don't exist, orphaned debriefs with no entry, duplicate entries, eyeballed card
counts, and inconsistent date formats. This script makes the files on disk the
single source of truth:

  - globs debriefs/debrief-YYYY-MM-DD-HH.html
  - derives the date and slug from the filename (never invented)
  - counts the ACTUAL rendered cards (arxiv = `class="card"`, web =
    `class="card web-card"`) instead of trusting a written-in number
  - emits one entry per html file, newest first

Run it after generating a new debrief, or any time to repair drift. It is
idempotent: same files in -> same manifest out.

Usage:
  python3 scripts/build_manifest.py            # rewrite manifest.json
  python3 scripts/build_manifest.py --check     # exit 1 if manifest is stale/invalid, write nothing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEBRIEFS = REPO / "debriefs"
MANIFEST = REPO / "manifest.json"

NAME_RE = re.compile(r"^debrief-(\d{4})-(\d{2})-(\d{2})-(\d{2})\.html$")
ARXIV_CARD_RE = re.compile(r'class="card"')
WEB_CARD_RE = re.compile(r'class="card web-card"')


def count_cards(html: str) -> tuple[int, int]:
    """Return (arxiv_cards, web_cards) by counting the rendered card divs."""
    web = len(WEB_CARD_RE.findall(html))
    arxiv = len(ARXIV_CARD_RE.findall(html))  # web cards are `card web-card`, not `card"`
    return arxiv, web


def build() -> list[dict]:
    entries = []
    bad = []
    for html_path in sorted(DEBRIEFS.glob("debrief-*.html")):
        m = NAME_RE.match(html_path.name)
        if not m:
            bad.append(html_path.name)
            continue
        y, mo, d, h = m.groups()
        slug = html_path.stem  # debrief-YYYY-MM-DD-HH
        try:
            arxiv, web = count_cards(html_path.read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            print(f"[warn] cannot read {html_path.name}: {e}", file=sys.stderr)
            continue
        md_path = html_path.with_suffix(".md")
        entries.append(
            {
                "date": f"{y}-{mo}-{d} {h}:00",
                "_sortkey": f"{y}-{mo}-{d}-{h}",
                "html": f"debriefs/{html_path.name}",
                "md": f"debriefs/{md_path.name}" if md_path.exists() else "",
                "papers": arxiv,
                "findings": web,
            }
        )
    if bad:
        print(f"[warn] {len(bad)} non-canonical filename(s) skipped: {bad}", file=sys.stderr)
    # newest first
    entries.sort(key=lambda e: e["_sortkey"], reverse=True)
    for e in entries:
        del e["_sortkey"]
    return entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate only; exit 1 if stale")
    args = ap.parse_args()

    entries = build()
    new_text = json.dumps(entries, indent=2, ensure_ascii=False) + "\n"

    if args.check:
        old = MANIFEST.read_text(encoding="utf-8") if MANIFEST.exists() else ""
        if old.strip() == new_text.strip():
            print(f"manifest OK: {len(entries)} entries, in sync with disk")
            return 0
        print("manifest STALE: does not match debrief files on disk", file=sys.stderr)
        return 1

    MANIFEST.write_text(new_text, encoding="utf-8")
    print(f"manifest.json rebuilt: {len(entries)} entries (newest: {entries[0]['date'] if entries else 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

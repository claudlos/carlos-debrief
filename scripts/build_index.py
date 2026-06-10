#!/usr/bin/env python3
"""Build index.json — a compact per-card index of recent debriefs.

This is the shared data layer for the search (#16), topic-browse (#19), and
insights/trends (#09) pages. It parses each debrief's cards (title, link,
web-vs-arxiv, topic group, short description) straight from the rendered HTML,
which is consistent across the whole archive. Capped to the most recent
MAX_DEBRIEFS to bound file size; tune freely.

Output shape (compact, nested by debrief):
  [{"d": "2026-06-09 19:00", "p": "debriefs/debrief-2026-06-09-19.html",
    "items": [{"t": title, "l": link, "w": 0|1, "g": topic, "s": short_desc}, ...]}]

Usage:
  python3 scripts/build_index.py            # write index.json
  python3 scripts/build_index.py --check     # exit 1 if stale
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEBRIEFS = REPO / "debriefs"
INDEX = REPO / "index.json"

MAX_DEBRIEFS = 60          # recent window for the index
MAX_CARDS_PER = 150        # guard against the giant LLM-era debriefs
DESC_LEN = 160

NAME_RE = re.compile(r"^debrief-(\d{4})-(\d{2})-(\d{2})-(\d{2})\.html$")
H3_RE = re.compile(r"<h3>(.*?)</h3>", re.S)
CARD_RE = re.compile(
    r'<div class="card( web-card)?"\s+data-full-desc="([^"]*)"[^>]*>\s*'
    r'<div class="card-title">\s*<a href="([^"]*)"[^>]*>(.*?)</a>',
    re.S,
)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean(s: str) -> str:
    s = TAG_RE.sub("", s)
    s = htmlmod.unescape(s)
    return WS_RE.sub(" ", s).strip()


def topic_label(h3_inner: str) -> str:
    # drop the <span class="group-count">N</span> then strip leading emoji/symbols
    txt = re.sub(r'<span class="group-count">.*?</span>', "", h3_inner)
    txt = clean(txt)
    return re.sub(r"^[^A-Za-z0-9]+", "", txt).strip()


def parse_debrief(html: str) -> list[dict]:
    h3s = [(m.start(), topic_label(m.group(1))) for m in H3_RE.finditer(html)]
    items = []
    for m in CARD_RE.finditer(html):
        is_web = 1 if m.group(1) else 0
        desc = clean(m.group(2))[:DESC_LEN]
        link = htmlmod.unescape(m.group(3))
        title = clean(m.group(4))
        if not title:
            continue
        # nearest preceding <h3> = this card's group
        group = ""
        for pos, label in h3s:
            if pos < m.start():
                group = label
            else:
                break
        if not group:
            group = "Web Findings" if is_web else "ArXiv Papers"
        items.append({"t": title, "l": link, "w": is_web, "g": group, "s": desc})
        if len(items) >= MAX_CARDS_PER:
            break
    return items


def build() -> list[dict]:
    files = sorted(DEBRIEFS.glob("debrief-*.html"), reverse=True)
    out = []
    for f in files:
        m = NAME_RE.match(f.name)
        if not m:
            continue
        if len(out) >= MAX_DEBRIEFS:
            break
        y, mo, d, h = m.groups()
        try:
            items = parse_debrief(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if items:
            out.append({"d": f"{y}-{mo}-{d} {h}:00", "p": f"debriefs/{f.name}", "items": items})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    data = build()
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    if args.check:
        old = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""
        if old.strip() == text.strip():
            print(f"index.json OK: {len(data)} debriefs")
            return 0
        print("index.json STALE", file=sys.stderr)
        return 1
    INDEX.write_text(text, encoding="utf-8")
    cards = sum(len(d["items"]) for d in data)
    print(f"index.json written: {len(data)} debriefs, {cards} cards, {len(text)//1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

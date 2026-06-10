#!/usr/bin/env python3
"""Deterministically build an RSS 2.0 feed (feed.xml) from manifest.json.

Mirrors build_manifest.py: the files on disk are the source of truth, the feed
is regenerated (never hand-edited), and `--check` lets CI fail if feed.xml has
drifted. Untrusted manifest fields are XML-escaped and only canonical debrief
paths are emitted as links.

Usage:
  python3 scripts/build_feed.py            # (re)write feed.xml
  python3 scripts/build_feed.py --check    # exit 1 if feed.xml is stale
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover - zoneinfo always present on 3.9+
    TZ = None

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "manifest.json"
FEED = REPO / "feed.xml"

SITE = "https://claudlos.github.io/carlos-debrief/"
TITLE = "Carlos's Debrief"
DESC = "Auto-generated research digests from arXiv, Google Scholar, Lobste.rs, Hacker News, and HuggingFace."
MAX_ITEMS = 50  # cap feed size; readers rarely need the full history

HTML_RE = re.compile(r"^debriefs/debrief-(\d{4})-(\d{2})-(\d{2})-(\d{2})\.html$")


def rfc822(date_str: str, m: re.Match) -> str | None:
    """Parse a manifest date into an RFC-822 pubDate, tz-aware (America/Chicago)."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        try:  # fall back to deriving from the filename slug
            y, mo, d, h = (int(x) for x in m.groups())
            dt = datetime(y, mo, d, h, 0)
        except Exception:
            return None
    if TZ is not None:
        dt = dt.replace(tzinfo=TZ)
    return format_datetime(dt)


def render() -> str:
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"build_feed: cannot read manifest.json: {e}", file=sys.stderr)
        raise

    items = []
    for e in (manifest if isinstance(manifest, list) else [])[:MAX_ITEMS]:
        html = e.get("html", "")
        m = HTML_RE.match(html)
        if not m:
            continue  # never emit a non-canonical (possibly attacker-shaped) link
        url = SITE + html
        date = str(e.get("date", ""))
        papers, findings = e.get("papers"), e.get("findings")
        desc = f"{papers} papers · {findings} web findings"
        pub = rfc822(date, m)
        parts = [
            "    <item>",
            f"      <title>{escape(date)}</title>",
            f"      <link>{escape(url)}</link>",
            f'      <guid isPermaLink="true">{escape(url)}</guid>',
            f"      <description>{escape(desc)}</description>",
        ]
        if pub:
            parts.append(f"      <pubDate>{escape(pub)}</pubDate>")
        parts.append("    </item>")
        items.append("\n".join(parts))

    last_build = items and None
    newest_pub = None
    if isinstance(manifest, list) and manifest:
        m0 = HTML_RE.match(manifest[0].get("html", ""))
        if m0:
            newest_pub = rfc822(str(manifest[0].get("date", "")), m0)

    head = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        f"    <title>{escape(TITLE)}</title>",
        f"    <link>{escape(SITE)}</link>",
        f"    <description>{escape(DESC)}</description>",
        "    <language>en-us</language>",
        f'    <atom:link href={quoteattr(SITE + "feed.xml")} rel="self" type="application/rss+xml" />',
    ]
    if newest_pub:
        head.append(f"    <lastBuildDate>{escape(newest_pub)}</lastBuildDate>")
    body = "\n".join(items)
    tail = ["  </channel>", "</rss>", ""]
    return "\n".join(head + ([body] if body else []) + tail)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    xml = render()
    if args.check:
        old = FEED.read_text(encoding="utf-8") if FEED.exists() else ""
        if old.strip() == xml.strip():
            print("feed.xml OK: in sync with manifest")
            return 0
        print("feed.xml STALE: does not match manifest", file=sys.stderr)
        return 1
    FEED.write_text(xml, encoding="utf-8")
    n = xml.count("<item>")
    print(f"feed.xml written: {n} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Build curated topic pages + feed pages from index.json.

Reads the same `index.json` that build_index.py produces, then renders a set
of static HTML pages under /topics/ and /feed/:

  /topics/security.html       — security + hacking + bug-bounty + CVE + malware
  /topics/hacking.html        — pen-testing + red-team + vuln-research
  /topics/coding.html         — compilers, type systems, formal verification, program repair
  /topics/oss.html            — open-source ecosystem (FOSS, licensing)
  /topics/decentralized.html  — P2P, gossip, distributed systems
  /topics/networking.html     — TCP/QUIC/BGP/SDN/wireguard
  /topics/quantum.html        — quantum computing + zero-point energy
  /topics/education.html      — ed-tech, MOOC, adaptive learning
  /topics/ai-safety.html      — alignment + guardrails + moderation + jailbreak
  /research-feed.html         — all "paper" type items, time-sorted
  /news-feed.html             — all "news" type items, time-sorted

Topic matching is by keyword overlap with each item's `g` (group label)
plus the raw text. Cheap, no LLM — runs on every cron tick.

Usage:
  python3 scripts/build_topic_pages.py
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "index.json"


# Topic pages — label → keyword sets that match an item's group or text
TOPICS: list[tuple[str, str, list[str], list[str]]] = [
    # (slug,        title,                 include_groups,                     include_text_keywords)
    ("security", "Security & Cybersecurity", [], [
        "security", "cybersecurity", "cryptography", "cryptographic", "vulnerability",
        "vulnerabilities", "exploit", "exploits", "CVE", "fuzzing", "malware",
        "supply chain", "sbom", "zero-day", "0day",
    ]),
    ("hacking", "Hacking, Pen Testing & Red Team", [], [
        "penetration testing", "pentest", "red team", "red-team", "offensive security",
        "exploit", "vulnerability research", "bug bounty", "responsible disclosure",
        "ctf", "capture the flag",
    ]),
    ("ai-safety", "AI Safety, Guardrails & Moderation", [], [
        "alignment", "AI safety", "guardrails", "content moderation", "moderation",
        "jailbreak", "red teaming", "red-teaming", "harm classification",
        "policy compliance",
    ]),
    ("coding", "Coding, Compilers & SE", [], [
        "program analysis", "static analysis", "formal verification", "compiler",
        "compilers", "type system", "type systems", "program repair", "static analysis",
        "software engineering", "formal methods", "verification", "proof assistant",
    ]),
    ("oss", "Open-Source Ecosystem", [], [
        "open source", "open-source", "FOSS", "OSS", "copyleft", "GPL", "MIT license",
        "permissive license", "software license", "software licensing",
    ]),
    ("decentralized", "Decentralized Networks & P2P", [], [
        "decentralized", "peer-to-peer", "P2P", "distributed systems",
        "gossip protocol", "libp2p", "consensus", "byzantine",
    ]),
    ("networking", "Networking & Protocols", [], [
        "TCP", "QUIC", "BGP", "SDN", "wireguard", "network protocol", "routing",
        "packet", "mesh network", "firewall", "DNS",
    ]),
    ("quantum", "Quantum Computing & Zero-Point Energy", [], [
        "quantum computing", "quantum algorithm", "qubit", "topological qubit",
        "quantum error correction", "quantum vacuum", "casimir", "zero-point energy",
        "vacuum fluctuation", "ground state energy",
    ]),
    ("education", "Educational Systems", [], [
        "education", "MOOC", "e-learning", "adaptive learning", "educational technology",
        "pedagogy", "tutoring", "intelligent tutoring", "learning analytics",
    ]),
]


def item_matches(item: dict, include_groups: list[str], include_text: list[str]) -> bool:
    if item.get("g") in include_groups:
        return True
    haystack = " ".join([
        item.get("t", ""), item.get("s", ""),
        " ".join(item.get("tags", []) or []),
    ]).lower()
    return any(kw.lower() in haystack for kw in include_text)


def normalize_ts(item: dict) -> str:
    """ISO timestamp for an item, used for time-sorting."""
    # items are nested by debrief — pull from outer debrief_date via index
    return item.get("_d", "")


def collect_items(index: list[dict], predicate) -> list[dict]:
    """Flatten + filter index entries. Each item gets `_d` (debrief date) attached."""
    flat = []
    for entry in index:
        for item in entry.get("items", []):
            decorated = dict(item)
            decorated["_d"] = entry.get("d", "")
            decorated["_p"] = entry.get("p", "")
            if predicate(decorated):
                flat.append(decorated)
    return flat


def render_card(item: dict) -> str:
    title = escape(item.get("t", ""))
    link = escape(item.get("l", "#"))
    desc = escape(item.get("s", ""))
    group = escape(item.get("g", ""))
    src = item.get("w") and "web-card" or ""
    tag_html = "".join(
        f'<span class="tag">{escape(str(t))}</span>'
        for t in (item.get("tags") or [])[:5]
    )
    debrief = escape(item.get("_d", ""))
    return (
        f'<div class="card {src}" data-full-desc="{escape(desc)}" data-debrief="{escape(item.get("_p", ""))}">'
        f'<div class="card-title"><a href="{link}" target="_blank" rel="noopener">{title}</a></div>'
        f'<div class="card-meta">{group} · {debrief}</div>'
        f'<div class="card-desc">{desc}</div>'
        f'<div class="card-tags">{tag_html}</div>'
        f'</div>'
    )


# Reuse the polished debrief CSS for cards; minimal page-specific styles.
PAGE_CSS = """
  .page-header {
    padding: 56px 20px 32px; text-align: center;
    background: linear-gradient(180deg, var(--bg-elevated, #161b22) 0%, var(--bg, #0d1117) 100%);
    border-bottom: 1px solid var(--border-soft, #21262d);
  }
  .page-header h1 {
    font-size: 2.4em; margin-bottom: 6px; letter-spacing: -0.02em;
    background: linear-gradient(135deg, var(--accent, #58a6ff), var(--accent-purple, #d2a8ff));
    -webkit-background-clip: text; background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  .page-header .subtitle { color: var(--text-muted, #8b949e); font-size: 1em; }
  .page-header .stats { display: flex; justify-content: center; gap: 14px; margin-top: 20px; flex-wrap: wrap; }
  .page-header .stat { background: var(--bg-elevated, #161b22); border: 1px solid var(--border, #30363d); border-radius: 10px; padding: 10px 22px; min-width: 120px; }
  .page-header .stat-num { font-size: 1.5em; font-weight: 700; color: var(--accent, #58a6ff); display: block; font-variant-numeric: tabular-nums; }
  .page-header .stat-label { font-size: 0.72em; color: var(--text-muted, #8b949e); margin-top: 2px; text-transform: uppercase; letter-spacing: 0.05em; }

  .container { max-width: 1140px; margin: 0 auto; padding: 24px 20px; }
  .toolbar { display: flex; gap: 12px; align-items: center; margin-bottom: 28px; flex-wrap: wrap; }
  .search-input { flex: 1; min-width: 220px; background: var(--bg-elevated, #161b22); border: 1px solid var(--border, #30363d); border-radius: 10px; color: var(--text, #c9d1d9); padding: 12px 16px; font-size: 0.95em; font-family: inherit; outline: none; transition: border-color 0.15s, box-shadow 0.15s; }
  .search-input:focus { border-color: var(--accent, #58a6ff); box-shadow: 0 0 0 3px rgba(88, 166, 255, 0.15); }
  .search-input::placeholder { color: var(--text-subtle, #6e7681); }
  .filter-count { color: var(--text-muted, #8b949e); font-size: 0.85em; white-space: nowrap; }

  .cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
  .card { background: var(--bg-elevated, #161b22); border: 1px solid var(--border, #30363d); border-radius: 12px; padding: 18px 20px; transition: border-color 0.18s, transform 0.18s, box-shadow 0.18s; display: flex; flex-direction: column; position: relative; overflow: hidden; }
  .card::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--accent, #58a6ff); opacity: 0.5; transition: opacity 0.18s; }
  .card:hover { border-color: var(--accent, #58a6ff); transform: translateY(-3px); box-shadow: var(--shadow-card, 0 4px 16px rgba(0,0,0,0.4)); }
  .card:hover::before { opacity: 1; }
  .card-title { font-size: 1em; font-weight: 600; margin-bottom: 4px; line-height: 1.4; }
  .card-title a { color: var(--text-bright, #f0f6fc); text-decoration: none; }
  .card-title a:hover { color: var(--accent, #58a6ff); text-decoration: underline; }
  .card-meta { color: var(--text-subtle, #6e7681); font-size: 0.78em; font-family: var(--font-mono, ui-monospace, monospace); margin-bottom: 6px; }
  .card-desc { color: var(--text, #c9d1d9); font-size: 0.88em; line-height: 1.5; margin-bottom: 10px; }
  .card-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: auto; }
  .tag { background: var(--tag-bg, #21262d); color: var(--accent, #58a6ff); font-size: 0.72em; padding: 2px 9px; border-radius: 12px; border: 1px solid var(--border, #30363d); white-space: nowrap; font-family: var(--font-mono, ui-monospace, monospace); }
  .web-card::before { background: var(--accent-purple, #d2a8ff); }

  .back-link { display: inline-block; margin-bottom: 18px; color: var(--accent, #58a6ff); text-decoration: none; font-size: 0.92em; }
  .back-link:hover { text-decoration: underline; }

  .footer { text-align: center; padding: 32px 20px; margin-top: 56px; border-top: 1px solid var(--border-soft, #21262d); color: var(--text-subtle, #6e7681); font-size: 0.85em; }
  .footer a { color: var(--accent, #58a6ff); text-decoration: none; }
  .footer a:hover { text-decoration: underline; }

  @media (max-width: 700px) {
    .page-header h1 { font-size: 1.7em; }
    .cards-grid { grid-template-columns: 1fr; }
    .page-header .stat { padding: 8px 14px; }
  }
"""

PAGE_JS = """
  const search = document.getElementById('search');
  const filterCount = document.getElementById('filter-count');
  const cards = Array.from(document.querySelectorAll('.card'));
  function apply() {
    const q = (search.value || '').trim().toLowerCase();
    let shown = 0;
    cards.forEach((c) => {
      if (!q) { c.classList.remove('hidden'); shown++; return; }
      const text = (c.textContent + ' ' + (c.dataset.fullDesc || '')).toLowerCase();
      if (text.includes(q)) { c.classList.remove('hidden'); shown++; }
      else { c.classList.add('hidden'); }
    });
    filterCount.textContent = q ? shown + ' of ' + cards.length + ' cards' : '';
  }
  if (search) search.addEventListener('input', apply);
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement.tagName !== 'INPUT') {
      e.preventDefault(); search.focus();
    }
  });
"""


def render_page(*, title: str, subtitle: str, items: list[dict], rel_path: str = "") -> str:
    """Render a topic / feed page. `rel_path` is the path back to root from the page."""
    cards_html = "\n".join(render_card(it) for it in items)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    # Bump on every theme-affecting commit. Mirrors the rest of the site.
    ASSET_VERSION = "7"
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="github-dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="cache-control" content="no-cache, no-store, must-revalidate">
<title>Carlos's Debrief — {escape(title)}</title>
<link rel="alternate" type="application/rss+xml" title="Carlos's Debrief" href="{rel_path}feed.xml">
<link rel="icon" href="data:,">
<link rel="stylesheet" href="{rel_path}assets/themes.css?v={ASSET_VERSION}">
<script src="{rel_path}assets/theme-switcher.js?v={ASSET_VERSION}" defer></script>
<style>
  :root {{
    /* Theme tokens come from themes.css — DO NOT redefine them here or the
       active theme loses. Only local-layout aliases go in this block. */
  }}
  {PAGE_CSS}
</style>
</head>
<body>
<div id="theme-picker" class="theme-picker" role="group" aria-label="Theme switcher">
  <button type="button" data-theme="github-dark">Default</button>
  <button type="button" data-theme="cyber">Cyber</button>
  <button type="button" data-theme="modern">Modern</button>
  <button type="button" data-theme="dark-mono">Mono</button>
  <button type="button" data-theme="light">Light</button>
</div>
<div class="page-header">
  <h1>{escape(title)}</h1>
  <div class="subtitle">{escape(subtitle)}</div>
  <div class="stats">
    <div class="stat"><span class="stat-num">{len(items)}</span><span class="stat-label">items</span></div>
    <div class="stat"><span class="stat-num">{len(set(i.get('_d','')[:10] for i in items if i.get('_d')))}</span><span class="stat-label">days</span></div>
    <div class="stat"><span class="stat-num">{sum(1 for i in items if i.get('w'))}</span><span class="stat-label">news</span></div>
    <div class="stat"><span class="stat-num">{sum(1 for i in items if not i.get('w'))}</span><span class="stat-label">papers</span></div>
  </div>
</div>
<div class="container">
  <a class="back-link" href="{rel_path}index.html">← back to all debriefs</a>
  <div class="toolbar">
    <input type="text" id="search" class="search-input" placeholder="Filter cards…" />
    <span class="filter-count" id="filter-count"></span>
  </div>
  <div class="cards-grid">
{cards_html}
  </div>
</div>
<div class="footer">
  <a href="{rel_path}index.html">Carlos's Debrief</a> · curated by Hermes Research Scout · generated {escape(generated_at)} · alt+T to change theme
</div>
<script>{PAGE_JS}</script>
</body>
</html>
"""


def build_topic_pages(index: list[dict], out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(exist_ok=True)
    counts = {}
    for slug, title, groups, kws in TOPICS:
        items = collect_items(index, lambda it: item_matches(it, groups, kws))
        # Newest first by debrief_date
        items.sort(key=lambda it: it.get("_d", ""), reverse=True)
        # Cap to most recent 200 to keep file sizes sane
        items = items[:200]
        page = render_page(
            title=title,
            subtitle=f"All {len(items)} items on this topic, newest first.",
            items=items,
            rel_path="../",
        )
        (out_dir / f"{slug}.html").write_text(page)
        counts[slug] = len(items)
    return counts


def build_feed_pages(index: list[dict], out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(exist_ok=True)
    papers = collect_items(index, lambda it: not it.get("w"))
    news = collect_items(index, lambda it: bool(it.get("w")))
    for items, slug, title, sub in [
        (papers, "research-feed", "Research Feed", "Every research / paper / preprint, newest first."),
        (news,   "news-feed",     "News Feed",     "Every web finding (Hacker News, Lobste.rs, Google Scholar), newest first."),
    ]:
        items.sort(key=lambda it: it.get("_d", ""), reverse=True)
        items = items[:400]
        page = render_page(title=title, subtitle=sub, items=items, rel_path="../")
        (out_dir / f"{slug}.html").write_text(page)
    return {"research": len(papers), "news": len(news)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if not INDEX.exists():
        print(f"[err] {INDEX} not found — run build_index.py first", file=__import__("sys").stderr)
        return 1

    index = json.loads(INDEX.read_text())
    topic_dir = REPO / "topics"
    feed_dir = REPO  # root-level: research-feed.html + news-feed.html

    topic_counts = build_topic_pages(index, topic_dir)
    feed_counts = build_feed_pages(index, feed_dir)

    summary = {**topic_counts, **{f"feed:{k}": v for k, v in feed_counts.items()}}
    print(f"topic/feed pages built: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

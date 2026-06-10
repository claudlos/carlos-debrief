#!/usr/bin/env python3
"""Generate a one-time Hermes-judged Top 100 page from historical debriefs."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


DEFAULT_HERMES_COMMAND = "hermes"
DEFAULT_RUBRIC = (
    "Score each historical debrief item from 0 to 1000 for long-term importance "
    "to AI, machine learning, security, cryptography, agents, AI safety, quantum "
    "computing, and adjacent research strategy. Reward technical significance, "
    "novelty, practical impact, credible evidence, and strong fit with the debrief "
    "topics. Penalize generic roundups, weak source text, low relevance, or narrow "
    "incremental work. Use the FULL range and spread scores out (avoid clustering): "
    "900-1000 = landmark/foundational; 700-899 = high impact; 450-699 = solid/notable; "
    "200-449 = incremental/niche; 1-199 = roundup/noise/low-signal."
)


@dataclass
class Card:
    item_id: str
    title: str
    url: str
    authors: str
    description: str
    full_description: str
    tags: list[str]
    section: str
    group: str
    source: str
    item_type: str
    debrief_date: str
    debrief_path: str
    debrief_md: str
    sort_date: str
    card_class: str
    occurrences: list[dict[str, str]] = field(default_factory=list)


class DebriefCardParser(HTMLParser):
    def __init__(self, debrief: dict[str, Any]):
        super().__init__(convert_charrefs=True)
        self.debrief = debrief
        self.cards: list[dict[str, Any]] = []
        self.section = ""
        self.group = ""
        self.heading_capture: str | None = None
        self.heading_text: list[str] = []
        self.current: dict[str, Any] | None = None
        self.card_depth = 0
        self.capture: str | None = None
        self.capture_text: list[str] = []
        self.current_tag_text: list[str] | None = None
        self.in_title_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name: value or "" for name, value in attrs}
        classes = set(attr.get("class", "").split())

        if self.current is not None:
            self.card_depth += 1
            if tag == "a" and self.capture == "title" and not self.current.get("url"):
                self.current["url"] = attr.get("href", "")
                self.in_title_link = True
            if tag == "span" and "tag" in classes:
                self.current_tag_text = []
            return

        if tag in {"h2", "h3"}:
            self.heading_capture = tag
            self.heading_text = []
            return

        if tag == "div" and "card" in classes:
            self.current = {
                "title": "",
                "url": "",
                "authors": "",
                "description": "",
                "full_description": attr.get("data-full-desc", ""),
                "tags": [],
                "section": clean_heading(self.section),
                "group": clean_heading(self.group),
                "card_class": attr.get("class", ""),
            }
            self.card_depth = 1
            return

        if self.current is not None:
            return

        if tag == "div" and "card-title" in classes:
            self.capture = "title"

    def handle_endtag(self, tag: str) -> None:
        if self.current is not None:
            if self.in_title_link and tag == "a":
                self.in_title_link = False

            if self.current_tag_text is not None and tag == "span":
                value = normalize_space("".join(self.current_tag_text))
                if value:
                    self.current["tags"].append(value)
                self.current_tag_text = None

            if self.capture and tag == "div":
                value = normalize_space("".join(self.capture_text))
                if self.capture == "title":
                    self.current["title"] = strip_source_number(value)
                elif self.capture == "authors":
                    self.current["authors"] = value
                elif self.capture == "description":
                    self.current["description"] = value
                self.capture = None
                self.capture_text = []

            self.card_depth -= 1
            if self.card_depth == 0:
                if self.current.get("title"):
                    self.cards.append(self.current)
                self.current = None
            return

        if self.heading_capture == tag:
            value = normalize_space("".join(self.heading_text))
            if tag == "h2":
                self.section = value
                self.group = ""
            elif tag == "h3":
                self.group = value
            self.heading_capture = None
            self.heading_text = []

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            if self.current_tag_text is not None:
                self.current_tag_text.append(data)
            if self.capture is not None:
                self.capture_text.append(data)
            return
        if self.heading_capture is not None:
            self.heading_text.append(data)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


class CardDetailParser(HTMLParser):
    """Second-pass parser for card detail divs.

    The main parser sees nested card content, but class transitions occur after the
    card starts. This small parser reads each card fragment independently.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.data: dict[str, Any] = {"tags": []}
        self.capture: str | None = None
        self.capture_text: list[str] = []
        self.tag_text: list[str] | None = None
        self.in_title_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name: value or "" for name, value in attrs}
        classes = set(attr.get("class", "").split())
        if "card-title" in classes:
            self.capture = "title"
            self.capture_text = []
        elif "card-authors" in classes:
            self.capture = "authors"
            self.capture_text = []
        elif "card-desc" in classes:
            self.capture = "description"
            self.capture_text = []
        elif tag == "div":
            return
        elif tag == "a" and self.capture == "title" and not self.data.get("url"):
            self.data["url"] = attr.get("href", "")
            self.in_title_link = True
        elif tag == "span" and "tag" in classes:
            self.tag_text = []

    def handle_endtag(self, tag: str) -> None:
        if self.in_title_link and tag == "a":
            self.in_title_link = False
        if self.tag_text is not None and tag == "span":
            value = normalize_space("".join(self.tag_text))
            if value:
                self.data["tags"].append(value)
            self.tag_text = None
        if self.capture and tag in {"div", "h3", "p"}:
            value = normalize_space("".join(self.capture_text))
            if self.capture == "title":
                self.data["title"] = strip_source_number(value)
            else:
                self.data[self.capture] = value
            self.capture = None
            self.capture_text = []

    def handle_data(self, data: str) -> None:
        if self.tag_text is not None:
            self.tag_text.append(data)
        if self.capture is not None:
            self.capture_text.append(data)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_heading(value: str) -> str:
    value = normalize_space(value)
    value = re.sub(r"\s+\d+\s*$", "", value)
    return value


def strip_source_number(value: str) -> str:
    return re.sub(r"\s*\[\d+\]\s*$", "", normalize_space(value))


def source_from_card(card: dict[str, Any]) -> str:
    tags = card.get("tags") or []
    group = card.get("group") or ""
    url = card.get("url") or ""
    url_lower = url.lower()
    if "arxiv.org" in url_lower:
        return "ArXiv"
    if "huggingface.co" in url_lower:
        return "HuggingFace"
    if "lobste.rs" in url_lower or "lobsters" in url_lower:
        return "Lobste.rs"
    if "news.ycombinator.com" in url_lower:
        return "Hacker News"
    known = ["ArXiv", "HuggingFace", "Google Scholar", "Hacker News", "Lobste.rs"]
    for value in [*tags, group]:
        value_lower = value.lower()
        if value_lower in {"hf", "huggingface", "huggingface papers"}:
            return "HuggingFace"
        if value_lower in {"lobsters", "lobste.rs"}:
            return "Lobste.rs"
        if value_lower in {"hn", "hacker news"}:
            return "Hacker News"
        if value_lower in {"scholar", "google scholar"}:
            return "Google Scholar"
        for name in known:
            if name.lower() in value_lower:
                return name
    return clean_heading(group) or "Web"


def item_type_from_source(source: str) -> str:
    if source in {"ArXiv", "HuggingFace", "Google Scholar"}:
        return "paper"
    return "news"


def parse_sort_date(debrief: dict[str, Any]) -> str:
    path = debrief.get("html", "")
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})[- ](\d{2})(?:[-:](\d{2}))?", path)
    if match:
        minute = match.group(5) or "00"
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}T{match.group(4)}:{minute}:00Z"
    value = debrief.get("date", "")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H", "%B %d, %Y %H:%M"):
        try:
            return dt.datetime.strptime(value, fmt).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return ""


def normalize_url(value: str) -> str:
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value.strip())
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = re.sub(r"/+$", "", parsed.path)
    query_pairs = [
        (key, val)
        for key, val in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    query = urllib.parse.urlencode(query_pairs, doseq=True)
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def dedupe_key(card: dict[str, Any]) -> str:
    url = normalize_url(card.get("url", ""))
    if url:
        return "url:" + url
    return "title:" + normalize_space(card.get("title", "")).lower()


def extract_card_fragments(html_text: str) -> list[dict[str, str]]:
    fragments: list[dict[str, str]] = []
    pattern = re.compile(r'<div class="([^"]*)"([^>]*)>', re.IGNORECASE)
    for match in pattern.finditer(html_text):
        if "card" not in match.group(1).split():
            continue
        start = match.start()
        idx = match.end()
        depth = 1
        while depth > 0:
            next_open = html_text.find("<div", idx)
            next_close = html_text.find("</div>", idx)
            if next_close == -1:
                break
            if next_open != -1 and next_open < next_close:
                depth += 1
                idx = next_open + 4
            else:
                depth -= 1
                idx = next_close + len("</div>")
        fragment = html_text[start:idx]
        fragments.append({"class": match.group(1), "attrs": match.group(2), "html": fragment})
    return fragments


def extract_full_desc(attrs: str) -> str:
    match = re.search(r"""data-full-desc=(["'])(.*?)\1""", attrs, re.DOTALL)
    if not match:
        return ""
    return html.unescape(match.group(2))


def extract_headings_before(html_text: str, offset: int) -> tuple[str, str]:
    before = html_text[:offset]
    h2s = re.findall(r"<h2[^>]*>(.*?)</h2>", before, re.IGNORECASE | re.DOTALL)
    h3s = re.findall(r"<h3[^>]*>(.*?)</h3>", before, re.IGNORECASE | re.DOTALL)
    section = clean_heading(strip_tags(h2s[-1])) if h2s else ""
    group = clean_heading(strip_tags(h3s[-1])) if h3s else ""
    return section, group


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(normalize_space(value))


def parse_debrief_file(path: Path, debrief: dict[str, Any]) -> list[dict[str, Any]]:
    html_text = path.read_text(encoding="utf-8")
    cards: list[dict[str, Any]] = []
    for fragment in extract_card_fragments(html_text):
        parser = CardDetailParser()
        parser.feed(fragment["html"])
        data = parser.data
        title = normalize_space(data.get("title", ""))
        if not title:
            continue
        offset = html_text.find(fragment["html"][:80])
        section, group = extract_headings_before(html_text, offset if offset >= 0 else 0)
        card = {
            "title": title,
            "url": data.get("url", ""),
            "authors": data.get("authors", ""),
            "description": data.get("description", ""),
            "full_description": extract_full_desc(fragment["attrs"]),
            "tags": data.get("tags", []),
            "section": section,
            "group": group,
            "card_class": fragment["class"],
        }
        source = source_from_card(card)
        card["source"] = source
        card["item_type"] = item_type_from_source(source)
        card["debrief_date"] = debrief.get("date", "")
        card["debrief_path"] = debrief.get("html", "")
        card["debrief_md"] = debrief.get("md", "")
        card["sort_date"] = parse_sort_date(debrief)
        cards.append(card)
    return cards


def load_manifest(repo_root: Path) -> list[dict[str, Any]]:
    with (repo_root / "manifest.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def extract_unique_items(repo_root: Path, max_items: int | None = None) -> tuple[list[Card], dict[str, int]]:
    manifest = load_manifest(repo_root)
    raw_count = 0
    skipped_files = 0
    by_key: dict[str, Card] = {}

    for debrief in manifest:
        html_path = repo_root / debrief.get("html", "")
        if not html_path.exists():
            skipped_files += 1
            continue
        for raw in parse_debrief_file(html_path, debrief):
            raw_count += 1
            key = dedupe_key(raw)
            occurrence = {
                "debrief_date": raw.get("debrief_date", ""),
                "debrief_path": raw.get("debrief_path", ""),
                "debrief_md": raw.get("debrief_md", ""),
            }
            existing = by_key.get(key)
            if existing is None:
                card = Card(
                    item_id=f"item_{len(by_key) + 1:05d}",
                    title=raw.get("title", ""),
                    url=raw.get("url", ""),
                    authors=raw.get("authors", ""),
                    description=raw.get("description", ""),
                    full_description=raw.get("full_description", ""),
                    tags=list(raw.get("tags", [])),
                    section=raw.get("section", ""),
                    group=raw.get("group", ""),
                    source=raw.get("source", ""),
                    item_type=raw.get("item_type", ""),
                    debrief_date=raw.get("debrief_date", ""),
                    debrief_path=raw.get("debrief_path", ""),
                    debrief_md=raw.get("debrief_md", ""),
                    sort_date=raw.get("sort_date", ""),
                    card_class=raw.get("card_class", ""),
                    occurrences=[occurrence],
                )
                by_key[key] = card
            else:
                existing.occurrences.append(occurrence)
                existing.tags = sorted(set(existing.tags).union(raw.get("tags", [])))
                if len(raw.get("full_description", "")) > len(existing.full_description):
                    existing.full_description = raw.get("full_description", "")
                if raw.get("sort_date", "") > existing.sort_date:
                    existing.sort_date = raw.get("sort_date", "")
                    existing.debrief_date = raw.get("debrief_date", "")
                    existing.debrief_path = raw.get("debrief_path", "")
                    existing.debrief_md = raw.get("debrief_md", "")
            if max_items and len(by_key) >= max_items:
                break
        if max_items and len(by_key) >= max_items:
            break

    stats = {
        "manifest_entries": len(manifest),
        "raw_cards": raw_count,
        "unique_items": len(by_key),
        "skipped_files": skipped_files,
    }
    return list(by_key.values()), stats


def prompt_item(card: Card) -> dict[str, Any]:
    text = card.full_description or card.description
    return {
        "id": card.item_id,
        "title": card.title[:260],
        "source": card.source,
        "type": card.item_type,
        "date": card.debrief_date,
        "authors_or_source": card.authors[:220],
        "tags": card.tags[:8],
        "section": card.section,
        "group": card.group,
        "recurrence_count": len(card.occurrences),
        "description": text[:900],
    }


def hermes_prompt(batch: list[Card]) -> str:
    payload = {
        "rubric": DEFAULT_RUBRIC,
        "items": [prompt_item(card) for card in batch],
    }
    return (
        "You are ranking historical research/news cards for Carlos's Debrief.\n"
        "Apply the rubric consistently and return one rating for every input id.\n"
        "Scores must be comparable across batches. Keep each rationale under 24 words.\n"
        "Return ONLY valid JSON, with no markdown fence, no prose, and this exact shape:\n"
        '{"ratings":[{"id":"item_00001","score":872,"rationale":"Short reason."}]}\n\n'
        "Rules:\n"
        "- score must be an integer from 0 to 1000.\n"
        "- every input id must appear exactly once.\n"
        "- do not invent ids.\n\n"
        "Input JSON:\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def call_hermes(batch: list[Card], hermes_command: str, retries: int = 3) -> dict[str, dict[str, Any]]:
    command = shlex.split(hermes_command) + ["-z", hermes_prompt(batch)]
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            completed = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
                timeout=600,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Hermes exited {completed.returncode}: "
                    f"{(completed.stderr or completed.stdout).strip()[:2000]}"
                )
            parsed = parse_json_response(completed.stdout)
            ratings = parsed.get("ratings", [])
            result: dict[str, dict[str, Any]] = {}
            for item in ratings:
                item_id = str(item.get("id", ""))
                if not item_id:
                    continue
                result[item_id] = {
                    "id": item_id,
                    "score": max(0, min(1000, int(item.get("score", 0)))),
                    "rationale": normalize_space(str(item.get("rationale", ""))),
                }
            expected = {card.item_id for card in batch}
            missing = expected.difference(result)
            extra = set(result).difference(expected)
            if missing or extra:
                raise RuntimeError(
                    f"Hermes response id mismatch; missing={sorted(missing)[:8]}, "
                    f"extra={sorted(extra)[:8]}"
                )
            return result
        except Exception as exc:  # noqa: BLE001 - keep retry path simple for CLI output.
            last_error = exc
            time.sleep(min(30, 2 ** attempt + 1))
    raise RuntimeError(f"Hermes request failed after {retries} attempts: {last_error}") from last_error


def load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_cache(path: Path, cache: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    tmp.replace(path)


def rate_items(items: list[Card], hermes_command: str, batch_size: int, cache_path: Path, workers: int = 4) -> dict[str, dict[str, Any]]:
    cache = load_cache(cache_path)
    cache_key = f"hermes:{hermes_command}"
    model_cache = cache.setdefault(cache_key, {})
    lock = threading.Lock()
    total = len(items)
    jobs: list[tuple[int, list[Card]]] = []
    for offset in range(0, total, batch_size):
        batch = items[offset : offset + batch_size]
        pending = [card for card in batch if card.item_id not in model_cache]
        if pending:
            jobs.append((offset, pending))
    if not jobs:
        return model_cache
    print(f"Rating {total} items in {len(jobs)} batches with {workers} workers", flush=True)
    done = [0]

    def work(job: tuple[int, list[Card]]) -> None:
        offset, pending = job
        result = call_hermes(pending, hermes_command)
        with lock:
            for item_id, rating in result.items():
                model_cache[item_id] = rating
            save_cache(cache_path, cache)  # incremental: resumable on interruption
            done[0] += 1
            print(f"  [{done[0]}/{len(jobs)}] batch @ {offset} (+{len(pending)})", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        for future in as_completed([executor.submit(work, job) for job in jobs]):
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001 - log and continue; unrated items just drop out
                print(f"  batch failed (skipped): {exc}", flush=True)
    return model_cache


def card_to_output(card: Card, rating: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card.item_id,
        "rank": 0,
        "score": int(rating["score"]),
        "rationale": normalize_space(rating.get("rationale", "")),
        "title": card.title,
        "url": card.url,
        "authors": card.authors,
        "description": card.full_description or card.description,
        "summary": card.description,
        "tags": card.tags,
        "source": card.source,
        "type": card.item_type,
        "section": card.section,
        "group": card.group,
        "debrief_date": card.debrief_date,
        "debrief_path": card.debrief_path,
        "debrief_md": card.debrief_md,
        "occurrence_count": len(card.occurrences),
        "occurrences": card.occurrences[:10],
        "sort_date": card.sort_date,
    }


def build_top100(items: list[Card], ratings: dict[str, dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for card in items:
        rating = ratings.get(card.item_id)
        if not rating:
            continue
        output.append(card_to_output(card, rating))
    output.sort(
        key=lambda item: (
            item["score"],
            item["occurrence_count"],
            item.get("sort_date", ""),
            item.get("title", "").lower(),
        ),
        reverse=True,
    )
    for index, item in enumerate(output[:limit], start=1):
        item["rank"] = index
    return output[:limit]


def count_by(items: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = item.get(field) or "Unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def truncate(value: str, limit: int) -> str:
    value = normalize_space(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def render_html(data: dict[str, Any]) -> str:
    generated = data["generated_at"].replace("T", " ").replace("Z", " UTC")
    items_json = html.escape(json.dumps(data["items"], ensure_ascii=False), quote=False)
    ranked_count = len(data["items"])
    source_options = "\n".join(
        f'<option value="{html.escape(source)}">{html.escape(source)}</option>'
        for source in data["stats"]["top100_by_source"]
    )
    rows = "\n".join(render_item(item) for item in data["items"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Carlos's Debrief - Top 500</title>
<style>
  :root {{
    --bg: #0d1117;
    --card: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-bright: #f0f6fc;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --accent-green: #3fb950;
    --accent-orange: #f0883e;
    --tag-bg: #21262d;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    line-height: 1.55;
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px 18px 48px; }}
  .topbar {{ margin-bottom: 28px; }}
  .topbar a {{ color: var(--text-muted); text-decoration: none; font-size: 0.9rem; }}
  .topbar a:hover {{ color: var(--accent); }}
  h1 {{ color: var(--text-bright); font-size: 2.15rem; margin-bottom: 8px; letter-spacing: 0; }}
  .subtitle {{ color: var(--text-muted); max-width: 760px; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, minmax(130px, 1fr)); gap: 12px; margin: 24px 0; }}
  .stat {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }}
  .num {{ color: var(--accent-green); font-size: 1.55rem; font-weight: 700; line-height: 1.1; }}
  .label {{ color: var(--text-muted); font-size: 0.78rem; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.04em; }}
  .toolbar {{ display: grid; grid-template-columns: 1fr 180px 150px; gap: 10px; margin-bottom: 18px; }}
  input, select {{
    width: 100%;
    background: var(--card);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 11px 12px;
    font: inherit;
  }}
  input:focus, select:focus {{ outline: 2px solid rgba(88,166,255,0.32); border-color: var(--accent); }}
  .count {{ color: var(--text-muted); font-size: 0.9rem; margin-bottom: 12px; }}
  .list {{ display: grid; gap: 12px; }}
  .item {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 18px;
  }}
  .item-head {{ display: grid; grid-template-columns: 64px 1fr auto; gap: 14px; align-items: start; }}
  .rank {{ color: var(--accent); font-size: 1.1rem; font-weight: 700; }}
  .score {{ color: var(--accent-green); font-weight: 700; white-space: nowrap; }}
  .title {{ color: var(--text-bright); font-size: 1rem; font-weight: 650; text-decoration: none; }}
  .title:hover {{ color: var(--accent); text-decoration: underline; }}
  .meta {{ color: var(--text-muted); font-size: 0.86rem; margin: 4px 0 10px; }}
  .rationale {{ color: var(--text); margin-bottom: 10px; }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .tag {{ background: var(--tag-bg); color: #79c0ff; border: 1px solid var(--border); border-radius: 999px; padding: 2px 9px; font-size: 0.75rem; }}
  .links {{ margin-top: 10px; display: flex; gap: 14px; flex-wrap: wrap; }}
  .links a {{ color: var(--text-muted); font-size: 0.85rem; text-decoration: none; }}
  .links a:hover {{ color: var(--accent); text-decoration: underline; }}
  footer {{ color: var(--text-muted); border-top: 1px solid var(--border); margin-top: 32px; padding-top: 16px; font-size: 0.84rem; text-align: center; }}
  .hidden {{ display: none; }}
  @media (max-width: 760px) {{
    .wrap {{ padding: 20px 12px 36px; }}
    h1 {{ font-size: 1.55rem; }}
    .stats {{ grid-template-columns: repeat(2, 1fr); }}
    .toolbar {{ grid-template-columns: 1fr; }}
    .item-head {{ grid-template-columns: 48px 1fr; }}
    .score {{ grid-column: 2; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar"><a href="index.html">&larr; All debriefs</a></div>
  <h1>Top 500 Rated Items</h1>
  <p class="subtitle">Hermes-judged ranking (scored out of 1000) across historical Carlos's Debrief papers and news cards. Generated {html.escape(generated)} with {html.escape(data["model"])}.</p>

  <div class="stats">
    <div class="stat"><div class="num">{ranked_count}</div><div class="label">Ranked Items</div></div>
    <div class="stat"><div class="num">{data["stats"]["unique_items"]}</div><div class="label">Unique Judged</div></div>
    <div class="stat"><div class="num">{data["stats"]["raw_cards"]}</div><div class="label">Cards Parsed</div></div>
    <div class="stat"><div class="num">{data["stats"]["manifest_entries"]}</div><div class="label">Debriefs</div></div>
  </div>

  <div class="toolbar">
    <input id="search" type="search" placeholder="Search titles, rationale, source, tags">
    <select id="source">
      <option value="">All sources</option>
      {source_options}
    </select>
    <select id="type">
      <option value="">All types</option>
      <option value="paper">Papers</option>
      <option value="news">News</option>
    </select>
  </div>
  <div class="count" id="count">Showing 500 of 500</div>

  <div class="list" id="list">
    {rows}
  </div>

  <footer>
    Generated by <code>scripts/generate_top100.py</code>. Data artifact: <a href="top100.json" style="color:var(--text-muted);">top100.json</a>.
  </footer>
</div>
<script type="application/json" id="top100-data">{items_json}</script>
<script>
(function () {{
  const cards = Array.from(document.querySelectorAll('.item'));
  const search = document.getElementById('search');
  const source = document.getElementById('source');
  const type = document.getElementById('type');
  const count = document.getElementById('count');
  function applyFilter() {{
    const q = search.value.trim().toLowerCase();
    const s = source.value;
    const t = type.value;
    let shown = 0;
    cards.forEach((card) => {{
      const matchesSearch = !q || card.dataset.search.includes(q);
      const matchesSource = !s || card.dataset.source === s;
      const matchesType = !t || card.dataset.type === t;
      const visible = matchesSearch && matchesSource && matchesType;
      card.classList.toggle('hidden', !visible);
      if (visible) shown += 1;
    }});
    count.textContent = 'Showing ' + shown + ' of ' + cards.length;
  }}
  [search, source, type].forEach((el) => el.addEventListener('input', applyFilter));
}}());
</script>
</body>
</html>
"""


def render_item(item: dict[str, Any]) -> str:
    tags = [item.get("source", ""), item.get("type", ""), *item.get("tags", [])]
    tags_html = "".join(f'<span class="tag">{html.escape(tag)}</span>' for tag in tags if tag)
    title = html.escape(item["title"])
    title_link = item.get("url") or item.get("debrief_path", "")
    search_text = " ".join(
        [
            item.get("title", ""),
            item.get("rationale", ""),
            item.get("description", ""),
            item.get("source", ""),
            item.get("type", ""),
            " ".join(item.get("tags", [])),
        ]
    ).lower()
    meta_bits = [
        item.get("source", ""),
        item.get("debrief_date", ""),
    ]
    if item.get("occurrence_count", 0) > 1:
        meta_bits.append(f"{item['occurrence_count']} appearances")
    meta = " / ".join(bit for bit in meta_bits if bit)
    summary = truncate(item.get("summary") or item.get("description", ""), 260)
    return f"""    <article class="item" data-source="{html.escape(item.get("source", ""))}" data-type="{html.escape(item.get("type", ""))}" data-search="{html.escape(search_text)}">
      <div class="item-head">
        <div class="rank">#{item["rank"]}</div>
        <div>
          <a class="title" href="{html.escape(title_link)}" target="_blank" rel="noopener">{title}</a>
          <div class="meta">{html.escape(meta)}</div>
          <div class="rationale"><strong>{item["score"]}/1000</strong> - {html.escape(item.get("rationale", ""))}</div>
          <p class="meta">{html.escape(summary)}</p>
          <div class="tags">{tags_html}</div>
          <div class="links">
            <a href="{html.escape(item.get("url", ""))}" target="_blank" rel="noopener">Original</a>
            <a href="{html.escape(item.get("debrief_path", ""))}">Source debrief</a>
            <a href="{html.escape(item.get("debrief_md", ""))}">Markdown</a>
          </div>
        </div>
        <div class="score">{item["score"]}/1000</div>
      </div>
    </article>"""


def write_html(path: Path, data: dict[str, Any]) -> None:
    path.write_text(render_html(data), encoding="utf-8")


def build_output_data(
    top_items: list[dict[str, Any]],
    stats: dict[str, int],
    model: str,
) -> dict[str, Any]:
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "model": model,
        "rubric": DEFAULT_RUBRIC,
        "stats": {
            **stats,
            "top100_by_source": count_by(top_items, "source"),
            "top100_by_type": count_by(top_items, "type"),
        },
        "items": top_items,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", type=Path)
    parser.add_argument("--hermes-command", default=os.environ.get("HERMES_COMMAND", DEFAULT_HERMES_COMMAND))
    parser.add_argument("--limit", default=500, type=int)
    parser.add_argument("--batch-size", default=60, type=int)
    parser.add_argument("--workers", default=4, type=int, help="Parallel hermes rating calls.")
    parser.add_argument("--max-items", default=None, type=int, help="Limit unique items for smoke tests.")
    parser.add_argument("--cache", default=".top100-ratings-cache.json", type=Path)
    parser.add_argument("--output-json", default="top100.json", type=Path)
    parser.add_argument("--output-html", default="top-100.html", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Parse and print stats without calling Hermes or writing outputs.")
    parser.add_argument("--render-only", action="store_true", help="Regenerate HTML from an existing top100 JSON file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_json = args.output_json if args.output_json.is_absolute() else repo_root / args.output_json
    output_html = args.output_html if args.output_html.is_absolute() else repo_root / args.output_html
    cache_path = args.cache if args.cache.is_absolute() else repo_root / args.cache

    if args.render_only:
        with output_json.open(encoding="utf-8") as handle:
            data = json.load(handle)
        write_html(output_html, data)
        print(f"Wrote {output_html}")
        return 0

    items, stats = extract_unique_items(repo_root, max_items=args.max_items)
    print(json.dumps(stats, indent=2), flush=True)
    if args.dry_run:
        return 0

    ratings = rate_items(items, args.hermes_command, args.batch_size, cache_path, args.workers)
    top_items = build_top100(items, ratings, args.limit)
    data = build_output_data(top_items, stats, f"Hermes Agent ({args.hermes_command})")
    write_json(output_json, data)
    write_html(output_html, data)
    print(f"Wrote {output_json}")
    print(f"Wrote {output_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

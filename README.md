# Carlos's Debrief

> Auto-generated AI research debriefs from arXiv, HuggingFace, Lobste.rs,
> Hacker News, and Google Scholar — published twice a day to a static site
> you can read in a browser.

**🔗 Live: [claudlos.github.io/carlos-debrief](https://claudlos.github.io/carlos-debrief/)**

![Dashboard](assets/dashboard.png)

## What it is

A pipeline that scouts the web for new research across **19 arXiv topic searches**,
deduplicates against everything it has ever surfaced before, compiles the
harvest into a digest, and publishes the result as a self-contained HTML
page on GitHub Pages.

The goal is to **not have to open ten tabs** every morning. Click any card
to zoom in and read the full abstract without leaving the page.

## Features

- **📰 Two summary boxes** at the top of every debrief: one for arXiv research highlights, one for trending news headlines.
- **🔍 Click-to-zoom modal** — click any paper or news card to read the full abstract in a large reading view. `←` / `→` to navigate, `Esc` to close.
- **🔎 In-page search filter** — type to instantly filter all cards across every section by title, authors, or tags. Press `/` to focus the search box.
- **🔁 Persistent dedup** — every paper/article ID and title hash is recorded forever, so the same paper never appears in two debriefs.
- **📚 Full abstracts** — every arXiv card embeds the full untruncated abstract; web cards embed the article's `<meta description>` or first paragraph.
- **🎨 3 themes** — switch with the widget in the top-right corner, or press **Alt+T** to cycle. Persists in `localStorage`.

### Themes

| Theme | Look |
|---|---|
| **Default** | GitHub-dark — the original palette |
| **Cyber** | Neon cyan + hot pink, monospace headings, glow effects |
| **Monk** | Warm sepia + deep brown, serif headings, contemplative |

![Click-to-zoom modal showing full abstract](assets/modal.png)

## Sources

| Source | Method | What it's good for |
| --- | --- | --- |
| **arXiv** | REST API | Daily fresh papers across 19 topic searches |
| **HuggingFace daily papers** | JSON API | Curated trending ML papers, with upvotes and full abstracts |
| **Lobste.rs** | JSON API (`/t/{tag}.json`) | High-signal infosec / compsci link aggregator |
| **Hacker News** | Algolia search | Tech news front-page conversations |
| **Google Scholar** | camoufox scrape | Citation-based discovery for general topics |
| **GitHub Trending** | API + REST | Trending repos by topic & language |
| **Reddit** | JSON | r/MachineLearning, r/LocalLLaMA, r/netsec, r/programming |
| **Semantic Scholar** | API | Citation graph + paper metadata |
| **OpenReview** | API | Conference submissions (NeurIPS, ICML, etc.) |
| **X / Twitter** | Search API | Trending threads by topic |

### Topics searched (19)

Artificial Intelligence · Machine Learning · Large Language Models · AI Agents & Reasoning · AI Safety & Guardrails · Security & Cybersecurity · Hacking & Pen Testing · Bug Bounty & Vulns · CVE & Malware · Cryptography · Zero Knowledge · Quantum Computing · **Zero-Point Energy** · Crypto & Blockchain · **Decentralized Networks** · **Networking** · **Coding & SE** · **Educational Systems** · **Open-Source Ecosystem**

## Curated topic pages

Each curated page pulls every item matching that topic across all historical debriefs (newest first):

- [Security & Cybersecurity](https://claudlos.github.io/carlos-debrief/topics/security.html) — CVEs, malware, fuzzing, SBOM
- [Hacking & Pen Testing](https://claudlos.github.io/carlos-debrief/topics/hacking.html) — exploits, red-team, bug bounty
- [AI Safety & Guardrails](https://claudlos.github.io/carlos-debrief/topics/ai-safety.html) — alignment, jailbreaks, content moderation
- [Coding & Compilers](https://claudlos.github.io/carlos-debrief/topics/coding.html) — formal verification, type systems, program repair
- [Open-Source Ecosystem](https://claudlos.github.io/carlos-debrief/topics/oss.html) — FOSS, licensing
- [Decentralized Networks](https://claudlos.github.io/carlos-debrief/topics/decentralized.html) — P2P, gossip, distributed systems
- [Networking & Protocols](https://claudlos.github.io/carlos-debrief/topics/networking.html) — TCP, QUIC, BGP, SDN, mesh
- [Quantum & Zero-Point](https://claudlos.github.io/carlos-debrief/topics/quantum.html) — qubits, ZPE, Casimir
- [Educational Systems](https://claudlos.github.io/carlos-debrief/topics/education.html) — MOOCs, adaptive learning

Plus time-sorted feeds:

- [Research Feed](https://claudlos.github.io/carlos-debrief/research-feed.html) — every paper, newest first
- [News Feed](https://claudlos.github.io/carlos-debrief/news-feed.html) — every news item, newest first

## Schedule

**Two** debriefs per day, both auto-published:

| Time (CT) | Debrief |
| --- | --- |
| **07:00 AM** | Morning edition |
| **07:00 PM** | Evening edition |

Each run executes the scouts, generates `.md` and `.html` artifacts, updates the manifest, rebuilds the topic + feed pages, and pushes to this repo. GitHub Pages rebuilds within ~30 seconds.

## How it works

```
[ Hermes cron, 2x/day at 07:00 + 19:00 CT ]
        │
        ▼
┌──────────────────────────────────────────────┐
│ 0. Scouts (only run here, never separately)  │
│    - fetch_papers.py     (arXiv API)         │
│    - api_scout.py        (Lobste.rs + HF)    │
│    - web_scout.py        (camoufox: GS + HN) │
│    + github/reddit/semanticscholar/...       │
│    All dedup against seen_*.txt              │
└──────────────────────────────────────────────┘
        │  papers.jsonl + web_papers.jsonl
        ▼
┌──────────────────────────────────────────────┐
│ 1. build_debrief.py — deterministic build    │
│    Reads template.html for CSS / modal / JS  │
└──────────────────────────────────────────────┘
        │  debrief-YYYY-MM-DD-HH.{html,md}
        ▼
┌──────────────────────────────────────────────┐
│ 2. Deterministic post-processing             │
│    build_manifest.py    → manifest.json     │
│    build_index.py       → index.json         │
│    build_topic_pages.py → 9 topic + 2 feed   │
│    build_feed.py        → RSS feed.xml       │
└──────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────┐
│ 3. git add / commit / push origin main       │
└──────────────────────────────────────────────┘
        │
        ▼
   GitHub Pages rebuilds → live in ~30s
```

The scouts maintain `seen_arxiv_ids.txt` and `seen_web_keys.txt` so even after
the per-debrief queue files are cleared, the same paper will not surface in a
future debrief.

![Debrief page with topic chips and Quick Summary](assets/debrief.png)

## Repo layout

```
.
├── index.html                  # dashboard, surfaces topics + feeds + themes
├── topics/                     # 9 curated topic pages (built by build_topic_pages.py)
├── template.html               # canonical CSS / modal / search JS for all debriefs
├── research-feed.html          # every paper, newest first
├── news-feed.html              # every news item, newest first
├── top-500.html                # Hermes-judged ranking, scored out of 1000
├── assets/
│   ├── themes.css              # 3 themes (Default / Cyber / Monk) via :root tokens
│   └── theme-switcher.js       # widget + Alt+T cycling + localStorage persistence
├── scripts/                    # all deterministic, no LLM in the loop
│   ├── build_debrief.py
│   ├── build_manifest.py
│   ├── build_index.py
│   ├── build_topic_pages.py
│   ├── build_feed.py
│   ├── generate_top500.py
│   └── validate_site.py
├── manifest.json               # list of every debrief, newest first
├── index.json                  # shared data for search/topic/insights pages
├── debrief-YYYY-MM-DD-HH.html  # generated debrief pages
├── feed.xml                    # RSS feed
└── search.html / topics.html / insights.html  # browse + analyze views
```

The scout scripts and cron config live outside the repo (in the local Hermes
setup at `~/.hermes/cron/arxiv-scout/`) and aren't checked in.

## Reading a debrief

- Click anywhere on a card to zoom into the modal view.
- Use the search box at the top to filter cards by keyword (title, authors, tags, full abstract text).
- Click the paper title link to open the source on arXiv / Lobste.rs / wherever.
- Press `Alt+T` to cycle through themes.
- Press `/` to focus the search box from anywhere.
- `←` / `→` keys navigate between cards inside the modal.
- `Esc` closes the modal.

## Generating the Top 500 page

`scripts/generate_top500.py` parses every historical debrief card, asks Hermes
Agent to rate each unique paper/news item (scored out of 1000) with the
configured default LLM, and writes `top500.json` plus `top-500.html`.

```bash
python3 scripts/generate_top500.py --workers 6
```

The script uses `hermes -z` by default. Override the command with
`HERMES_COMMAND=...` if needed.

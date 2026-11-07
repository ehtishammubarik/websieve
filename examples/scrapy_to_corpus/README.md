# scrapy_to_corpus — Scrapy crawl to websieve corpus

An end-to-end worked example: a small Scrapy spider crawls a handful of local
static fixture pages, and the result is piped into `websieve build` to produce
a clean, deduplicated corpus. It is the promised real, runnable path behind the
one-line pipe in the top-level README.

## Why local fixtures

The spider crawls static pages served by Python's built-in HTTP server on
`localhost`, not a third-party site. That keeps the example offline, fast, and
free of any dependence on a remote site's structure, rate limits, or terms.
The fixture set is small and deliberately contains the kinds of pages a real
crawl produces: an index page, a real article, the same article under a
tracking URL, a nav dump, and SEO spam.

This is a **manual-only** example: it is not wired into CI because it runs a
local HTTP server and a Scrapy crawl. The commands below are exact and were
run to produce the numbers in this README.

## Setup

```bash
cd examples/scrapy_to_corpus
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 1. Serve the fixtures

```bash
python -m http.server 8000 --directory fixtures
```

Leave that running in its own terminal.

## 2. Crawl

From this directory (so `scrapy.cfg` resolves), crawl and write JSONL:

```bash
scrapy crawl sample -o crawl.jsonl -t jsonlines
```

The spider honours the project's crawl-ethics defaults: `ROBOTSTXT_OBEY`,
`AUTOTHROTTLE_ENABLED`, a 1s `DOWNLOAD_DELAY`, an honest `USER_AGENT` with a
contact address, and a low per-domain concurrency. See `.claude/skills/crawl-ethics/SKILL.md`
in the repo root.

## 3. Build the corpus

```bash
websieve build crawl.jsonl -o dataset/
```

## 4. Inspect what was dropped and why

```bash
cat dataset/stats.json | python3 -m json.tool
```

On the fixture set this produces a drop breakdown like:

```text
seen        5
kept        2  (40.0%)
dropped     3
  exact duplicate  1
  quality          2
```

What happens to each of the five fixture pages:

- `index.html` — kept. A real page with a heading and a paragraph.
- `article-a.html` — kept. The real article.
- `article-b.html` — dropped as an **exact duplicate**. Its body is the same
  article as `article-a.html`; extraction strips the surrounding nav/footer, so
  the two normalize to identical text. This is the same duplicate the quickstart
  shows for tracking-parameter URLs.
- `nav.html` — dropped on quality (`word_count` / `terminal_punctuation_ratio`).
  It is nothing but links.
- `spam.html` — dropped on quality (`repetition_ratio`). One line repeated.

This is the whole point of `websieve`: every drop is attributable to a rule, and
the counts reconcile (`seen == kept + dropped`).

## Files

| Path | Role |
|---|---|
| `scrapy_to_corpus/spiders/sample_spider.py` | The spider: starts at `index.html`, follows same-host `.html` links, yields `{"url", "html"}` records |
| `scrapy_to_corpus/settings.py` | Crawl-ethics settings (robots, throttle, honest UA) |
| `scrapy_to_corpus/scrapy.cfg` | Scrapy project config (resolved from this directory) |
| `fixtures/` | Static pages served locally |
| `requirements.txt` | Scrapy and websieve for this example |

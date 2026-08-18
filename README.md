# websieve

**Turn a web crawl into an ML-ready dataset.** Extract, filter, deduplicate, embed, shard.

[![CI](https://github.com/ehtishammubarik/websieve/actions/workflows/ci.yml/badge.svg)](https://github.com/ehtishammubarik/websieve/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
![Dependencies](https://img.shields.io/badge/core%20dependencies-none-success)
![Coverage](https://img.shields.io/badge/coverage-92%25-success)
![License](https://img.shields.io/badge/license-MIT-blue)

## What this actually is

You scraped 50,000 pages. You cannot train on them, because a scraped page is not a document.

**In:** raw HTML, one JSON object per line.

```json
{"url": "https://example.com/gpu-guide",
 "html": "<html><head><title>GPU scheduling on Kubernetes</title></head><body><nav><a href='/'>Home</a><a href='/about'>About</a></nav><article><h1>GPU scheduling</h1><p>Kubernetes exposes GPUs through the NVIDIA device plugin, which advertises nvidia.com/gpu as an allocatable resource on every node...</p></article><footer>&copy; 2026 Example Inc. Privacy Policy</footer></body></html>"}
```

**Out:** clean text, deduplicated, quality-scored, in gzipped shards a dataloader can stream.

```json
{"doc_id": "dc1bf1ffa1945c31",
 "url": "https://example.com/gpu-guide",
 "title": "GPU scheduling on Kubernetes",
 "text": "GPU scheduling\n\nKubernetes exposes GPUs through the NVIDIA device plugin, which advertises...",
 "quality": {"passed": true, "rules": {"word_count": {"passed": true, "value": 104, "threshold": 50}}},
 "signatures": {"raw": "81879111...", "normalized": "0745f9c2...", "structural": "a74bccb9..."}}
```

The nav, the footer, and the copyright line are gone. The title came from `<title>`, the body from
the article, and nothing else survived. Across a real crawl, so do the 9,884 pages that were the
same article under a different URL and the 14,022 that were link farms, stub pages, or SEO spam.

Both blocks above are actual output, not illustration. `docs/quickstart.md` reproduces them in
about a minute.

**That gap is the whole product.** Crawling is solved; Scrapy does it. Training is solved; your
framework does it. The part in between, where a crawl becomes a corpus, is where people quietly lose
weeks and then train on duplicates anyway.

## Who this is for

- **You are building an LLM or RAG corpus** from crawled pages and need dedup that catches near
  duplicates, not just byte-identical ones.
- **You run a scraper in production** and want the cleaning stage to be a library with tests rather
  than a 400-line `clean.py` nobody wants to touch.
- **You cannot install dependencies** where the cleaning has to run: someone else's container, a
  locked-down build box, an air-gapped environment.

If you want a distributed, Spark-scale pipeline with a cluster behind it, use HuggingFace's
`datatrove`. `websieve` deliberately runs in one process with no dependencies, which is the right
trade below roughly ten million documents and the wrong one above it.

## How it works

```
crawl -> extract -> normalize -> exact dedup -> quality -> near dedup -> embed -> shards
         boilerplate  NFKC       3 levels       9 rules    MinHash+LSH   batched
```

Each stage costs more than the one before it, so each shrinks the input to the next. One hash beats
nine heuristics; nine heuristics beat 128 hash permutations. Details in
[`docs/architecture.md`](docs/architecture.md).

**The core has no dependencies.** Not "few". None. `pyarrow`, `torch`, and `scrapy` are optional
extras used only by the stages that genuinely need them, and CI fails if a third-party import ever
reaches the core.

## Install

```bash
pip install websieve                # core, zero dependencies
pip install "websieve[parquet]"     # + Parquet output
pip install "websieve[embed]"       # + GPU embedding
pip install "websieve[all]"
```

## Use

Pipe a crawl straight in:

```bash
scrapy crawl myspider -o - -t jsonlines | websieve build - -o dataset/
```

Or run against a file:

```bash
websieve build crawl.jsonl -o dataset/ --threshold 0.85 --shard-size 50000
```

You get sharded output, a manifest, and a stats report:

```
dataset/
  shard-00000.jsonl.gz
  shard-00001.jsonl.gz
  manifest.json     every shard, its record count, its size
  stats.json        what was dropped, and by which rule
```

```
seen        50000
kept        18342  (36.7%)
dropped     31658
  empty              412
  exact duplicate   9884
  quality          14022
  near duplicate    7340
quality rule failures (a document can fail several):
  word_count                   8110
  terminal_punctuation_ratio   6033
  repetition_ratio             2914
```

That breakdown is the point. A filter you cannot attribute is a filter you cannot tune.

### Inspect before you commit

```bash
websieve assess crawl.jsonl -v                  # what would be dropped, and why. Drops nothing.
websieve assess crawl.jsonl --sample 1000      # same, on a sample, for large crawls
websieve dedup  crawl.jsonl         # duplicate clusters with similarity scores
websieve extract page.html          # main-content text from one page
```

### As a library

```python
from websieve.pipeline import Pipeline, PipelineConfig
from websieve.models import Document

pipeline = Pipeline(PipelineConfig(near_dup_threshold=0.85))
for doc in pipeline.process(Document(url=u, html=h) for u, h in crawl()):
    index(doc.text)

print(pipeline.stats.render())
```

Every stage also stands alone:

```python
from websieve.quality.heuristics import assess
from websieve.dedup.minhash import MinHash, LSHIndex
from websieve.clean.boilerplate import extract
```

## What each stage does

### Extraction

Text-density heuristic, not a readability port. Blocks are scored by length and link density, then
the best contiguous run is kept, so navigation and footers fall away because they are short and
mostly links. Headings adjacent to the body are reclaimed, because Kadane's algorithm will not pick
them up on its own and an article without its title is a worse document.

No dependencies. If you can afford one and need higher accuracy, use `trafilatura` and feed its
output into the quality stage instead.

### Quality

Nine rules from the published recipes for large web corpora, chiefly the Gopher rules
(Rae et al., 2021) and the C4 cleanup (Raffel et al., 2020): word count, mean word length, symbol
ratio, alphabetic ratio, bullet and ellipsis line ratios, terminal punctuation, line repetition, and
boilerplate markers.

Reimplemented rather than vendored so every threshold is visible and adjustable. The right values
genuinely differ between general web text and a domain corpus, and you cannot tune what you cannot
see. **Every rule runs even after one fails**, so the failure histogram is complete.

**The rule set adapts to the writing system.** Every one of those rules was derived from English and
assumes words are separated by spaces, so applied unchanged they reject ordinary Chinese, Japanese,
Thai, and Korean outright. Script is detected per document, and the rules are composed from its
traits: not space-delimited means character-based length rules, no terminal punctuation means that
rule is dropped, dense characters mean a lower word-length floor. Verified against twelve writing
systems.

### Deduplication

Two passes, cheap before expensive.

**Exact**, at three levels. `raw` is byte-identical. `normalized` ignores case, punctuation, and
spacing. `structural` also collapses digits, which catches templated pages differing only by a
price, date, or id. That last one will merge genuinely different pages whose only distinguishing
content is numeric, so choose it deliberately.

**Near**, by MinHash with LSH banding. Shingle into word n-grams, keep the minimum under `num_perm`
hash permutations, then band the signature so candidate lookup is a hash hit instead of an O(n^2)
scan. Candidates are verified against real signature similarity afterwards, because LSH returns
candidates, not answers.

Permutations are simulated as `(a*h + b) mod p` over a Mersenne prime, the standard universal
hashing construction, which is why this needs no numpy. Accuracy is what the theory predicts:

| Pair | True Jaccard | MinHash estimate, 256 perms |
| :--- | ---: | ---: |
| One word differs | 0.833 | 0.863 |
| Unrelated documents | 0.000 | 0.000 |
| Identical | 1.000 | 1.000 |

### Embedding

The model call sits behind a `Protocol`, so the part that actually governs throughput is testable
without a GPU and CI exercises it with a stub.

Two things dominate embedding throughput, and neither is the model:

- **Padding waste.** A batch is as slow as its longest sequence. Sorting by length before batching
  keeps short documents from being padded up to the longest one in the corpus.
- **Batch size versus memory.** `adaptive_batches` caps on `max_len * batch_size` rather than record
  count, so a batch of long documents automatically becomes a smaller batch.

`padding_efficiency()` reports how much of what you processed was real rather than padding. Below
about 0.7, the length distribution is too spread out for the current batch size.

Worth knowing: sorting helps when batch size is the binding constraint. When the token cap binds
first, both orderings produce identical batches and sorting buys nothing. Both regimes are asserted
in the tests rather than assumed.

### Output

Sharded JSONL (gzip) or Parquet. Many medium shards rather than one large file, because shards
parallelize across dataloader workers, resume cleanly after a failure, and stream from object
storage without a full download.

Both writers emit `manifest.json`. `read_shards()` reads it rather than globbing the directory, so
a truncated or partially uploaded dataset raises an error instead of silently yielding fewer records
than you think you have.

## Tuning

| Symptom | Change |
| :--- | :--- |
| Keeping too much junk | Lower `--threshold` toward 0.7; raise the `word_count` minimum |
| Dropping good documents | Raise `--threshold`; check `stats.json` for the dominant rule |
| Dedup too slow | Lower `--num-perm` to 64 |
| Missing obvious duplicates | Raise `--bands` for higher recall and more candidates to verify |
| Templated pages surviving | `--exact-level structural` |
| Low padding efficiency | Lower `max_batch_tokens`, keep `sort_by_length=True` |

`PipelineConfig` exposes all of it. See [`docs/tuning.md`](docs/tuning.md) and
[`docs/architecture.md`](docs/architecture.md).

## Testing

```bash
pip install -e ".[dev]"
pytest
```

112 tests, 92 percent line coverage, no network access and no GPU required. The uncovered remainder
is `ParquetShardWriter` and `SentenceTransformerEncoder`, which need `pyarrow` and `torch` and are
not installed in CI. They are thin call-throughs; the logic they sit behind is covered.

CI runs on Python 3.10, 3.11, and 3.12, and includes a job that **fails if the core ever acquires a
runtime dependency**.

## Documentation

| Guide | For |
| :--- | :--- |
| [Quickstart](docs/quickstart.md) | Five minutes, no crawler needed. Real input and real output |
| [Architecture](docs/architecture.md) | Why the stages are ordered this way, memory ceiling, limitations |
| [Tuning](docs/tuning.md) | Calibrating thresholds against your own corpus |
| [Extending](docs/extending.md) | Swapping the extractor, model, writer, or similarity metric |
| [Roadmap](ROADMAP.md) | What is next, and what is deliberately not planned |
| [Changelog](CHANGELOG.md) | What changed in each release |
| [Contributing](CONTRIBUTING.md) | Setup, the rules specific to this codebase |

## Contact

Issues and PRs welcome. If an issue is not the right shape, or for commercial
use and private corpora, email
[contact@eprecisio.com](mailto:contact@eprecisio.com).

Maintained by [Ehtisham Mubarik](https://github.com/ehtishammubarik)
([LinkedIn](https://www.linkedin.com/in/ehtisham-mubarik)) at
[Eprecisio Technologies](https://eprecisio.com).

## Origin

This repository began as a containerized Scrapy deployment (Scrapy, Scrapyd, Postgres, Filebeat,
Jenkins) built for a Swiss real-estate crawl. That crawler is still here under `immo_crawl/` as a
working integration example. `websieve` is the part that was missing: everything between a finished
crawl and a dataset you would actually train on.

## License

MIT. See [LICENSE](LICENSE).

---

If `websieve` saved you an afternoon, a star helps the next person find it.
Contributions welcome: [`good first issue`](https://github.com/ehtishammubarik/websieve/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
is pre-scoped, and [CONTRIBUTING.md](CONTRIBUTING.md) says how to claim one so
two people do not build it twice.

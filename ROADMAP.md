# Roadmap

Honest about status: `websieve` is early. The core pipeline works and is tested,
but it has not been run against a corpus of tens of millions of documents by
anyone other than the author. Treat version numbers accordingly.

Each section below maps to a GitHub milestone, so this file and the issue
tracker cannot drift apart without one of them being visibly wrong.

- [**0.2 — usable on a real corpus**](https://github.com/ehtishammubarik/websieve/milestone/1)
- [**0.3 — scale and breadth**](https://github.com/ehtishammubarik/websieve/milestone/2)

## Vision

**A crawl becomes a corpus in one process, on any machine, with every decision
attributable.**

Three commitments follow from that, and they are the reason to pick this over
something bigger.

**You can always answer "why is this document not in my dataset?"** Every drop
is attributed to a rule, every rule reports the observed value and the threshold
it failed, and every count reconciles: `seen == kept + dropped + malformed`. A
filter you cannot attribute is a filter you cannot tune, and a pipeline that
loses documents silently is one you will eventually stop trusting for reasons
you cannot articulate.

**It runs where the work is.** The core imports stdlib only, so it runs inside
someone else's container, on a locked-down build box, or in an air-gapped
environment where `pip install` is not an option. That constraint is permanent
and CI enforces it. It costs real capability, and it is the reason this is
usable in the places a heavier tool is not.

**The defaults come from published work, and stay visible.** The quality rules
are the Gopher and C4 heuristics, reimplemented rather than vendored so every
threshold can be read and changed. The right values genuinely differ between
general web text and a domain corpus.

**Where it stops.** Memory, not elapsed time, is the binding constraint for the
in-process dedup indexes. The [reproducible benchmark](docs/benchmarks.md)
measured linear growth of about 10.8 MiB per 1,000 input documents on its
controlled corpus, enough to fill a 16 GiB machine at roughly 1.5 million
documents. The exact wall depends on the corpus and settings; past it, the
honest answer is sharding or HuggingFace's `datatrove`. Growing into a
distributed system would mean losing the property that makes this worth having.

## Now (0.1.x)

Shipped, tested, and on PyPI.

| Capability | |
| :--- | :--- |
| Boilerplate extraction, Unicode normalization | text-density heuristic, no dependencies |
| Nine Gopher and C4 quality heuristics | per-rule attribution, every rule runs even after one fails |
| **Writing-system-aware quality rules** | script detected per document; verified against twelve writing systems ([#19]) |
| Exact dedup at three levels, MinHash and LSH near-dedup | candidates verified, never trusted |
| Adaptive batching for embedding | oversized documents get their own batch rather than being dropped |
| Sharded JSONL and Parquet output | verifiable manifests |
| `build`, `assess`, `dedup`, `extract` | plus `assess --sample N` for calibration ([#10]) |
| **Malformed lines counted, not lost** | `seen == kept + dropped + malformed` closes ([#27]) |
| **`--strict` and `--max-malformed N`** | opt-in exit codes; the default still counts and continues ([#31]) |
| **`--version` and `websieve.__version__`** | recorded into `manifest.json` and `stats.json` ([#32]) |
| **Non-object JSON lines warned, not fatal** | `[1,2,3]`, `"x"`, `42`, `true`, `null` ([#33]) |
| **Fragmented short-body extraction** | dominant sidebars no longer suppress runs of short semantic paragraphs ([#39]) |
| **Reproducible performance benchmark** | stage throughput, dedup accuracy, and peak RSS with pinned input and machine-readable results ([#38]) |
| **Live build progress** | stderr-only seen, kept, keep-rate, and throughput counters for unknown-length streams ([#40]) |

## Next (0.2)

[Milestone](https://github.com/ehtishammubarik/websieve/milestone/1). The gaps
that most affect whether this survives contact with production work.

| Item | Why it matters |
| :--- | :--- |
| [Resumable runs](https://github.com/ehtishammubarik/websieve/issues/2) | A crash 8 hours into a 12-hour job currently means starting over |
| [Persistent dedup index](https://github.com/ehtishammubarik/websieve/issues/5) | Deduplicate a second crawl against the first instead of re-reading both |
| [Release pipeline does not test the artifact](https://github.com/ehtishammubarik/websieve/issues/11) | It tests the source tree, so a packaging break ships |
| [`websieve report`](https://github.com/ehtishammubarik/websieve/issues/12) | An HTML corpus report you can hand to someone who will not read `stats.json` |
| [Dataset card](https://github.com/ehtishammubarik/websieve/issues/13) | Publishing a dataset without one is how provenance gets lost |
| [Official Docker image](https://github.com/ehtishammubarik/websieve/issues/14) | Trying it should take 30 seconds |
| [Worked example end to end](https://github.com/ehtishammubarik/websieve/issues/9) | Crawler to corpus, with real numbers |

## Later (0.3+)

[Milestone](https://github.com/ehtishammubarik/websieve/milestone/2). Bigger,
and none of it blocks 0.2.

| Item | Note |
| :--- | :--- |
| [Parallel processing](https://github.com/ehtishammubarik/websieve/issues/15) | Multiprocessing over shards. Dedup is the hard part, because the index is shared state; likely partition by URL host |
| [PII detection](https://github.com/ehtishammubarik/websieve/issues/16) | Absent today, and its absence is a compliance trap for anyone publishing a dataset. An optional extra, and never implied without one |
| [Quality classifier](https://github.com/ehtishammubarik/websieve/issues/22) | An optional learned filter alongside the heuristics, in the style of the FineWeb educational classifier |
| [Chunking for RAG](https://github.com/ehtishammubarik/websieve/issues/20) | Split at semantic boundaries rather than character counts |
| [Near-duplicate detection across chunks](https://github.com/ehtishammubarik/websieve/issues/21) | Not just whole documents |
| [Streaming from S3 and GCS](https://github.com/ehtishammubarik/websieve/issues/7) | Read a crawl without staging it locally |
| [HuggingFace Hub publishing](https://github.com/ehtishammubarik/websieve/issues/17) | Straight from `build` |
| [`websieve doctor`](https://github.com/ehtishammubarik/websieve/issues/18) | Recommend thresholds instead of making people guess |

## Not planned

Saying no is part of a roadmap.

- **A crawler.** Scrapy exists and is good. `websieve` starts where it ends.
- **Distributed execution.** If you need a cluster, use HuggingFace's
  `datatrove`. Running in one process with no dependencies is the point here,
  and the [benchmark](docs/benchmarks.md) makes its throughput and memory wall
  measurable on representative input.
- **A plugin system.** Composition and subclassing already cover the real cases.
  See [`docs/extending.md`](docs/extending.md).
- **Dependencies in the core.** Permanent. CI enforces it.
- **Legal guarantees.** This filters for corpus *quality*, not legal
  *permissibility*. No licence detection, and no PII removal unless you install
  the extra that provides it.

## How this file stays true

It went stale once: language detection and `--sample` sat under **Next** for
weeks after they shipped, including the item labelled "the biggest correctness
gap" ([#34]). Someone deciding whether to adopt this read a solved problem as a
live limitation.

So: **a PR that closes a roadmap item moves its row into Now, in the same PR.**
Not afterwards. The row names the PR that delivered it, which is what makes the
claim checkable rather than assertable. Reviewers, this is fair game to block on.

## Influencing this list

The order is a guess, and a real use case beats a guess.

- **Open an issue** describing what you are building and where this got in the
  way. Concrete beats abstract: corpus size, document type, and what broke.
- **Email** [contact@eprecisio.com](mailto:contact@eprecisio.com) if an issue is
  not the right shape, for instance commercial use or a private corpus.
- **LinkedIn:** [Ehtisham Mubarik](https://www.linkedin.com/in/ehtisham-mubarik)
  or [Eprecisio Technologies](https://www.linkedin.com/company/eprecisio/)

Issues labelled [`good first issue`](https://github.com/ehtishammubarik/websieve/labels/good%20first%20issue)
are scoped so a first contribution does not require reading the whole codebase.
[`help wanted`](https://github.com/ehtishammubarik/websieve/labels/help%20wanted)
marks items I would genuinely rather not do alone.
[`CONTRIBUTING.md`](CONTRIBUTING.md) says how to claim one so two people do not
build it twice.

[#10]: https://github.com/ehtishammubarik/websieve/pull/10
[#19]: https://github.com/ehtishammubarik/websieve/pull/19
[#27]: https://github.com/ehtishammubarik/websieve/pull/27
[#31]: https://github.com/ehtishammubarik/websieve/pull/31
[#32]: https://github.com/ehtishammubarik/websieve/pull/32
[#33]: https://github.com/ehtishammubarik/websieve/pull/33
[#34]: https://github.com/ehtishammubarik/websieve/issues/34
[#38]: https://github.com/ehtishammubarik/websieve/pull/38
[#39]: https://github.com/ehtishammubarik/websieve/pull/39
[#40]: https://github.com/ehtishammubarik/websieve/pull/40

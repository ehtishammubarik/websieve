# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] - 2026-08-30

Eleven changes since 0.1.1. The theme is the arithmetic closing: a line that
fails to parse is now counted rather than vanishing, and a run can be told to
fail on that rather than quietly training on a partial corpus.

### Added

- **Live progress while `build` runs** ([#3], [#40]). `build` was silent until it
  finished, which on an hours-long corpus is indistinguishable from a hang.
  Seen, kept, keep-rate and throughput are now throttled to stderr, and the
  library exposes the same counters through a callback so an embedding caller
  can render its own. Malformed milestones are counted without needing a known
  stream length.
- **`--strict` and `--max-malformed N`** ([#23], [#31]). The malformed counter
  added in [#27] counted but never failed. `--strict` exits non-zero if any input
  line failed to parse; `--max-malformed N` tolerates a few and fails on a flood.
  Both are opt-in and the default still counts and continues.
- **`--version`, `websieve.__version__`, and version stamping in output**
  ([#24], [#32]). The installed version is now discoverable, and it is recorded in
  `manifest.json` and `stats.json` so a dataset says which build produced it.
  Contributed by @gandzekas.
- **A reproducible benchmark** ([#6], [#38]). Throughput and memory claims were
  previously unmeasured. There is now a checksum-pinned Common Crawl benchmark
  reporting per-stage speed, dedup precision and recall, and peak RSS from a
  fresh process. This is where the roughly 10.8 MiB per 1,000 documents figure
  in the ROADMAP comes from.

### Fixed

- **A valid JSON line that is not an object no longer kills the run** ([#28],
  [#33]). `[1,2,3]`, `"x"`, `42`, `true` and `null` are all valid JSON and none is
  a record. `Document.from_dict` assumed a dict, so each raised `AttributeError`
  from inside a comprehension, which `_read_docs` did not catch: one bad line
  from a writer hiccup killed an hours-long `build`, `assess` or `dedup`. Guarded
  with `isinstance` rather than by widening the `except`, so correctness does not
  depend on which exception `from_dict` happens to raise today. They are warned,
  skipped, and counted as malformed.
- **Malformed lines are counted, so the totals close** ([#23], [#27]). A line that
  failed to parse was warned about and then vanished: not in `seen`, not in any
  drop bucket, not in `stats.json`. The artifact reported a clean corpus while
  quietly missing records, which made truncation undetectable. `malformed` is now
  a peer of `dropped`, and `seen == kept + dropped + malformed` holds.
- **Quality rules adapt to the writing system** ([#1], [#19]). Every heuristic was
  derived from English and assumed words are separated by spaces, so ordinary
  Chinese, Japanese, Thai and Korean text was rejected outright with no
  indication why. Script detection over codepoint ranges, stdlib only.
- **Extraction no longer loses content on pages of many short blocks** ([#8],
  [#39]). A single high-scoring block is capped while computing the centering
  mean only, so short linked paragraphs stay eligible without weakening the
  link-density penalty or shrinking genuine long-block scores.

### Changed

- **The Scrapy example moved out of the repository root** ([#35], [#37]). A
  `setup.py` declaring a package named `project` and a `requirements.txt` pinning
  Scrapy and psycopg2 sat beside the `pyproject.toml` of a package whose headline
  claim is zero runtime dependencies, with nothing saying they belonged to the
  example. All of it now lives under `examples/immo_crawl/` with a README. The
  example itself is unchanged and still works.

### Documentation

- **ROADMAP rebuilt from what actually merged, and a Vision section added**
  ([#34], [#36]). The roadmap promised two things that had already shipped, one of
  them labelled the biggest correctness gap. Every row now names the PR that
  delivered it, each section points at its GitHub milestone, and a stated rule
  keeps them from drifting again.
- **CONTRIBUTING now tells you to claim an issue before building it** ([#29],
  [#30]). Two people built `--version` four hours apart and one had their work
  closed. Also documents that GitHub holds first-time-contributor workflows at
  `action_required`, so "no checks reported" is not a pass.

### Note on this release

0.2.0 is deliberately not this release. The 0.2 milestone means usable on a real
corpus and seven of its items are still open, so numbering this 0.2.0 would make
the ROADMAP false. See the [0.2 milestone](https://github.com/ehtishammubarik/websieve/milestone/1).

[#1]: https://github.com/ehtishammubarik/websieve/issues/1
[#3]: https://github.com/ehtishammubarik/websieve/issues/3
[#6]: https://github.com/ehtishammubarik/websieve/issues/6
[#8]: https://github.com/ehtishammubarik/websieve/issues/8
[#19]: https://github.com/ehtishammubarik/websieve/pull/19
[#23]: https://github.com/ehtishammubarik/websieve/issues/23
[#24]: https://github.com/ehtishammubarik/websieve/issues/24
[#27]: https://github.com/ehtishammubarik/websieve/pull/27
[#28]: https://github.com/ehtishammubarik/websieve/issues/28
[#29]: https://github.com/ehtishammubarik/websieve/issues/29
[#30]: https://github.com/ehtishammubarik/websieve/pull/30
[#31]: https://github.com/ehtishammubarik/websieve/pull/31
[#32]: https://github.com/ehtishammubarik/websieve/pull/32
[#33]: https://github.com/ehtishammubarik/websieve/pull/33
[#34]: https://github.com/ehtishammubarik/websieve/issues/34
[#35]: https://github.com/ehtishammubarik/websieve/issues/35
[#36]: https://github.com/ehtishammubarik/websieve/pull/36
[#37]: https://github.com/ehtishammubarik/websieve/pull/37
[#38]: https://github.com/ehtishammubarik/websieve/pull/38
[#39]: https://github.com/ehtishammubarik/websieve/pull/39
[#40]: https://github.com/ehtishammubarik/websieve/pull/40

## [0.1.1] - 2026-07-28

### Added

- `websieve assess --sample N` reads the whole input stream but evaluates a
  reservoir sample of N documents, so calibrating thresholds against a large
  crawl no longer requires a full pass. Output is marked `(sampled from
  stream)` so a sampled count cannot be mistaken for a total.
  Contributed by [@pollychen-lab](https://github.com/pollychen-lab) in
  [#10](https://github.com/ehtishammubarik/websieve/pull/10), closing
  [#4](https://github.com/ehtishammubarik/websieve/issues/4).
- `--seed` for `--sample`, defaulting to a fixed value so repeated runs are
  reproducible by default. Without it, identical invocations varied by 11
  points on a fixed corpus, which would have made the measure-change-measure
  workflow in `docs/tuning.md` report sampling noise as a real effect.

### Fixed

- `assess` and `dedup` now extract HTML before judging the text. Both read
  `Document.text` directly, which is empty for HTML-only input until extraction
  runs, so `assess` reported that every document failed `word_count` while
  `build` on the same file kept them. Two commands disagreeing about the same
  corpus is worse than either being wrong alone.

### Changed

- Release pipeline now tests the built artifact rather than only the source
  tree. The wheel and sdist are each installed into a clean environment, the
  source tree is deleted so a local import is impossible, and the suite runs
  against the installed package. Publishing goes to TestPyPI first and is
  verified there before PyPI, because PyPI versions can never be reused.
- `.github/scripts/verify_artifact.py` inspects wheel and sdist contents
  directly: no tests or keys packaged, no credential-shaped strings, zero
  runtime dependencies read from wheel metadata, and every source module
  present in the wheel.
- `scripts/verify-published.sh` verifies a published release in Docker on stock
  `python:3.x-slim` images, testing what `pip install websieve` actually
  delivers rather than an artifact CI just built.

## [0.1.0] - 2026-07-28

Initial release under the `websieve` name.

Crawl-to-dataset pipeline: boilerplate extraction, Unicode normalization, nine
Gopher and C4 quality heuristics with per-rule attribution, exact and MinHash
near-duplicate detection, GPU-aware adaptive batching, and sharded output with
verifiable manifests. The core has no runtime dependencies, enforced by CI.

[0.1.1]: https://github.com/ehtishammubarik/websieve/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ehtishammubarik/websieve/releases/tag/v0.1.0

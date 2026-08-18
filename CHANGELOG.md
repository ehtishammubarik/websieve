# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `websieve build --strict` exits non-zero if any input line failed to parse,
  for pipelines that would rather stop than quietly train on a partial corpus.
  `--max-malformed N` is the middle setting: tolerate a few bad lines, fail on
  a flood. Both are opt-in; the default still counts and continues, as added in
  [#27](https://github.com/ehtishammubarik/websieve/pull/27). Closes
  [#23](https://github.com/ehtishammubarik/websieve/issues/23).

### Fixed

- **A JSON line that is valid but is not an object no longer crashes the run**
  ([#28](https://github.com/ehtishammubarik/websieve/issues/28)). `[1,2,3]`,
  `"x"`, `42`, `true`, and `null` all parse cleanly and none is a record.
  `Document.from_dict` assumed a dict, so each raised `AttributeError` from
  inside a comprehension, which `_read_docs` did not catch: one bad line from a
  writer hiccup killed an hours-long `build`, `assess`, or `dedup`. They are now
  warned, skipped, and counted as `malformed`, so the arithmetic still closes
  and `--strict` still catches them. `from_dict` raises a `TypeError` naming
  what it received rather than an `AttributeError` naming its own internals.

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

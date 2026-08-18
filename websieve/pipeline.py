"""Pipeline orchestration.

Stage order is not arbitrary. Each stage is more expensive than the one before,
so each exists partly to reduce the input to the next:

    extract -> normalize -> exact dedup -> quality -> near dedup -> embed

Exact dedup before quality because hashing is cheaper than nine heuristics.
Quality before near-dedup because MinHash signatures cost far more than the
heuristics and there is no point signing a document you are about to drop.
Embedding last because it is orders of magnitude more expensive than all of it.

Every stage records why it dropped a document. ``PipelineStats`` is the output
you actually look at when tuning, and the reason the stages do not short
circuit silently.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .clean.boilerplate import extract
from .clean.normalize import normalize
from .dedup.exact import ExactDeduper, signatures
from .dedup.minhash import LSHIndex, MinHash
from .models import Document
from .quality.heuristics import assess


@dataclass
class PipelineStats:
    """Counters for one pipeline run."""

    seen: int = 0
    kept: int = 0
    dropped_empty: int = 0
    dropped_exact_dup: int = 0
    dropped_quality: int = 0
    dropped_near_dup: int = 0
    malformed: int = 0
    quality_failures: dict[str, int] = field(default_factory=dict)

    @property
    def dropped(self) -> int:
        return (
            self.dropped_empty
            + self.dropped_exact_dup
            + self.dropped_quality
            + self.dropped_near_dup
        )

    @property
    def keep_rate(self) -> float:
        return self.kept / self.seen if self.seen else 0.0

    def to_dict(self) -> dict:
        return {
            "seen": self.seen,
            "kept": self.kept,
            "dropped": self.dropped,
            "malformed": self.malformed,
            "keep_rate": round(self.keep_rate, 4),
            "dropped_by_stage": {
                "empty": self.dropped_empty,
                "exact_duplicate": self.dropped_exact_dup,
                "quality": self.dropped_quality,
                "near_duplicate": self.dropped_near_dup,
            },
            "quality_failures": dict(sorted(self.quality_failures.items(), key=lambda kv: -kv[1])),
        }

    def render(self) -> str:
        lines = [
            f"seen        {self.seen}",
            f"kept        {self.kept}  ({self.keep_rate:.1%})",
            f"dropped     {self.dropped}",
            f"malformed   {self.malformed}",
            f"  empty            {self.dropped_empty}",
            f"  exact duplicate  {self.dropped_exact_dup}",
            f"  quality          {self.dropped_quality}",
            f"  near duplicate   {self.dropped_near_dup}",
        ]
        if self.quality_failures:
            lines.append("quality rule failures (a document can fail several):")
            for name, n in sorted(self.quality_failures.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {name:28} {n}")
        return "\n".join(lines)


@dataclass
class PipelineConfig:
    """Tunables. Defaults are reasonable for general web text."""

    exact_level: str = "normalized"
    near_dup_threshold: float = 0.80
    num_perm: int = 128
    bands: int = 32
    ngram: int = 5
    min_block_chars: int = 25
    unicode_form: str = "NFKC"
    run_quality: bool = True
    run_near_dedup: bool = True
    adapt_to_script: bool = True


def prepare(doc: Document, config: PipelineConfig | None = None) -> Document:
    """Extract text from HTML and normalize it, in place.

    Everything downstream, in the pipeline and in the CLI alike, must go through
    this. The `assess` command originally inspected `doc.text` directly, which
    is empty for HTML-only input, so it reported that every document failed
    `word_count` while `build` on the same file kept them. Two commands
    disagreeing about the same corpus is worse than either being wrong.
    """
    cfg = config or PipelineConfig()
    if doc.html and not doc.text:
        text, title = extract(doc.html, min_block_chars=cfg.min_block_chars)
        doc.text = text
        doc.title = doc.title or title
    doc.text = normalize(doc.text, form=cfg.unicode_form)
    doc.html = None
    return doc


class Pipeline:
    """Streaming crawl-to-dataset pipeline.

    Single pass and generator based: memory grows with the number of *kept*
    documents (the dedup index), not with the size of the crawl.
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        self.stats = PipelineStats()
        self._exact = ExactDeduper(self.config.exact_level)
        self._hasher = MinHash(num_perm=self.config.num_perm)
        self._lsh = LSHIndex(num_perm=self.config.num_perm, bands=self.config.bands)

    def process(self, docs: Iterable[Document]) -> Iterator[Document]:
        """Run every document through the pipeline, yielding survivors."""
        cfg = self.config
        for doc in docs:
            # `seen` is also incremented in the CLI read layer for malformed
            # lines (cli._read_docs); only successfully-parsed Documents reach
            # here, so there is no double-count.
            self.stats.seen += 1

            prepare(doc, cfg)
            doc.crawled_at = doc.crawled_at or datetime.now(timezone.utc).isoformat()

            if not doc.text:
                self.stats.dropped_empty += 1
                continue

            is_dup, _first = self._exact.check(doc.doc_id, doc.text)
            if is_dup:
                self.stats.dropped_exact_dup += 1
                continue
            doc.signatures = signatures(doc.text)

            if cfg.run_quality:
                report = assess(doc.text, adapt_to_script=cfg.adapt_to_script)
                doc.quality = report.to_dict()
                if report.script is not None:
                    # Document.language existed from the start and was never
                    # populated. It holds the detected script rather than a
                    # language: distinguishing Mandarin from Cantonese needs a
                    # model, and the thresholds depend on the writing system.
                    doc.language = report.script.script
                if not report.passed:
                    self.stats.dropped_quality += 1
                    for name in report.failures:
                        self.stats.quality_failures[name] = (
                            self.stats.quality_failures.get(name, 0) + 1
                        )
                    continue

            if cfg.run_near_dedup:
                sig = self._hasher.signature(doc.text, n=cfg.ngram)
                matches = self._lsh.duplicates(sig, cfg.near_dup_threshold)
                if matches:
                    self.stats.dropped_near_dup += 1
                    continue
                self._lsh.add(doc.doc_id, sig)

            self.stats.kept += 1
            yield doc

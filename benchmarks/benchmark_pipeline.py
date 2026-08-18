#!/usr/bin/env python3
"""Reproducible throughput, dedup-quality, and peak-RSS benchmark.

The default input is a tiny WET sample from Common Crawl's official
``whirlwind-python`` repository, pinned by commit and SHA-256. The sample is
expanded deterministically so scaling runs exercise the in-process indexes
without downloading or redistributing a large crawl.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from websieve.clean.boilerplate import extract
from websieve.clean.normalize import normalize
from websieve.dedup.exact import normalized_hash
from websieve.dedup.minhash import MinHash, deduplicate, shingles
from websieve.models import Document
from websieve.pipeline import Pipeline, PipelineConfig
from websieve.quality.heuristics import assess

SAMPLE_COMMIT = "57209f8dce576e1aaf215f71a983eeba794f781b"
SAMPLE_URL = (
    "https://raw.githubusercontent.com/commoncrawl/whirlwind-python/"
    f"{SAMPLE_COMMIT}/whirlwind.warc.wet"
)
SAMPLE_SHA256 = "20dc2c125edb83b10e3b0f16356d0c00420725b21b59d6c2f95d3316ba129771"
SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    """One deterministic benchmark document and its duplicate-family truth."""

    key: str
    text: str
    family: str
    expected_duplicate: bool

    @property
    def html(self) -> str:
        return f"<html><body><article><p>{self.text}</p></article></body></html>"


def _headers(block: bytes) -> dict[str, str]:
    lines = block.decode("utf-8", errors="replace").splitlines()
    return {
        key.strip().lower(): value.strip()
        for line in lines[1:]
        if ":" in line
        for key, value in [line.split(":", 1)]
    }


def parse_wet_records(data: bytes) -> list[tuple[str, str]]:
    """Return ``(target_uri, text)`` conversion records from WET bytes."""
    records: list[tuple[str, str]] = []
    cursor = 0
    while True:
        start = data.find(b"WARC/1.0", cursor)
        if start < 0:
            break
        separator = b"\r\n\r\n" if b"\r\n\r\n" in data[start:] else b"\n\n"
        header_end = data.find(separator, start)
        if header_end < 0:
            raise ValueError("WET record has no header terminator")
        headers = _headers(data[start:header_end])
        try:
            length = int(headers["content-length"])
        except (KeyError, ValueError) as exc:
            raise ValueError("WET record has an invalid Content-Length") from exc
        payload_start = header_end + len(separator)
        payload_end = payload_start + length
        if payload_end > len(data):
            raise ValueError("WET record payload is truncated")
        if headers.get("warc-type") == "conversion":
            text = data[payload_start:payload_end].decode("utf-8", errors="replace").strip()
            if text:
                records.append((headers.get("warc-target-uri", ""), text))
        cursor = payload_end
    if not records:
        raise ValueError("WET input contains no conversion records")
    return records


def load_sample(sample_file: Path | None = None) -> tuple[bytes, dict[str, Any]]:
    """Load a local WET file or the checksum-pinned official sample."""
    if sample_file is None:
        request = urllib.request.Request(
            SAMPLE_URL,
            headers={
                "User-Agent": "websieve-benchmark/1 (+https://github.com/ehtishammubarik/websieve)"
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
        expected_sha256 = SAMPLE_SHA256
        source = SAMPLE_URL
    else:
        data = sample_file.read_bytes()
        expected_sha256 = None
        source = str(sample_file.resolve())

    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError(f"sample checksum mismatch: expected {expected_sha256}, got {digest}")
    records = parse_wet_records(data)
    return data, {
        "source": source,
        "sha256": digest,
        "bytes": len(data),
        "conversion_records": len(records),
    }


def _alpha_id(value: int) -> str:
    """Stable alphabetic identifier that remains one MinHash token."""
    chars = []
    value += 1
    while value:
        value, remainder = divmod(value - 1, 26)
        chars.append(chr(ord("a") + remainder))
    return "".join(reversed(chars))


def _punctuate(words: Sequence[str], sentence_words: int = 20) -> str:
    sentences = []
    for start in range(0, len(words), sentence_words):
        sentence = " ".join(words[start : start + sentence_words]).strip()
        if sentence:
            sentences.append(sentence[0].upper() + sentence[1:] + ".")
    return " ".join(sentences)


def _base_words(source_words: Sequence[str], family_number: int, words_per_doc: int) -> list[str]:
    """Create unrelated families while retaining words from the public sample."""
    if not source_words:
        raise ValueError("source text has no words")
    family_id = _alpha_id(family_number)
    words = []
    for position in range(words_per_doc):
        if position % 5 == 4:
            words.append(f"anchor{family_id}{_alpha_id(position // 5)}")
        else:
            offset = (family_number * 97 + position * 13) % len(source_words)
            words.append(source_words[offset])
    return words


def iter_corpus(
    source_text: str,
    size: int,
    *,
    words_per_doc: int = 160,
    duplicate_every: int = 4,
) -> Iterator[CorpusDocument]:
    """Yield a deterministic corpus with known, high-similarity duplicate pairs."""
    if size < 1:
        raise ValueError("size must be positive")
    if words_per_doc < 20:
        raise ValueError("words_per_doc must be at least 20")
    source_words = source_text.split()
    emitted = 0
    family_number = 0
    while emitted < size:
        words = _base_words(source_words, family_number, words_per_doc)
        family = f"family-{family_number:06d}"
        yield CorpusDocument(
            key=f"doc-{emitted:08d}",
            text=_punctuate(words),
            family=family,
            expected_duplicate=False,
        )
        emitted += 1
        if emitted < size and family_number % duplicate_every == 0:
            variant = list(words)
            # Alter one compact span. Most shingles remain identical, while
            # exact hashing cannot mistake the pair for byte-identical input.
            variant[-8:] = list(reversed(variant[-8:]))
            yield CorpusDocument(
                key=f"doc-{emitted:08d}",
                text=_punctuate(variant),
                family=family,
                expected_duplicate=True,
            )
            emitted += 1
        family_number += 1


def _timed(repeats: int, operation: Callable[[], int]) -> tuple[float, int]:
    durations = []
    observations = 0
    for _ in range(repeats):
        started = time.perf_counter()
        observations = operation()
        durations.append(time.perf_counter() - started)
    return statistics.median(durations), observations


def _stage_result(
    name: str,
    documents: int,
    repeats: int,
    operation: Callable[[], int],
) -> dict[str, Any]:
    seconds, observations = _timed(repeats, operation)
    return {
        "stage": name,
        "documents": documents,
        "repeats": repeats,
        "median_seconds": round(seconds, 6),
        "documents_per_second": round(documents / seconds, 2),
        "observations": observations,
    }


def benchmark_stages(corpus: Sequence[CorpusDocument], repeats: int) -> list[dict[str, Any]]:
    """Measure each dependency-free stage independently."""
    texts = [doc.text for doc in corpus]
    html = [doc.html for doc in corpus]
    results = [
        _stage_result(
            "extract",
            len(corpus),
            repeats,
            lambda: sum(len(extract(value)[0]) for value in html),
        ),
        _stage_result(
            "normalize",
            len(corpus),
            repeats,
            lambda: sum(len(normalize(value)) for value in texts),
        ),
        _stage_result(
            "exact_hash",
            len(corpus),
            repeats,
            lambda: sum(len(normalized_hash(value)) for value in texts),
        ),
        _stage_result(
            "quality",
            len(corpus),
            repeats,
            lambda: sum(assess(value).passed for value in texts),
        ),
    ]
    for num_perm in (64, 128, 256):
        hasher = MinHash(num_perm=num_perm)
        results.append(
            _stage_result(
                f"minhash_{num_perm}",
                len(corpus),
                repeats,
                lambda hasher=hasher: sum(len(hasher.signature(value)) for value in texts),
            )
        )
    return results


def benchmark_dedup(
    corpus: Sequence[CorpusDocument],
    *,
    permutations: Sequence[int],
    threshold: float,
) -> list[dict[str, Any]]:
    """Measure MinHash speed together with precision and recall."""
    expected = {doc.key: doc.expected_duplicate for doc in corpus}
    rows = []
    for num_perm in permutations:
        bands = num_perm // 4
        started = time.perf_counter()
        predictions = list(
            deduplicate(
                ((doc.key, doc.text) for doc in corpus),
                threshold=threshold,
                num_perm=num_perm,
                bands=bands,
            )
        )
        seconds = time.perf_counter() - started
        tp = fp = fn = tn = 0
        for key, is_duplicate, _match, _similarity in predictions:
            truth = expected[key]
            if truth and is_duplicate:
                tp += 1
            elif truth:
                fn += 1
            elif is_duplicate:
                fp += 1
            else:
                tn += 1
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        rows.append(
            {
                "num_perm": num_perm,
                "bands": bands,
                "threshold": threshold,
                "documents": len(corpus),
                "seconds": round(seconds, 6),
                "documents_per_second": round(len(corpus) / seconds, 2),
                "true_positive": tp,
                "false_positive": fp,
                "false_negative": fn,
                "true_negative": tn,
                "precision": round(precision, 6),
                "recall": round(recall, 6),
            }
        )
    return rows


def _pipeline_run(source_text: str, size: int) -> tuple[int, dict[str, Any]]:
    pipeline = Pipeline(
        PipelineConfig(
            run_quality=False,
            num_perm=128,
            bands=32,
            near_dup_threshold=0.8,
        )
    )
    kept = sum(
        1
        for _ in pipeline.process(
            Document(url=f"https://benchmark.invalid/{doc.key}", text=doc.text)
            for doc in iter_corpus(source_text, size)
        )
    )
    return kept, pipeline.stats.to_dict()


def _peak_rss_mib() -> float:
    try:
        import resource
    except ImportError as exc:  # pragma: no cover - resource is unavailable on Windows
        raise RuntimeError("peak RSS measurement requires a Unix-like platform") from exc
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    bytes_used = raw if sys.platform == "darwin" else raw * 1024
    return bytes_used / (1024 * 1024)


def _rss_worker(source_text: str, size: int) -> dict[str, Any]:
    started = time.perf_counter()
    kept, stats = _pipeline_run(source_text, size)
    return {
        "documents": size,
        "kept": kept,
        "seconds": round(time.perf_counter() - started, 6),
        "peak_rss_mib": round(_peak_rss_mib(), 2),
        "stats": stats,
    }


def benchmark_memory(source_text: str, sizes: Sequence[int]) -> list[dict[str, Any]]:
    """Measure each size in a fresh process so RSS high-water marks do not leak."""
    rows = []
    for size in sizes:
        command = [sys.executable, str(Path(__file__).resolve()), "--rss-worker", str(size)]
        completed = subprocess.run(
            command,
            input=source_text,
            text=True,
            capture_output=True,
            check=True,
        )
        rows.append(json.loads(completed.stdout))
    return rows


def _environment() -> dict[str, Any]:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "logical_cpus": os.cpu_count(),
    }


def run_benchmark(
    source_text: str,
    source_metadata: dict[str, Any],
    *,
    stage_documents: int,
    repeats: int,
    permutations: Sequence[int],
    threshold: float,
    rss_sizes: Sequence[int],
) -> dict[str, Any]:
    """Run all benchmark dimensions and return a JSON-serializable result."""
    corpus = list(iter_corpus(source_text, stage_documents))
    first_by_family: dict[str, set[str]] = {}
    positive_jaccards = []
    for document in corpus:
        document_shingles = shingles(document.text)
        if document.expected_duplicate:
            first_shingles = first_by_family[document.family]
            positive_jaccards.append(
                len(first_shingles & document_shingles) / len(first_shingles | document_shingles)
            )
        else:
            first_by_family[document.family] = document_shingles
    pipeline_started = time.perf_counter()
    kept, pipeline_stats = _pipeline_run(source_text, stage_documents)
    pipeline_seconds = time.perf_counter() - pipeline_started
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source_metadata,
        "environment": _environment(),
        "config": {
            "stage_documents": stage_documents,
            "repeats": repeats,
            "permutations": list(permutations),
            "near_duplicate_threshold": threshold,
            "rss_sizes": list(rss_sizes),
            "corpus_words_per_document": 160,
            "positive_pair_true_jaccard_range": (
                [round(min(positive_jaccards), 6), round(max(positive_jaccards), 6)]
                if positive_jaccards
                else None
            ),
        },
        "stage_throughput": benchmark_stages(corpus, repeats),
        "dedup_quality": benchmark_dedup(
            corpus,
            permutations=permutations,
            threshold=threshold,
        ),
        "full_pipeline": {
            "documents": stage_documents,
            "kept": kept,
            "seconds": round(pipeline_seconds, 6),
            "documents_per_second": round(stage_documents / pipeline_seconds, 2),
            "stats": pipeline_stats,
        },
        "peak_memory": benchmark_memory(source_text, rss_sizes) if rss_sizes else [],
    }


def memory_growth_projection(result: dict[str, Any]) -> dict[str, Any] | None:
    """Fit the measured RSS series and return explicitly labelled extrapolations."""
    rows = result["peak_memory"]
    if len(rows) < 2:
        return None

    documents = [float(row["documents"]) for row in rows]
    if len(set(documents)) < 2:
        return None
    rss_mib = [float(row["peak_rss_mib"]) for row in rows]
    slope, intercept = statistics.linear_regression(documents, rss_mib)
    throughput = float(result["full_pipeline"]["documents_per_second"])
    if slope <= 0 or throughput <= 0:
        return None

    scales = []
    for count in (1_000_000, 5_000_000, 10_000_000):
        scales.append(
            {
                "documents": count,
                "rss_gib": (intercept + slope * count) / 1024,
                "hours": count / throughput / 3600,
            }
        )
    capacities = []
    for ram_gib in (16, 32, 64):
        capacities.append(
            {
                "ram_gib": ram_gib,
                "documents": max(0.0, (ram_gib * 1024 - intercept) / slope),
            }
        )
    return {
        "intercept_mib": intercept,
        "mib_per_1000_documents": slope * 1000,
        "scales": scales,
        "capacities": capacities,
    }


def render_markdown(result: dict[str, Any]) -> str:
    """Render a compact, reviewable report from machine-readable results."""
    env = result["environment"]
    source = result["source"]
    config = result["config"]
    lines = [
        "# WebSieve benchmark results",
        "",
        "This report is generated by `benchmarks/benchmark_pipeline.py`. The runner downloads "
        "a checksum-pinned WET record from Common Crawl's official example repository. The "
        "record targets an Aragonese Wikipedia page and is processed transiently; its text is "
        "not copied into this repository or the result JSON.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "uv run python benchmarks/benchmark_pipeline.py \\",
        f"  --stage-documents {config['stage_documents']} --repeats {config['repeats']} \\",
        f"  --permutations {','.join(str(value) for value in config['permutations'])} \\",
        f"  --threshold {config['near_duplicate_threshold']} \\",
        f"  --rss-sizes {','.join(str(value) for value in config['rss_sizes'])} \\",
        "  --output-json benchmark-results.json \\",
        "  --output-markdown benchmark-results.md",
        "```",
        "",
        "The public text is expanded deterministically into independent document families. "
        "Every fourth family receives one near-duplicate variant, so precision and recall "
        "have known labels; alphabetic anchors keep unrelated families distinct. Stage "
        "figures are medians. RSS sizes run in fresh processes and stream their input; "
        "quality is timed separately and disabled in the RSS pipeline so memory growth "
        "reflects the exact and near-duplicate indexes.",
        "",
        "## Reproduction metadata",
        "",
        f"- Timestamp (UTC): {env['timestamp_utc']}",
        f"- Platform: {env['platform']}",
        f"- Python: {env['implementation']} {env['python']}",
        f"- Machine / logical CPUs: {env['machine']} / {env['logical_cpus']}",
        f"- Input: {source['source']}",
        f"- Input SHA-256: `{source['sha256']}`",
        f"- Timed documents / repeats: {config['stage_documents']} / {config['repeats']}",
        "- Positive-pair true 5-shingle Jaccard range: "
        f"{config['positive_pair_true_jaccard_range']}",
        "",
        "## Stage throughput",
        "",
        "| Stage | Documents/s | Median seconds |",
        "| :--- | ---: | ---: |",
    ]
    for row in result["stage_throughput"]:
        lines.append(
            f"| {row['stage']} | {row['documents_per_second']:.2f} | {row['median_seconds']:.6f} |"
        )
    pipeline = result["full_pipeline"]
    lines.extend(
        [
            f"| full pipeline (quality disabled) | {pipeline['documents_per_second']:.2f} | "
            f"{pipeline['seconds']:.6f} |",
            "",
            "## MinHash accuracy and speed",
            "",
            "| Permutations | Documents/s | Precision | Recall | FP | FN |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in result["dedup_quality"]:
        lines.append(
            f"| {row['num_perm']} | {row['documents_per_second']:.2f} | "
            f"{row['precision']:.3f} | {row['recall']:.3f} | "
            f"{row['false_positive']} | {row['false_negative']} |"
        )
    lines.extend(
        [
            "",
            "## Peak resident memory",
            "",
            "Each row is a fresh process. RSS includes the interpreter and benchmark source text; "
            "the pipeline consumes the generated corpus as a stream.",
            "",
            "| Documents | Kept in indexes | Peak RSS MiB | Seconds |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    for row in result["peak_memory"]:
        lines.append(
            f"| {row['documents']} | {row['kept']} | {row['peak_rss_mib']:.2f} | "
            f"{row['seconds']:.6f} |"
        )
    projection = memory_growth_projection(result)
    if projection is not None:
        lines.extend(
            [
                "",
                "### What the memory series means",
                "",
                "The observed points fit `RSS = "
                f"{projection['intercept_mib']:.2f} MiB + "
                f"{projection['mib_per_1000_documents']:.2f} MiB per 1,000 input documents`. "
                "Growth is linear because the in-process exact and LSH indexes retain keys and "
                "MinHash signatures for every kept document. At larger scales, memory therefore "
                "becomes the binding constraint before elapsed time.",
                "",
                "Extrapolating that fit and the measured full-pipeline throughput:",
                "",
                "| Input documents | Projected peak RSS | Projected time |",
                "| ---: | ---: | ---: |",
            ]
        )
        for row in projection["scales"]:
            lines.append(
                f"| {row['documents']:,} | {row['rss_gib']:.1f} GiB | {row['hours']:.1f} h |"
            )
        lines.extend(
            [
                "",
                "The same fit gives these upper bounds if the process could consume all installed "
                "RAM; leave headroom for the operating system and workload variation:",
                "",
                "| Installed RAM | Approximate input at fitted RSS limit |",
                "| ---: | ---: |",
            ]
        )
        for row in projection["capacities"]:
            lines.append(
                f"| {row['ram_gib']} GiB | {row['documents'] / 1_000_000:.1f} million documents |"
            )
    lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            "These figures describe one pinned public WET record expanded into a controlled corpus, "
            "on one machine. The projections assume that the measured linear RSS growth and throughput "
            "continue outside the observed 1,000–10,000-document range. Document length, duplicate rate, "
            "settings, and hardware can move the wall; rerun the benchmark on representative input. "
            "The measurements do not compare against a NumPy implementation.",
            "",
        ]
    )
    return "\n".join(lines)


def _positive_int_list(value: str) -> list[int]:
    items = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not items or any(item <= 0 for item in items):
        raise argparse.ArgumentTypeError("expected a comma-separated list of positive integers")
    return items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-file", type=Path, help="local WET input instead of pinned sample")
    parser.add_argument("--stage-documents", type=int, default=500)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--permutations", type=_positive_int_list, default=[64, 128, 256])
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--rss-sizes", type=_positive_int_list, default=[100, 500, 1000])
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    parser.add_argument("--rss-worker", type=int, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rss_worker is not None:
        print(json.dumps(_rss_worker(sys.stdin.read(), args.rss_worker), sort_keys=True))
        return 0
    if args.stage_documents < 1 or args.repeats < 1:
        raise SystemExit("--stage-documents and --repeats must be positive")
    if not 0.0 <= args.threshold <= 1.0:
        raise SystemExit("--threshold must be between 0 and 1")
    if any(value % 4 for value in args.permutations):
        raise SystemExit("every --permutations value must be divisible by 4")

    data, source_metadata = load_sample(args.sample_file)
    records = parse_wet_records(data)
    source_text = "\n".join(text for _uri, text in records)
    result = run_benchmark(
        source_text,
        source_metadata,
        stage_documents=args.stage_documents,
        repeats=args.repeats,
        permutations=args.permutations,
        threshold=args.threshold,
        rss_sizes=args.rss_sizes,
    )
    markdown = render_markdown(result)
    if args.output_json:
        args.output_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.output_markdown:
        args.output_markdown.write_text(markdown, encoding="utf-8")
    if not args.output_markdown:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

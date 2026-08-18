import hashlib
import sys
from pathlib import Path

import pytest

# Benchmark utilities intentionally stay outside the installed zero-dependency
# package. Add the checkout root so plain ``pytest`` can exercise them in CI.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.benchmark_pipeline import (
    benchmark_dedup,
    iter_corpus,
    parse_wet_records,
    render_markdown,
)

SOURCE = (
    "A public web corpus needs transparent extraction and filtering so researchers can "
    "attribute every discarded record to one documented rule. Reproducible benchmarks "
    "report both throughput and errors because speed without correctness is not useful. "
) * 20


def _wet_record(*, uri: str, payload: bytes, warc_type: str = "conversion") -> bytes:
    return (
        (
            "WARC/1.0\r\n"
            f"WARC-Type: {warc_type}\r\n"
            f"WARC-Target-URI: {uri}\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode()
        + payload
        + b"\r\n\r\n"
    )


def test_parse_wet_records_uses_content_length_and_conversion_records_only():
    data = _wet_record(uri="", payload=b"metadata", warc_type="warcinfo") + _wet_record(
        uri="https://example.test/article", payload="plain text ✓".encode()
    )

    assert parse_wet_records(data) == [("https://example.test/article", "plain text ✓")]


def test_parse_wet_records_rejects_truncated_payload():
    data = _wet_record(uri="https://example.test", payload=b"complete")[:-5]
    with pytest.raises(ValueError, match="truncated"):
        parse_wet_records(data)


def test_controlled_corpus_is_deterministic_and_labels_duplicate_pairs():
    first = list(iter_corpus(SOURCE, 20))
    second = list(iter_corpus(SOURCE, 20))

    assert first == second
    assert len(first) == 20
    assert first[0].family == first[1].family
    assert first[0].expected_duplicate is False
    assert first[1].expected_duplicate is True
    assert first[0].text != first[1].text
    assert (
        hashlib.sha256(first[0].text.encode()).digest()
        == hashlib.sha256(second[0].text.encode()).digest()
    )


def test_dedup_benchmark_reports_accuracy_and_confusion_counts():
    corpus = list(iter_corpus(SOURCE, 40))

    [result] = benchmark_dedup(corpus, permutations=[64], threshold=0.8)

    assert result["documents"] == 40
    assert result["true_positive"] > 0
    assert result["true_positive"] + result["false_negative"] == sum(
        doc.expected_duplicate for doc in corpus
    )
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0


def test_markdown_renders_metadata_metrics_and_limits():
    result = {
        "source": {"source": "sample.wet", "sha256": "abc"},
        "environment": {
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "platform": "test-platform",
            "implementation": "CPython",
            "python": "3.12.0",
            "machine": "arm64",
            "logical_cpus": 8,
        },
        "config": {
            "stage_documents": 10,
            "repeats": 2,
            "permutations": [64],
            "near_duplicate_threshold": 0.8,
            "rss_sizes": [10],
            "positive_pair_true_jaccard_range": [0.85, 0.92],
        },
        "stage_throughput": [
            {"stage": "extract", "documents_per_second": 12.5, "median_seconds": 0.8}
        ],
        "dedup_quality": [
            {
                "num_perm": 64,
                "documents_per_second": 5.0,
                "precision": 1.0,
                "recall": 0.9,
                "false_positive": 0,
                "false_negative": 1,
            }
        ],
        "full_pipeline": {
            "documents_per_second": 4.0,
            "seconds": 2.5,
        },
        "peak_memory": [
            {"documents": 1000, "kept": 800, "peak_rss_mib": 42.31, "seconds": 3.0},
            {"documents": 5000, "kept": 4001, "peak_rss_mib": 85.59, "seconds": 15.1},
            {"documents": 10000, "kept": 8002, "peak_rss_mib": 139.72, "seconds": 30.5},
        ],
    }

    report = render_markdown(result)

    assert "sample.wet" in report
    assert "| 64 | 5.00 | 1.000 | 0.900 | 0 | 1 |" in report
    assert "10.82 MiB per 1,000 input documents" in report
    assert "| 16 GiB | 1.5 million documents |" in report
    assert "rerun the benchmark on representative input" in report

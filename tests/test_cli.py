import importlib.metadata
import io
import json
import subprocess
import sys

import pytest

from websieve import __version__
from websieve.cli import _ProgressReporter, main
from websieve.pipeline import PipelineStats

PROSE = (
    "Kubernetes schedules GPU workloads through the NVIDIA device plugin. "
    "The plugin advertises nvidia.com/gpu as an allocatable resource on nodes. "
    "Fragmentation becomes the dominant concern once training and inference mix. "
    "MIG partitioning splits an A100 into as many as seven separate instances. "
) * 4


def write_input(tmp_path, docs):
    p = tmp_path / "in.jsonl"
    p.write_text("\n".join(json.dumps(d) for d in docs) + "\n", encoding="utf-8")
    return str(p)


def test_build_writes_dataset_and_stats(tmp_path):
    src = write_input(
        tmp_path,
        [
            {"url": "u1", "text": PROSE},
            {"url": "u2", "text": PROSE},  # exact duplicate
            {"url": "u3", "text": "too short"},  # quality drop
        ],
    )
    out = tmp_path / "ds"
    assert main(["build", src, "-o", str(out)]) == 0
    stats = json.loads((out / "stats.json").read_text())
    assert stats["stats"]["seen"] == 3
    assert stats["stats"]["kept"] == 1
    assert stats["stats"]["dropped_by_stage"]["exact_duplicate"] == 1
    assert (out / "manifest.json").exists()


def test_build_respects_disabled_stages(tmp_path):
    src = write_input(tmp_path, [{"url": "u1", "text": "tiny"}])
    out = tmp_path / "ds"
    main(["build", src, "-o", str(out), "--no-quality", "--no-dedup"])
    assert json.loads((out / "stats.json").read_text())["stats"]["kept"] == 1


def test_build_chunks_only_after_document_survives_dedup(tmp_path):
    text = "# Guide\n\n" + "A useful sentence. " * 12
    src = write_input(tmp_path, [{"url": "u1", "text": text}, {"url": "u2", "text": text}])
    out = tmp_path / "ds"

    assert (
        main(
            [
                "build",
                src,
                "-o",
                str(out),
                "--chunk",
                "80",
                "--no-compress",
                "--no-quality",
            ]
        )
        == 0
    )

    records = [
        json.loads(line) for line in next(out.glob("shard-*.jsonl")).read_text().splitlines()
    ]
    assert len(records) > 1
    assert {record["doc_id"] for record in records} == {records[0]["doc_id"]}
    assert [record["chunk_index"] for record in records] == list(range(len(records)))
    assert all(record["heading_path"] == ["Guide"] for record in records)


def test_build_rejects_overlap_not_smaller_than_chunk(tmp_path, capsys):
    src = write_input(tmp_path, [{"url": "u1", "text": PROSE}])

    assert (
        main(["build", src, "-o", str(tmp_path / "ds"), "--chunk", "10", "--chunk-overlap", "10"])
        == 2
    )
    assert "--chunk-overlap must be smaller" in capsys.readouterr().err


def test_build_reports_progress_for_valid_dropped_and_malformed_records(tmp_path, capsys):
    p = tmp_path / "in.jsonl"
    good = json.dumps({"url": "u1", "text": PROSE})
    p.write_text(good + "\nNOT JSON\n" + good + "\n", encoding="utf-8")
    out = tmp_path / "ds"

    assert main(["build", str(p), "-o", str(out), "--progress-every", "1"]) == 0
    captured = capsys.readouterr()
    progress = [line for line in captured.err.splitlines() if line.endswith("docs/s")]

    assert captured.out == ""
    assert len(progress) == 3
    assert "1 seen" in progress[0] and "1 kept (100.0%)" in progress[0]
    assert "2 seen" in progress[1] and "1 kept (50.0%)" in progress[1]
    assert "3 seen" in progress[2] and "1 kept (33.3%)" in progress[2]


def test_build_progress_zero_is_silent(tmp_path, capsys):
    src = write_input(tmp_path, [{"url": "u1", "text": PROSE}])
    out = tmp_path / "ds"

    assert main(["build", src, "-o", str(out), "--progress-every", "0"]) == 0

    assert "docs/s" not in capsys.readouterr().err


def test_build_rejects_negative_progress_interval(tmp_path):
    src = write_input(tmp_path, [{"url": "u1", "text": PROSE}])
    out = tmp_path / "ds"

    with pytest.raises(SystemExit) as exc_info:
        main(["build", src, "-o", str(out), "--progress-every", "-1"])

    assert exc_info.value.code == 2


def test_progress_reporter_uses_elapsed_monotonic_time():
    ticks = iter([100.0, 102.0])
    stream = io.StringIO()
    reporter = _ProgressReporter(10, stream=stream, clock=lambda: next(ticks))

    reporter(PipelineStats(seen=10, kept=4))
    reporter(PipelineStats(seen=10, kept=4))  # the same milestone is not repeated

    assert stream.getvalue() == "     10 seen         4 kept (40.0%)   5 docs/s\n"


def test_malformed_line_is_skipped_not_fatal(tmp_path):
    p = tmp_path / "in.jsonl"
    p.write_text('{"url":"u1","text":"' + PROSE + '"}\nNOT JSON\n', encoding="utf-8")
    out = tmp_path / "ds"
    assert main(["build", str(p), "-o", str(out)]) == 0
    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert stats["seen"] == 2
    assert stats["malformed"] == 1
    assert stats["kept"] == 1
    assert stats["seen"] == stats["kept"] + stats["dropped"] + stats["malformed"]


def test_clean_file_has_no_malformed(tmp_path):
    src = write_input(
        tmp_path,
        [
            {"url": "u1", "text": PROSE},
            {"url": "u2", "text": PROSE + " variant."},
            {"url": "u3", "text": PROSE + " another variant."},
        ],
    )
    out = tmp_path / "ds"
    assert main(["build", src, "-o", str(out)]) == 0
    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert stats["malformed"] == 0
    assert stats["seen"] == stats["kept"] + stats["dropped"] + stats["malformed"]


def test_scattered_bad_lines_are_all_counted(tmp_path):
    p = tmp_path / "in.jsonl"
    good = '{"url":"u1","text":"' + PROSE + '"}'
    p.write_text(
        good + "\nBROKEN ONE\n" + good + "\nBROKEN TWO\n" + good + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "ds"
    assert main(["build", str(p), "-o", str(out)]) == 0
    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert stats["seen"] == 5
    assert stats["malformed"] == 2
    assert stats["seen"] == stats["kept"] + stats["dropped"] + stats["malformed"]


def test_truncated_line_is_counted_as_malformed(tmp_path):
    p = tmp_path / "in.jsonl"
    p.write_text(
        '{"url":"u1","text":"' + PROSE + '"}\n{"url":"u2","text":',
        encoding="utf-8",
    )
    out = tmp_path / "ds"
    assert main(["build", str(p), "-o", str(out)]) == 0
    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert stats["seen"] == 2
    assert stats["malformed"] == 1
    assert stats["seen"] == stats["kept"] + stats["dropped"] + stats["malformed"]


def test_all_lines_malformed_still_closes(tmp_path):
    p = tmp_path / "in.jsonl"
    p.write_text("BROKEN ONE\nBROKEN TWO\nBROKEN THREE\n", encoding="utf-8")
    out = tmp_path / "ds"
    assert main(["build", str(p), "-o", str(out)]) == 0
    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert stats["seen"] == 3
    assert stats["malformed"] == 3
    assert stats["kept"] == 0
    assert stats["seen"] == stats["kept"] + stats["dropped"] + stats["malformed"]
    assert (out / "stats.json").exists()


def test_stats_json_records_malformed(tmp_path):
    p = tmp_path / "in.jsonl"
    p.write_text('{"url":"u1","text":"' + PROSE + '"}\nNOT JSON\n', encoding="utf-8")
    out = tmp_path / "ds"
    assert main(["build", str(p), "-o", str(out)]) == 0
    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert "malformed" in stats


def test_build_strict_exits_nonzero_on_malformed(tmp_path):
    p = tmp_path / "in.jsonl"
    p.write_text('{"url":"u1","text":"' + PROSE + '"}\nNOT JSON\n', encoding="utf-8")
    out = tmp_path / "ds"
    assert main(["build", str(p), "-o", str(out), "--strict"]) == 1
    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert stats["malformed"] == 1


def test_build_strict_passes_when_no_malformed(tmp_path):
    src = write_input(tmp_path, [{"url": "u1", "text": PROSE}])
    out = tmp_path / "ds"
    assert main(["build", src, "-o", str(out), "--strict"]) == 0
    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert stats["malformed"] == 0


def test_build_max_malformed_within_budget_returns_zero(tmp_path):
    p = tmp_path / "in.jsonl"
    good = '{"url":"u1","text":"' + PROSE + '"}'
    p.write_text(good + "\nBAD ONE\n" + good + "\nBAD TWO\n", encoding="utf-8")
    out = tmp_path / "ds"
    assert main(["build", str(p), "-o", str(out), "--max-malformed", "5"]) == 0
    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert stats["malformed"] == 2


def test_build_max_malformed_exceeded_returns_nonzero(tmp_path):
    p = tmp_path / "in.jsonl"
    good = '{"url":"u1","text":"' + PROSE + '"}'
    p.write_text(
        good + "\nBAD ONE\n" + good + "\nBAD TWO\n" + good + "\nBAD THREE\n",
        encoding="utf-8",
    )
    out = tmp_path / "ds"
    assert main(["build", str(p), "-o", str(out), "--max-malformed", "2"]) == 1
    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert stats["malformed"] == 3


def test_build_max_malformed_zero_rejected_by_argparse(tmp_path):
    src = write_input(tmp_path, [{"url": "u1", "text": PROSE}])
    out = tmp_path / "ds"
    with pytest.raises(SystemExit) as exc_info:
        main(["build", src, "-o", str(out), "--max-malformed", "0"])
    assert exc_info.value.code == 2


def test_build_strict_and_max_malformed_are_mutually_exclusive(tmp_path):
    src = write_input(tmp_path, [{"url": "u1", "text": PROSE}])
    out = tmp_path / "ds"
    with pytest.raises(SystemExit) as exc_info:
        main(["build", src, "-o", str(out), "--strict", "--max-malformed", "3"])
    assert exc_info.value.code == 2


def test_build_strict_writes_stats_and_manifest_before_failing(tmp_path):
    p = tmp_path / "in.jsonl"
    p.write_text('{"url":"u1","text":"' + PROSE + '"}\nNOT JSON\n', encoding="utf-8")
    out = tmp_path / "ds"
    assert main(["build", str(p), "-o", str(out), "--strict"]) == 1
    assert (out / "stats.json").exists()
    assert (out / "manifest.json").exists()


def test_build_strict_all_lines_malformed(tmp_path):
    p = tmp_path / "in.jsonl"
    p.write_text("BROKEN ONE\nBROKEN TWO\nBROKEN THREE\n", encoding="utf-8")
    out = tmp_path / "ds"
    assert main(["build", str(p), "-o", str(out), "--strict"]) == 1
    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert stats["malformed"] == 3


def test_assess_command_runs(tmp_path, capsys):
    src = write_input(tmp_path, [{"url": "u1", "text": PROSE}])
    assert main(["assess", src]) == 0


def test_assess_sample_limits_documents_assessed(tmp_path, capsys):
    src = write_input(
        tmp_path,
        [{"url": f"u{i}", "text": PROSE} for i in range(20)],
    )
    with open(src, "a", encoding="utf-8") as fh:
        fh.write("NOT JSON\n")
    assert main(["assess", src, "--sample", "5"]) == 0
    err = capsys.readouterr().err
    assert "warning: skipping line 21" in err
    assert "documents   5  (sampled from stream)" in err
    assert "would pass  5" in err


def test_assess_sample_seed_makes_results_reproducible(tmp_path, capsys):
    docs = [
        {"url": f"pass-{i}", "text": PROSE}
        if i % 2 == 0
        else {"url": f"fail-{i}", "text": "too short"}
        for i in range(40)
    ]
    src = write_input(tmp_path, docs)

    assert main(["assess", src, "--sample", "10", "--seed", "123"]) == 0
    first = capsys.readouterr().err
    assert main(["assess", src, "--sample", "10", "--seed", "123"]) == 0
    second = capsys.readouterr().err

    assert first == second
    assert "documents   10  (sampled from stream)" in first


def test_assess_without_sample_counts_all_documents(tmp_path, capsys):
    src = write_input(
        tmp_path,
        [{"url": f"u{i}", "text": PROSE} for i in range(20)],
    )
    assert main(["assess", src]) == 0
    err = capsys.readouterr().err
    assert "documents   20\n" in err
    assert "(sampled from stream)" not in err


def test_dedup_command_reports_duplicates(tmp_path, capsys):
    src = write_input(tmp_path, [{"url": "u1", "text": PROSE}, {"url": "u2", "text": PROSE}])
    assert main(["dedup", src]) == 0
    assert "DUPLICATE_OF" in capsys.readouterr().out


def test_extract_command_json_output(tmp_path, capsys):
    page = tmp_path / "p.html"
    page.write_text(f"<html><head><title>T</title></head><body><p>{PROSE}</p></body></html>")
    assert main(["extract", str(page), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["title"] == "T" and "Kubernetes" in out["text"]


def test_module_is_executable(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "websieve.cli", "--help"], capture_output=True, text=True
    )
    assert r.returncode == 0 and "websieve" in r.stdout


def test_stdin_input(tmp_path):
    out = tmp_path / "ds"
    r = subprocess.run(
        [sys.executable, "-m", "websieve.cli", "build", "-", "-o", str(out)],
        input=json.dumps({"url": "u1", "text": PROSE}) + "\n",
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert json.loads((out / "stats.json").read_text())["stats"]["kept"] == 1


def test_stdin_progress_needs_no_known_total(tmp_path):
    out = tmp_path / "ds"
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "websieve.cli",
            "build",
            "-",
            "-o",
            str(out),
            "--progress-every",
            "1",
        ],
        input=json.dumps({"url": "u1", "text": PROSE}) + "\n",
        capture_output=True,
        text=True,
    )

    assert r.returncode == 0
    assert r.stdout == ""
    assert "1 seen" in r.stderr and "1 kept (100.0%)" in r.stderr
    assert "docs/s" in r.stderr


HTML_DOC = {
    "url": "https://example.com/a",
    "html": "<html><head><title>T</title></head><body><nav><a href='/'>Home</a></nav>"
    f"<article><p>{PROSE}</p></article><footer>Privacy</footer></body></html>",
}


def test_assess_extracts_html_before_judging(tmp_path, capsys):
    # Regression: assess used to read doc.text directly, which is empty for
    # HTML-only input, so it claimed every document failed word_count while
    # build on the same file kept them.
    src = write_input(tmp_path, [HTML_DOC])
    main(["assess", src])
    assert "would pass  1" in capsys.readouterr().err


def test_assess_and_build_agree_on_the_same_file(tmp_path, capsys):
    docs = [HTML_DOC, {"url": "https://example.com/nav", "text": "Home About Contact"}]
    src = write_input(tmp_path, docs)
    main(["assess", src])
    would_pass = int(capsys.readouterr().err.split("would pass")[1].split()[0])

    out = tmp_path / "ds"
    main(["build", src, "-o", str(out), "--no-dedup"])
    kept = json.loads((out / "stats.json").read_text())["stats"]["kept"]
    assert would_pass == kept


def test_dedup_extracts_html_before_hashing(tmp_path, capsys):
    # The same article as raw HTML and as plain text must be seen as duplicates.
    from websieve.clean.boilerplate import extract as _x
    from websieve.clean.normalize import normalize as _n

    plain = _n(_x(HTML_DOC["html"])[0])
    src = write_input(tmp_path, [HTML_DOC, {"url": "https://example.com/b", "text": plain}])
    main(["dedup", src])
    assert "DUPLICATE_OF" in capsys.readouterr().out


def test_version_matches_installed_metadata():
    """websieve.__version__ must match the installed package metadata."""
    installed = importlib.metadata.version("websieve")
    assert __version__ == installed


def test_version_flag_works(capsys):
    """websieve --version prints the version and exits cleanly."""
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("websieve")
    assert __version__ in out


def test_build_subcommand_version_flag_works(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["build", "--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert __version__ in out


def test_assess_subcommand_version_flag_works(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["assess", "--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert __version__ in out


def test_dedup_subcommand_version_flag_works(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["dedup", "--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert __version__ in out


def test_extract_subcommand_version_flag_works(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["extract", "--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert __version__ in out


def test_stats_json_records_websieve_version(tmp_path):
    """build output stats.json must include websieve_version."""
    src = write_input(tmp_path, [{"url": "u1", "text": PROSE}])
    out = tmp_path / "ds"
    main(["build", src, "-o", str(out)])
    report = json.loads((out / "stats.json").read_text())
    assert report["websieve_version"] == __version__


def test_manifest_json_records_websieve_version(tmp_path):
    """build output manifest.json must include websieve_version."""
    src = write_input(tmp_path, [{"url": "u1", "text": PROSE}])
    out = tmp_path / "ds"
    main(["build", src, "-o", str(out)])
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["websieve_version"] == __version__


def test_importing_websieve_survives_missing_distribution_metadata(monkeypatch):
    """A source checkout that was never installed must still import.
    `importlib.metadata.version` raises `PackageNotFoundError` when no
    distribution is installed, which happens for a plain clone, a vendored
    copy, or a PYTHONPATH import. Without the guard in `websieve/__init__.py`
    that exception escapes at import time and takes down every module below it,
    which is a steep price for a version string.
    """
    import importlib

    import websieve

    def _raise(_name):
        raise importlib.metadata.PackageNotFoundError("websieve")

    monkeypatch.setattr(importlib.metadata, "version", _raise)
    reloaded = importlib.reload(websieve)
    try:
        assert reloaded.__version__ == "0+unknown"
    finally:
        # Other tests compare __version__ against the real installed metadata,
        # so the sentinel must not outlive this test.
        monkeypatch.undo()
        importlib.reload(websieve)


# --------------------------------------------------------------------------
# Non-object JSON lines (issue #28)
#
# `[1,2,3]`, `"x"`, `42`, `true`, and `null` are all valid JSON and none of
# them is a record. Before the guard in Document.from_dict they raised
# AttributeError from inside a comprehension, which _read_docs did not catch,
# so one bad line from a writer hiccup killed an hours-long run.
# --------------------------------------------------------------------------

NON_OBJECT_LINES = ["[1,2,3]", '"just a string"', "42", "true", "null"]


@pytest.mark.parametrize("bad", NON_OBJECT_LINES)
def test_a_non_object_line_is_skipped_not_fatal(tmp_path, bad, capsys):
    src = tmp_path / "shapes.jsonl"
    src.write_text(f"{json.dumps({'url': 'u1', 'text': PROSE})}\n{bad}\n", encoding="utf-8")
    out = tmp_path / "out"

    assert main(["build", str(src), "-o", str(out), "--no-compress"]) == 0

    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert stats["malformed"] == 1
    assert stats["seen"] == stats["kept"] + stats["dropped"] + stats["malformed"]
    assert "warning: skipping line 2" in capsys.readouterr().err


@pytest.mark.parametrize("bad", NON_OBJECT_LINES)
def test_from_dict_names_what_it_got_instead_of_raising_attributeerror(bad):
    """The error a caller sees must describe the input, not the implementation.

    `AttributeError: 'list' object has no attribute 'items'` names a detail of
    the comprehension inside from_dict. It tells someone holding a bad corpus
    nothing about their corpus, and it changes if from_dict is refactored,
    which is why _read_docs must not depend on it.
    """
    from websieve.models import Document

    with pytest.raises(TypeError, match="expected a JSON object"):
        Document.from_dict(json.loads(bad))


@pytest.mark.parametrize("cmd", ["assess", "dedup"])
def test_assess_and_dedup_survive_a_non_object_line(tmp_path, cmd):
    """All three commands share _read_docs, so all three had the crash."""
    src = tmp_path / "shapes.jsonl"
    src.write_text(f"{json.dumps({'url': 'u1', 'text': PROSE})}\n[1,2,3]\n", encoding="utf-8")
    assert main([cmd, str(src)]) == 0


def test_every_non_object_shape_counts_toward_malformed(tmp_path):
    """All five in one file, so the counter cannot be right for one shape and
    wrong for another."""
    src = tmp_path / "shapes.jsonl"
    lines = [json.dumps({"url": "u1", "text": PROSE}), *NON_OBJECT_LINES]
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "out"

    assert main(["build", str(src), "-o", str(out), "--no-compress"]) == 0

    stats = json.loads((out / "stats.json").read_text())["stats"]
    assert stats["malformed"] == len(NON_OBJECT_LINES)
    assert stats["seen"] == stats["kept"] + stats["dropped"] + stats["malformed"]


def test_strict_fails_on_a_non_object_line(tmp_path):
    """The opt-in gate from #23 has to cover this shape too, or a pipeline
    using --strict still ships a truncated corpus silently."""
    src = tmp_path / "shapes.jsonl"
    src.write_text(f"{json.dumps({'url': 'u1', 'text': PROSE})}\n[1,2,3]\n", encoding="utf-8")
    out = tmp_path / "out"

    assert main(["build", str(src), "-o", str(out), "--no-compress", "--strict"]) == 1
    assert (out / "stats.json").exists()

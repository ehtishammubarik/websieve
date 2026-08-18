import importlib.metadata
import json
import subprocess
import sys

import pytest

from websieve import __version__
from websieve.cli import main

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


def test_malformed_line_is_skipped_not_fatal(tmp_path):
    p = tmp_path / "in.jsonl"
    p.write_text('{"url":"u1","text":"' + PROSE + '"}\nNOT JSON\n', encoding="utf-8")
    out = tmp_path / "ds"
    assert main(["build", str(p), "-o", str(out)]) == 0
    assert json.loads((out / "stats.json").read_text())["stats"]["seen"] == 1


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

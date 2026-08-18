import json

from websieve.export.writers import JsonlShardWriter, read_shards
from websieve.models import Document
from websieve.pipeline import Pipeline, PipelineConfig, PipelineStats

PROSE = (
    "Kubernetes schedules GPU workloads through the NVIDIA device plugin. "
    "The plugin advertises nvidia.com/gpu as an allocatable resource on nodes. "
    "Fragmentation becomes the dominant concern once training and inference mix. "
    "MIG partitioning splits an A100 into as many as seven separate instances. "
) * 4


def test_keeps_clean_document():
    p = Pipeline()
    assert [d.url for d in p.process([Document(url="u1", text=PROSE)])] == ["u1"]
    assert p.stats.kept == 1


def test_drops_exact_duplicate():
    p = Pipeline()
    list(p.process([Document(url="u1", text=PROSE), Document(url="u2", text=PROSE)]))
    assert p.stats.dropped_exact_dup == 1


def test_drops_near_duplicate():
    p = Pipeline(PipelineConfig(near_dup_threshold=0.7))
    docs = [Document(url="u1", text=PROSE), Document(url="u2", text=PROSE.replace("seven", "six"))]
    list(p.process(docs))
    assert p.stats.dropped_near_dup == 1


def test_drops_low_quality_and_attributes_the_rule():
    p = Pipeline()
    list(p.process([Document(url="u1", text="Home About Contact")]))
    assert p.stats.dropped_quality == 1
    assert "word_count" in p.stats.quality_failures


def test_html_and_plaintext_of_same_page_converge():
    # Extraction plus normalization must produce identical text, so the second
    # is caught as an exact duplicate rather than slipping through.
    p = Pipeline()
    docs = [
        Document(url="u1", text=PROSE),
        Document(
            url="u2",
            html=f"<html><body><nav><a href='/'>Home</a></nav>"
            f"<article><p>{PROSE}</p></article></body></html>",
        ),
    ]
    list(p.process(docs))
    assert p.stats.dropped_exact_dup == 1


def test_html_is_dropped_from_output():
    p = Pipeline()
    out = list(p.process([Document(url="u1", html=f"<p>{PROSE}</p>")]))
    assert out[0].html is None


def test_crawled_at_is_stamped():
    out = list(Pipeline().process([Document(url="u1", text=PROSE)]))
    assert out[0].crawled_at is not None


def test_existing_crawled_at_is_preserved():
    out = list(
        Pipeline().process([Document(url="u1", text=PROSE, crawled_at="2020-01-01T00:00:00Z")])
    )
    assert out[0].crawled_at == "2020-01-01T00:00:00Z"


def test_empty_document_counted_separately():
    p = Pipeline()
    list(p.process([Document(url="u1", text="   ")]))
    assert p.stats.dropped_empty == 1


def test_stages_can_be_disabled():
    p = Pipeline(PipelineConfig(run_quality=False, run_near_dedup=False))
    out = list(p.process([Document(url="u1", text="tiny")]))
    assert len(out) == 1


def test_stats_arithmetic_is_consistent():
    p = Pipeline(PipelineConfig(near_dup_threshold=0.7))
    docs = [
        Document(url="u1", text=PROSE),
        Document(url="u2", text=PROSE),
        Document(url="u3", text="short"),
        Document(url="u4", text=""),
    ]
    list(p.process(docs))
    assert p.stats.seen == p.stats.kept + p.stats.dropped
    assert 0.0 <= p.stats.keep_rate <= 1.0


def test_stats_serialize():
    p = Pipeline()
    list(p.process([Document(url="u1", text=PROSE)]))
    d = p.stats.to_dict()
    assert d["seen"] == 1 and d["kept"] == 1
    assert "dropped_by_stage" in d
    assert "malformed" in d
    assert d["malformed"] == 0
    json.dumps(d)  # must be serializable


def test_stats_arithmetic_includes_malformed():
    # malformed is a peer of dropped, not a sub-bucket, so the totals close:
    # seen == kept + dropped + malformed
    s = PipelineStats(seen=5, kept=2, dropped_empty=1, malformed=2)
    d = s.to_dict()
    assert d["malformed"] == 2
    assert d["seen"] == d["kept"] + d["dropped"] + d["malformed"]
    assert "malformed" in s.render()


def test_roundtrip_through_shards(tmp_path):
    p = Pipeline()
    out_dir = tmp_path / "ds"
    with JsonlShardWriter(out_dir, shard_size=2) as w:
        for doc in p.process(
            Document(url=f"u{i}", text=PROSE + f" variant {i}." * 3) for i in range(5)
        ):
            w.write(doc.to_dict())
        manifest = w.close()
    assert manifest["total_records"] == p.stats.kept
    assert len(list(read_shards(out_dir))) == p.stats.kept


def test_document_json_roundtrip():
    d = Document(url="u", text="hello", meta={"source": "test"})
    back = Document.from_json(d.to_json())
    assert back.url == d.url and back.text == d.text and back.meta == d.meta


def test_doc_id_is_stable_and_url_derived():
    assert Document(url="u", text="a").doc_id == Document(url="u", text="b").doc_id
    assert Document(url="u1", text="a").doc_id != Document(url="u2", text="a").doc_id

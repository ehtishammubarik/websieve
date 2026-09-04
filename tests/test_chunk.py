from websieve.chunk import semantic_chunks


def test_preserves_heading_paths_across_sections():
    chunks = semantic_chunks(
        "# Guide\n\nIntro text.\n\n## Install\n\nFirst step. Second step.",
        max_chars=35,
    )

    assert chunks[0].heading_path == ("Guide",)
    assert chunks[-1].heading_path == ("Guide", "Install")


def test_never_splits_fenced_code_or_markdown_table():
    code = "```python\nprint('a very long protected line')\n```"
    table = "| name | value |\n| --- | --- |\n| alpha | beta |"
    chunks = semantic_chunks(f"Before.\n\n{code}\n\n{table}\n\nAfter.", max_chars=20)
    texts = [chunk.text for chunk in chunks]

    assert code in texts
    assert table in texts


def test_overlap_is_bounded_and_never_duplicates_whole_chunk():
    chunks = semantic_chunks(
        "Alpha sentence one. Beta sentence two. Gamma sentence three.",
        max_chars=32,
        overlap=8,
    )

    assert len(chunks) > 1
    assert all(chunks[index].text != chunks[index - 1].text for index in range(1, len(chunks)))
    assert any(
        chunks[index - 1].text[-8:].lstrip() in chunks[index].text
        for index in range(1, len(chunks))
    )


def test_hard_cut_is_only_used_for_long_prose():
    chunks = semantic_chunks("x" * 25, max_chars=10)

    assert [len(chunk.text) for chunk in chunks] == [10, 10, 5]

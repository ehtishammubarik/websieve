"""Dependency-free semantic chunking for citation-ready RAG output."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class Chunk:
    """One chunk and the Markdown heading path that contains it."""

    text: str
    heading_path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Block:
    text: str
    heading_path: tuple[str, ...]
    protected: bool = False
    boundary: bool = False


def _is_table_start(lines: list[str], index: int) -> bool:
    return (
        "|" in lines[index]
        and index + 1 < len(lines)
        and bool(_TABLE_SEPARATOR.match(lines[index + 1]))
    )


def _blocks(text: str) -> list[_Block]:
    lines = text.splitlines()
    headings: list[str] = []
    blocks: list[_Block] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        fence = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)[0]
            collected = [line]
            index += 1
            while index < len(lines):
                collected.append(lines[index])
                if re.match(rf"^\s*{re.escape(marker)}{{3,}}\s*$", lines[index]):
                    index += 1
                    break
                index += 1
            blocks.append(_Block("\n".join(collected), tuple(headings), protected=True))
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            headings[level - 1 :] = [heading.group(2).strip()]
            blocks.append(_Block(line.strip(), tuple(headings), boundary=True))
            index += 1
            continue

        if _is_table_start(lines, index):
            collected = [line, lines[index + 1]]
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                collected.append(lines[index])
                index += 1
            blocks.append(_Block("\n".join(collected), tuple(headings), protected=True))
            continue

        paragraph = [line.strip()]
        index += 1
        while index < len(lines):
            if not lines[index].strip() or _HEADING.match(lines[index]):
                break
            if re.match(r"^\s*(`{3,}|~{3,})", lines[index]) or _is_table_start(lines, index):
                break
            paragraph.append(lines[index].strip())
            index += 1
        blocks.append(_Block(" ".join(paragraph), tuple(headings)))

    return blocks


def _split_prose(block: _Block, max_chars: int) -> list[_Block]:
    if block.protected or len(block.text) <= max_chars:
        return [block]

    pieces: list[_Block] = []
    current = ""
    for sentence in _SENTENCE_BOUNDARY.split(block.text):
        sentence = sentence.strip()
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars + 1)
            cut = cut if cut > 0 else max_chars
            prefix, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if current:
                pieces.append(_Block(current, block.heading_path))
                current = ""
            pieces.append(_Block(prefix, block.heading_path))
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            pieces.append(_Block(current, block.heading_path))
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(_Block(current, block.heading_path))
    return pieces


def semantic_chunks(text: str, *, max_chars: int, overlap: int = 0) -> list[Chunk]:
    """Split Markdown-like text without cutting fenced code blocks or tables.

    Protected blocks that exceed ``max_chars`` are emitted intact. Overlap is
    copied only from prose, never from a protected block, and is always smaller
    than the previous chunk so a whole chunk is not duplicated.
    """

    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be non-negative and smaller than max_chars")

    units = [piece for block in _blocks(text) for piece in _split_prose(block, max_chars)]
    chunks: list[Chunk] = []
    current: list[_Block] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        rendered = "\n\n".join(block.text for block in current).strip()
        chunks.append(Chunk(rendered, current[-1].heading_path))
        tail = ""
        if overlap and not current[-1].protected and len(rendered) > 1:
            tail_size = min(overlap, len(current[-1].text), len(rendered) - 1)
            tail = current[-1].text[-tail_size:].lstrip()
        current = [_Block(tail, current[-1].heading_path)] if tail else []

    for unit in units:
        if unit.boundary and current:
            flush()
        separator = 2 if current else 0
        size = sum(len(block.text) for block in current) + 2 * max(0, len(current) - 1)
        if current and size + separator + len(unit.text) > max_chars:
            flush()
        if current and sum(len(block.text) for block in current) + 2 + len(unit.text) > max_chars:
            current = []
        current.append(unit)
        if unit.protected and len(unit.text) > max_chars:
            flush()
    flush()
    return chunks

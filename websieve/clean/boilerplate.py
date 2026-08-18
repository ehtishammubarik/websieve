"""HTML to main-content text extraction.

Uses a text-density heuristic rather than a readability port, because the
target is crawled pages at corpus scale where per-site tuning is impossible.

The approach: strip non-content elements, split into blocks, score each block
by link density and text length, then keep the contiguous run of blocks with
the highest total score. Navigation and footers score badly because they are
short and mostly links. This is the same intuition behind Boilerpipe and
jusText, implemented with no dependencies.

Accuracy is deliberately traded for portability and speed. If you need better
extraction and can afford the dependency, use ``trafilatura`` and feed its
output into the quality stage instead. See ``docs/extraction.md``.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from statistics import median

# Elements whose contents are never body text.
_DROP_ELEMENTS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "canvas",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "button",
        "select",
        "iframe",
        "object",
        "embed",
        "figure",
        "figcaption",
    }
)

# Elements that end a text block.
_BLOCK_ELEMENTS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "main",
        "br",
        "hr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "tr",
        "td",
        "th",
        "blockquote",
        "pre",
        "dd",
        "dt",
    }
)


class _Block:
    __slots__ = ("is_heading", "link_chars", "text")

    def __init__(self) -> None:
        self.text: list[str] = []
        self.link_chars = 0
        self.is_heading = False

    def rendered(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.text)).strip()

    def score(self) -> float:
        """Higher is more likely to be body text.

        Two signals: absolute length, and the fraction of characters sitting
        inside anchors. A nav bar is short and almost entirely links; a
        paragraph is long and mostly not.
        """
        text = self.rendered()
        n = len(text)
        if n == 0:
            return 0.0
        link_density = min(self.link_chars / n, 1.0)
        if self.is_heading:
            # Headings are short by nature. Do not punish them for it, but do
            # not let a page of headings outscore a page of prose either.
            return n * 0.5 * (1.0 - link_density)
        return n * (1.0 - link_density) ** 2


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = [_Block()]
        self.title: str | None = None
        self._drop_depth = 0
        self._anchor_depth = 0
        self._in_title = False

    # -- helpers ---------------------------------------------------------
    def _new_block(self, *, heading: bool = False) -> None:
        if self.blocks[-1].rendered():
            self.blocks.append(_Block())
        self.blocks[-1].is_heading = heading

    # -- parser hooks ----------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _DROP_ELEMENTS:
            self._drop_depth += 1
            return
        if self._drop_depth:
            return
        if tag == "title":
            self._in_title = True
        elif tag == "a":
            self._anchor_depth += 1
        elif tag in _BLOCK_ELEMENTS:
            self._new_block(heading=tag.startswith("h") and len(tag) == 2)

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_ELEMENTS:
            self._drop_depth = max(0, self._drop_depth - 1)
            return
        if self._drop_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag == "a":
            self._anchor_depth = max(0, self._anchor_depth - 1)
        elif tag in _BLOCK_ELEMENTS:
            self._new_block()

    def handle_data(self, data: str) -> None:
        if self._drop_depth:
            return
        if self._in_title:
            self.title = (self.title or "") + data
            return
        if not data.strip():
            # Preserve a single space so words do not fuse across inline tags.
            if self.blocks[-1].text:
                self.blocks[-1].text.append(" ")
            return
        self.blocks[-1].text.append(data)
        if self._anchor_depth:
            self.blocks[-1].link_chars += len(data.strip())


def _best_run(blocks: list[_Block], scores: list[float]) -> tuple[int, int]:
    """Maximum-sum contiguous subarray over block scores (Kadane).

    Body text is contiguous. Picking the best *run* rather than the best
    individual blocks keeps paragraphs together and drops the nav that
    precedes them, without needing a DOM tree.
    """
    if not scores:
        return (0, 0)

    # A single long sidebar or widget must not raise the centering threshold
    # enough to make every short article paragraph look like a cost. Cap only
    # its influence on the mean; keep the raw score below so genuinely long
    # body blocks can still win the run.
    positive_scores = [score for score in scores if score > 0]
    score_cap = median(positive_scores) * 4 if positive_scores else 0.0
    centered_scores = [min(score, score_cap) for score in scores]
    mean = sum(centered_scores) / len(centered_scores)
    adjusted = [s - mean * 0.5 for s in scores]

    best_sum = float("-inf")
    best = (0, 1)
    cur_sum = 0.0
    cur_start = 0
    for i, v in enumerate(adjusted):
        if cur_sum <= 0:
            cur_start = i
            cur_sum = v
        else:
            cur_sum += v
        if cur_sum > best_sum:
            best_sum = cur_sum
            best = (cur_start, i + 1)
    return best


def extract(html_text: str, *, min_block_chars: int = 25) -> tuple[str, str | None]:
    """Extract main body text and title from an HTML document.

    Args:
        html_text: Raw HTML.
        min_block_chars: Blocks shorter than this are dropped unless they are
            headings. Filters out captions, bylines, and share widgets.

    Returns:
        ``(text, title)``. ``text`` is empty if nothing survived.
    """
    if not html_text or not html_text.strip():
        return ("", None)

    parser = _Extractor()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:
        # HTMLParser can raise on severely malformed input. Whatever was
        # parsed before the failure is still usable, so fall through.
        pass

    blocks = [b for b in parser.blocks if b.rendered()]
    if not blocks:
        return ("", _clean_title(parser.title))

    scores = [b.score() for b in blocks]
    start, end = _best_run(blocks, scores)

    # A heading immediately above the body run belongs to it. Kadane will not
    # pick it up on its own: headings are short, so they score below the mean
    # and look like a cost rather than a gain. Walk backwards and reclaim any
    # contiguous headings so the article title survives extraction.
    while start > 0 and blocks[start - 1].is_heading:
        start -= 1

    kept = blocks[start:end]

    lines = []
    for b in kept:
        t = b.rendered()
        if len(t) >= min_block_chars or b.is_heading:
            lines.append(t)

    return ("\n\n".join(lines), _clean_title(parser.title))


def _clean_title(raw: str | None) -> str | None:
    if not raw:
        return None
    t = re.sub(r"\s+", " ", html.unescape(raw)).strip()
    return t or None

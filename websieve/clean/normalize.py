"""Text normalization.

Runs before quality filtering and dedup. Both of those compare text against
thresholds or against other documents, and both give wrong answers if the same
logical character can appear in several byte sequences.

Stdlib only. No dependencies.
"""

from __future__ import annotations

import re
import unicodedata

# Zero-width and bidi control characters. These survive naive whitespace
# collapsing and silently break both hashing and token counts.
_INVISIBLE = re.compile(
    "["
    "\u200b-\u200f"  # zero-width space through RTL mark
    "\u202a-\u202e"  # bidi embedding and override
    "\u2060-\u2064"  # word joiner, invisible operators
    "\ufeff"  # BOM used mid-string
    "]"
)

# C0 and C1 control characters, except tab, newline, carriage return.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Runs of 3+ blank lines collapse to exactly one blank line.
_EXCESS_BLANK_LINES = re.compile(r"\n\s*\n\s*\n+")

# Horizontal whitespace runs, not touching newlines.
_HORIZONTAL_WS = re.compile(r"[^\S\n]+")

_QUOTE_MAP = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "′": "'",
        "″": '"',
    }
)


def strip_invisible(text: str) -> str:
    """Remove zero-width, bidi, and control characters."""
    return _CONTROL.sub("", _INVISIBLE.sub("", text))


def normalize_unicode(text: str, form: str = "NFKC") -> str:
    """Apply a Unicode normalization form.

    NFKC is the default because it folds compatibility variants such as
    fullwidth Latin and ligatures onto their plain equivalents. That is what
    you want for dedup and token counting. It is lossy for text where those
    distinctions carry meaning, so pass ``NFC`` to preserve them.
    """
    return unicodedata.normalize(form, text)


def normalize_quotes(text: str) -> str:
    """Fold typographic quotes onto ASCII equivalents."""
    return text.translate(_QUOTE_MAP)


def collapse_whitespace(text: str) -> str:
    """Collapse horizontal whitespace runs and excess blank lines.

    Paragraph structure is preserved: a single blank line survives, because
    the quality heuristics count lines and paragraphs.
    Indentation inside fenced code blocks (``` or ~~~) is preserved.
    """
    lines = text.split("\n")
    processed_lines = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            processed_lines.append(stripped)
        elif in_code_block:
            # Preserve internal indentation, trim trailing whitespace only
            processed_lines.append(line.rstrip())
        else:
            # Normal prose: collapse whitespace runs and strip outer padding
            collapsed = _HORIZONTAL_WS.sub(" ", stripped)
            processed_lines.append(collapsed)

    joined = "\n".join(processed_lines)
    return _EXCESS_BLANK_LINES.sub("\n\n", joined).strip()


def normalize(text: str, *, form: str = "NFKC", fold_quotes: bool = True) -> str:
    """Full normalization chain.

    Order matters. Invisibles are stripped before normalization so that a
    zero-width joiner cannot alter how a sequence composes.
    """
    if not text:
        return ""
    text = strip_invisible(text)
    text = normalize_unicode(text, form)
    if fold_quotes:
        text = normalize_quotes(text)
    return collapse_whitespace(text)

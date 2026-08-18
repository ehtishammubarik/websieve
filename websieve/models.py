"""Core data model.

A single ``Document`` carries a crawled page through every stage of the pipeline.
Stages never mutate in place; each returns a new document with additional fields
populated, so a run can be replayed from any intermediate shard.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Document:
    """One crawled page, at whatever stage of processing it has reached.

    Attributes:
        url: Canonical URL the content came from.
        text: Extracted plain text. Empty until the clean stage runs.
        html: Raw HTML. Dropped after extraction to keep shards small.
        title: Page title if one was found.
        language: ISO 639-1 code, populated by the quality stage.
        crawled_at: ISO 8601 UTC timestamp.
        quality: Per-rule results from the quality stage.
        signatures: Hashes used by the dedup stage.
        embedding: Vector, populated only if the embed stage runs.
        meta: Anything a caller wants to carry through untouched.
    """

    url: str
    text: str = ""
    html: str | None = None
    title: str | None = None
    language: str | None = None
    crawled_at: str | None = None
    quality: dict[str, Any] = field(default_factory=dict)
    signatures: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def doc_id(self) -> str:
        """Stable identifier derived from the URL.

        Deliberately URL-based rather than content-based: the same page
        re-crawled later must keep its identity so callers can diff snapshots.
        Content identity is handled separately in ``signatures``.
        """
        return hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:16]

    def to_dict(self, *, drop_html: bool = True) -> dict[str, Any]:
        d = asdict(self)
        if drop_html:
            d.pop("html", None)
        d["doc_id"] = self.doc_id
        return d

    def to_json(self, *, drop_html: bool = True) -> str:
        return json.dumps(self.to_dict(drop_html=drop_html), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Document:
        # A JSONL line can parse cleanly and still not be a record: `[1,2,3]`,
        # `"x"`, `42`, `true`, and `null` are all valid JSON. Without this
        # check the next line raises AttributeError from inside a
        # comprehension, naming `.items` rather than the actual problem, and
        # callers cannot distinguish it from a genuine bug in here.
        if not isinstance(d, dict):
            raise TypeError(f"expected a JSON object, got {type(d).__name__}")
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_json(cls, line: str) -> Document:
        return cls.from_dict(json.loads(line))

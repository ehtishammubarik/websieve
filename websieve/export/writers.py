"""Sharded dataset writers.

Training pipelines want many medium-sized shards, not one enormous file:
shards parallelize across dataloader workers, resume cleanly after a failure,
and stream from object storage without a full download.

``JsonlShardWriter`` is stdlib only and always available. ``ParquetShardWriter``
requires ``pyarrow`` and raises a clear error if it is missing rather than
failing at import time, so the rest of the package stays dependency-free.

Both writers emit a ``manifest.json`` describing every shard, because a dataset
you cannot verify the completeness of is a dataset you cannot trust.
"""

from __future__ import annotations

import gzip
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .. import __version__


class JsonlShardWriter:
    """Write records to gzipped JSONL shards of a bounded size.

    Args:
        out_dir: Directory to create shards in. Created if absent.
        shard_size: Records per shard.
        prefix: Filename prefix.
        compress: gzip the shards.

    Use as a context manager so the final partial shard and the manifest are
    always flushed, including on an exception.
    """

    def __init__(
        self,
        out_dir: str | os.PathLike,
        *,
        shard_size: int = 10_000,
        prefix: str = "shard",
        compress: bool = True,
    ) -> None:
        if shard_size < 1:
            raise ValueError("shard_size must be >= 1")
        self.out_dir = Path(out_dir)
        self.shard_size = shard_size
        self.prefix = prefix
        self.compress = compress
        self._fh = None
        self._index = 0
        self._in_shard = 0
        self._total = 0
        self._shards: list[dict[str, Any]] = []

    # -- lifecycle -------------------------------------------------------
    def __enter__(self) -> JsonlShardWriter:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _shard_path(self, index: int) -> Path:
        ext = "jsonl.gz" if self.compress else "jsonl"
        return self.out_dir / f"{self.prefix}-{index:05d}.{ext}"

    def _open_shard(self) -> None:
        path = self._shard_path(self._index)
        # A streaming writer holds the handle open across write() calls by
        # design; close() and __exit__ both guarantee release. Hence SIM115
        # is suppressed on the two lines below rather than fixed.
        self._fh = (
            gzip.open(path, "wt", encoding="utf-8")  # noqa: SIM115
            if self.compress
            else open(path, "w", encoding="utf-8")  # noqa: SIM115
        )
        self._in_shard = 0

    def _close_shard(self) -> None:
        if self._fh is None:
            return
        self._fh.close()
        path = self._shard_path(self._index)
        self._shards.append(
            {
                "path": path.name,
                "records": self._in_shard,
                "bytes": path.stat().st_size,
            }
        )
        self._fh = None
        self._index += 1

    # -- writing ---------------------------------------------------------
    def write(self, record: dict[str, Any]) -> None:
        if self._fh is None:
            self._open_shard()
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._in_shard += 1
        self._total += 1
        if self._in_shard >= self.shard_size:
            self._close_shard()

    def write_all(self, records: Iterable[dict[str, Any]]) -> int:
        for r in records:
            self.write(r)
        return self._total

    def close(self) -> dict[str, Any]:
        """Flush the open shard and write the manifest."""
        self._close_shard()
        manifest = {
            "format": "jsonl.gz" if self.compress else "jsonl",
            "total_records": self._total,
            "shard_count": len(self._shards),
            "shard_size": self.shard_size,
            "shards": self._shards,
            "websieve_version": __version__,
        }
        if self._shards or self.out_dir.exists():
            self.out_dir.mkdir(parents=True, exist_ok=True)
            (self.out_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
        return manifest

    @property
    def total(self) -> int:
        return self._total


def read_shards(out_dir: str | os.PathLike) -> Iterable[dict[str, Any]]:
    """Stream every record back, in shard order, using the manifest.

    Reads the manifest rather than globbing so that a truncated or partially
    uploaded shard directory surfaces as a missing-file error instead of
    silently yielding an incomplete dataset.
    """
    out_dir = Path(out_dir)
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"no manifest.json in {out_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for shard in manifest["shards"]:
        path = out_dir / shard["path"]
        if not path.exists():
            raise FileNotFoundError(f"manifest lists {shard['path']} but it is missing")
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)


class ParquetShardWriter:
    """Parquet equivalent of ``JsonlShardWriter``. Requires ``pyarrow``."""

    def __init__(
        self,
        out_dir: str | os.PathLike,
        *,
        shard_size: int = 10_000,
        prefix: str = "shard",
        compression: str = "zstd",
    ) -> None:
        try:
            import pyarrow  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on env
            raise ImportError(
                "ParquetShardWriter requires pyarrow. Install it with "
                "'pip install websieve[parquet]', or use JsonlShardWriter "
                "which has no dependencies."
            ) from exc
        self.out_dir = Path(out_dir)
        self.shard_size = shard_size
        self.prefix = prefix
        self.compression = compression
        self._buffer: list[dict[str, Any]] = []
        self._index = 0
        self._total = 0
        self._shards: list[dict[str, Any]] = []

    def __enter__(self) -> ParquetShardWriter:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _flush(self) -> None:
        if not self._buffer:
            return
        import pyarrow as pa
        import pyarrow.parquet as pq

        path = self.out_dir / f"{self.prefix}-{self._index:05d}.parquet"
        pq.write_table(pa.Table.from_pylist(self._buffer), path, compression=self.compression)
        self._shards.append(
            {"path": path.name, "records": len(self._buffer), "bytes": path.stat().st_size}
        )
        self._buffer.clear()
        self._index += 1

    def write(self, record: dict[str, Any]) -> None:
        self._buffer.append(record)
        self._total += 1
        if len(self._buffer) >= self.shard_size:
            self._flush()

    def write_all(self, records: Iterable[dict[str, Any]]) -> int:
        for r in records:
            self.write(r)
        return self._total

    def close(self) -> dict[str, Any]:
        self._flush()
        manifest = {
            "format": "parquet",
            "compression": self.compression,
            "total_records": self._total,
            "shard_count": len(self._shards),
            "shard_size": self.shard_size,
            "shards": self._shards,
            "websieve_version": __version__,
        }
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        return manifest

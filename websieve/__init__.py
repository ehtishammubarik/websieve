from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("websieve")
except PackageNotFoundError:  # pragma: no cover - exercised via monkeypatch
    # A source checkout that has not been installed is a normal thing to have:
    # someone reading the code, a vendored copy, a PYTHONPATH import. Before
    # this guard, `import websieve` raised here and took down every module
    # downstream of it, which is a steep price for a version string.
    __version__ = "0+unknown"

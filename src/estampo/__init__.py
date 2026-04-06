"""estampo — The build system for reproducible 3D prints."""

from __future__ import annotations

from importlib.metadata import version as _pkg_version
from pathlib import Path

__version__ = _pkg_version("estampo")


class EstampoError(Exception):
    """User-facing error — printed without a traceback."""


def require_file(path: Path, label: str = "File") -> None:
    """Raise FileNotFoundError if *path* does not exist."""
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


__all__ = ["EstampoError", "__version__", "require_file"]

"""estampo — Reproducible 3D print builds."""

from __future__ import annotations

from pathlib import Path

__version__ = "0.2.0"


class EstampoError(Exception):
    """User-facing error — printed without a traceback."""


# Backward-compatible alias (fabprint → estampo migration)
FabprintError = EstampoError


def require_file(path: Path, label: str = "File") -> None:
    """Raise FileNotFoundError if *path* does not exist."""
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


__all__ = ["EstampoError", "FabprintError", "__version__", "require_file"]

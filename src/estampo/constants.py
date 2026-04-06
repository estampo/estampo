"""Shared constants for the estampo package."""

NS_3MF = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"

# Default plate dimensions (mm) — Bambu Lab standard build volume
DEFAULT_PLATE_SIZE: tuple[float, float] = (256.0, 256.0)

# Thumbnail size (px) — used in 3MF preview generation
DEFAULT_THUMBNAIL_SIZE: int = 256

# Minimum filament slot array length in BBL 3MF metadata.
# P1S has a 4-slot AMS + 1 external spool = 5 slots.
MIN_FILAMENT_SLOTS: int = 5

"""Shared constants for the estampo package."""

NS_3MF = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"

# Default plate dimensions (mm)
DEFAULT_PLATE_SIZE: tuple[float, float] = (256.0, 256.0)

# Minimum filament slot array length in 3MF metadata.
MIN_FILAMENT_SLOTS: int = 5

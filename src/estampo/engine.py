"""Slicer engine protocol — the contract every engine module must implement.

See docs/decisions/006-slicer-plugin-protocol.md for the full specification.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SlicerEngine(Protocol):
    """Protocol that every slicer engine module must satisfy.

    Engine modules (``orca.py``, ``cura.py``, …) are plain Python modules,
    not classes.  This Protocol exists so that:

    1. Static type checkers can verify dispatch layers call the right signatures.
    2. Tests can assert that an engine module conforms at import time.
    3. New engine authors have a single source of truth for what to implement.

    Functions not yet needed by an engine should raise ``NotImplementedError``.
    """

    ENGINE_NAME: str
    ENGINE_KEY: str

    @staticmethod
    def find_binary() -> Path:
        """Locate the slicer executable on this system.

        Raises ``FileNotFoundError`` if not found.
        """
        ...

    @staticmethod
    def docker_image(version: str | None = None) -> str:
        """Return the Docker image tag for this engine and version.

        Must use the ``estampo/estampo:<key>-<version>`` format.
        """
        ...

    @staticmethod
    def discover_profiles(
        project_dir: Path,
        profiles_dir: str,
    ) -> dict[str, list[str]]:
        """Return available profile/definition names by category."""
        ...

    @staticmethod
    def load_profile(
        name: str,
        category: str,
        project_dir: Path,
        profiles_dir: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Load a profile/definition by name and category."""
        ...

    @staticmethod
    def pin_profiles(
        project_dir: Path,
        profiles_dir: str,
        version: str | None = None,
    ) -> list[Path]:
        """Pin profiles/definitions for reproducible builds."""
        ...

    @staticmethod
    def bundled_profile_names(version: str | None = None) -> dict[str, list[str]]:
        """Return profile/definition names from bundled data files."""
        ...

    @staticmethod
    def wizard_steps(
        console: Any,
        existing_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run engine-specific init wizard steps."""
        ...

    @staticmethod
    def emit_toml(config_values: dict[str, Any]) -> list[str]:
        """Emit the ``[slicer.<key>]`` TOML section lines for this engine."""
        ...

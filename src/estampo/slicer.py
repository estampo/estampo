"""Slicer dispatch — routes to engine-specific modules (orca, cura)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

from estampo.gcode import parse_gcode_metadata

# Re-export OrcaSlicer symbols for backward compatibility.
# Tests and scripts may import these from estampo.slicer.
from estampo.orca import (  # noqa: F401, E402
    _BC_DEFAULT_KEYS,
    _MIN_FILAMENT_SLOTS,
    _apply_overrides,
    _check_slicer_version,
    _detect_slicer_version,
    _fix_sliced_3mf,
    _resolve_profiles,
    _slice_via_docker,
    _write_tmp_profile,
    docker_image,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Slicer discovery (shared across engines)
# ---------------------------------------------------------------------------


def _slicer_paths() -> dict[str, Path]:
    """Return default slicer executable paths for the current platform."""
    if sys.platform == "darwin":
        return {
            "orca": Path("/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"),
            "cura": Path("/Applications/UltiMaker Cura.app/Contents/MacOS/CuraEngine"),
        }
    elif sys.platform == "win32":
        pf = Path("C:/Program Files")
        return {
            "orca": pf / "OrcaSlicer/orca-slicer.exe",
            "cura": pf / "UltiMaker Cura/CuraEngine.exe",
        }
    else:  # Linux and other Unix
        return {
            "orca": Path("/usr/bin/orca-slicer"),
            "cura": Path("/usr/local/bin/CuraEngine"),
        }


SLICER_PATHS = _slicer_paths()


def find_slicer(engine: str) -> Path:
    """Find the slicer executable for the given engine.

    Checks the platform-specific default path first, then falls back
    to searching PATH (useful on Linux or custom installs).
    """
    if engine not in SLICER_PATHS:
        raise ValueError(f"Unknown slicer engine: '{engine}'. Supported: {list(SLICER_PATHS)}")

    path = SLICER_PATHS[engine]
    if path.exists():
        return path

    # Fall back to PATH lookup (handles AppImage, Flatpak, AUR, custom installs)
    path_names = {
        "orca": ("orca-slicer", "OrcaSlicer", "OrcaSlicer.AppImage"),
        "cura": ("CuraEngine", "curaengine"),
    }
    for name in path_names.get(engine, ()):
        found = shutil.which(name)
        if found:
            return Path(found)

    raise FileNotFoundError(f"Slicer ({engine}) not found at {path} or on PATH. Is it installed?")


# ---------------------------------------------------------------------------
# Shared Docker utilities (used by both orca and cura engines)
# ---------------------------------------------------------------------------


def _has_docker_image(image: str) -> bool:
    """Check if the given Docker image exists locally."""
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _pull_docker_image(image: str, *, cached: bool) -> bool:
    """Pull a Docker image from the registry. Returns True on success."""
    from estampo import ui

    label = "Checking for updated image" if cached else "Pulling Docker image"
    log.info("Pulling Docker image %s ...", image)
    try:
        with ui.status(f"{label} [bold]{image}[/bold]"):
            r = subprocess.run(
                ["docker", "pull", image],
                capture_output=True,
                text=True,
                timeout=300,
            )
        if r.returncode == 0:
            return True
        log.debug("docker pull failed: %s", r.stderr.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False


def _ensure_docker_image(image: str) -> bool:
    """Ensure an up-to-date Docker image is available locally.

    Always attempts a pull so that image updates are picked up
    automatically.  If the pull fails (no network, registry down)
    the locally cached image is used instead.  Returns False only
    when no usable image is available at all.
    """
    cached = _has_docker_image(image)
    if _pull_docker_image(image, cached=cached):
        return True
    # Pull failed — fall back to local cache if available
    if cached:
        log.warning("Could not pull %s — using locally cached image", image)
        return True
    return False


# ---------------------------------------------------------------------------
# Printer-specific post-processing
# ---------------------------------------------------------------------------


def package_for_printer(
    sliced_output_dir: Path,
    plate_3mf: Path | None = None,
    printer_type: str | None = None,
) -> Path:
    """Printer-specific post-processing of slicer output.

    For Bambu printers: patches the .gcode.3mf so Bambu Connect accepts it
    (missing keys, short filament arrays, thumbnails).

    For other printers: returns the plain .gcode path unchanged.

    Returns the path to the deliverable file.
    """
    is_bambu = printer_type in ("bambu-lan", "bambu-cloud")

    if is_bambu:
        sliced_3mfs = list(sliced_output_dir.glob("*_sliced.gcode.3mf"))
        if sliced_3mfs:
            _fix_sliced_3mf(sliced_3mfs[0], plate_3mf)
            return sliced_3mfs[0]

    # Non-Bambu or no 3MF found: return plain gcode
    gcode_files = list(sliced_output_dir.glob("*.gcode"))
    if gcode_files:
        return gcode_files[0]

    # Fallback: return whatever is available
    sliced_3mfs = list(sliced_output_dir.glob("*_sliced.gcode.3mf"))
    if sliced_3mfs:
        return sliced_3mfs[0]

    raise FileNotFoundError(f"No gcode or 3MF output found in {sliced_output_dir}")


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------


def slice_plate(
    input_3mf: Path,
    engine: str = "orca",
    output_dir: Path | None = None,
    printer: str | None = None,
    process: str | None = None,
    filaments: list[str] | None = None,
    filament_ids: list[int] | None = None,
    overrides: dict[str, object] | None = None,
    machine_overrides: dict[str, object] | None = None,
    filament_overrides: dict[str, object] | None = None,
    project_dir: Path | None = None,
    local: bool = False,
    docker_version: str | None = None,
    required_version: str | None = None,
    profiles_dir: str = "profiles",
    bed_type: str | None = None,
) -> Path:
    """Slice a 3MF file using BambuStudio or OrcaSlicer CLI.

    Profile names are resolved via profiles.resolve_profile_data().
    If overrides are provided, they are patched into the process profile.
    If machine_overrides are provided, they are patched into the machine profile.
    If filament_overrides are provided, they are patched into every filament profile.

    Slicer selection:
      local=True           - force local slicer, fail if not installed
      docker_version="X"   - force Docker with estampo:orca-X image
      neither (default)    - try Docker first, fall back to local

    If required_version is set (from config), the slicer version is checked
    and must match exactly. For Docker, the image tag is used as the version.

    Returns the output directory containing the sliced gcode.
    """
    # CuraEngine backend — separate execution path
    if engine == "cura":
        from estampo.cura import (
            cura_docker_image,
            cura_profile_from_config,
            slice_stl,
        )

        if output_dir is None:
            output_dir = input_3mf.parent / "output"
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        import trimesh

        scene = trimesh.load(str(input_3mf))
        if isinstance(scene, trimesh.Scene):
            mesh = scene.to_geometry()
        else:
            mesh = scene
        z_min = float(mesh.bounds[0][2])  # type: ignore[attr-defined]
        if z_min < 0:
            mesh.vertices[:, 2] -= z_min  # type: ignore[attr-defined]
        stl_path = output_dir / (input_3mf.stem + ".stl")
        mesh.export(str(stl_path), file_type="stl")

        if isinstance(filaments, dict):
            filament_type = next(iter(filaments.values()), None)
        elif filaments:
            filament_type = filaments[0]
        else:
            filament_type = None

        profile = cura_profile_from_config(
            overrides=overrides,
            bed_type=bed_type,
            filament_type=filament_type,
            printer=printer,
            project_dir=project_dir,
            profiles_dir=profiles_dir,
        )
        image = cura_docker_image(docker_version or required_version)
        return slice_stl(
            stl_path,
            output_dir,
            profile,
            image=image,
            printer=printer,
            project_dir=project_dir,
            profiles_dir=profiles_dir,
        )

    # OrcaSlicer backend — delegate to orca module
    from estampo.orca import orca_slice_plate

    return orca_slice_plate(
        input_3mf=input_3mf,
        output_dir=output_dir,
        printer=printer,
        process=process,
        filaments=filaments,
        filament_ids=filament_ids,
        overrides=overrides,
        machine_overrides=machine_overrides,
        filament_overrides=filament_overrides,
        project_dir=project_dir,
        local=local,
        docker_version=docker_version,
        required_version=required_version,
        profiles_dir=profiles_dir,
        bed_type=bed_type,
    )


def parse_gcode_stats(output_dir: Path) -> dict[str, str | float | int]:
    """Parse filament usage and print time from gcode in an output directory.

    Finds the first .gcode file and delegates to gcode.parse_gcode_metadata().
    Returns dict with 'filament_g' and/or 'filament_cm3' and/or 'print_time'.
    """
    gcode_files = sorted(output_dir.glob("*.gcode"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not gcode_files:
        return {}

    return parse_gcode_metadata(gcode_files[0])

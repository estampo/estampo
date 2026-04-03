"""CuraEngine slicer backend.

Slices STL files using CuraEngine via Docker, with BBL-specific start/end
G-code for Bambu Lab printers. Produces plain G-code that can be packaged
into .gcode.3mf.

Uses CuraEngine 5.12.0 extracted from the UltiMaker Cura AppImage,
packaged in a minimal Docker image (~95 MB) with bundled definitions.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from estampo import EstampoError

log = logging.getLogger(__name__)

DOCKERHUB_REPO = "estampo/estampo"
CURAENGINE_VERSION = "5.12.0"

# Definitions directory inside the Docker image (bundled from Cura AppImage).
_DEFS_DIR = "/opt/cura/definitions"


def cura_docker_image(version: str | None = None) -> str:
    """Return the Docker image name for a given CuraEngine version."""
    if version:
        return f"{DOCKERHUB_REPO}:cura-{version}"
    return f"{DOCKERHUB_REPO}:cura-{CURAENGINE_VERSION}"


@dataclass
class CuraProfile:
    """Minimal slicer profile for CuraEngine targeting a BBL printer."""

    # Machine
    machine_width: float = 256.0
    machine_depth: float = 256.0
    machine_height: float = 256.0
    machine_heated_bed: bool = True
    machine_name: str = "Bambu Lab P1S"

    # Nozzle / material
    nozzle_diameter: float = 0.4
    material_diameter: float = 1.75
    material_print_temperature: int = 260
    material_bed_temperature: int = 70

    # Process
    layer_height: float = 0.20
    layer_height_0: float = 0.20
    infill_sparse_density: int = 25
    wall_line_count: int = 3
    top_layers: int = 5
    bottom_layers: int = 4
    speed_print: int = 80
    speed_travel: int = 200
    speed_wall_0: int = 50
    speed_infill: int = 80

    # BBL-specific
    bed_type: str = "Textured PEI Plate"
    filament_type: str = "PETG-CF"

    # Additional -s overrides (Cura setting key names)
    overrides: dict[str, str] = field(default_factory=dict)


def _render_bbl_gcode(profile: CuraProfile) -> tuple[str, str]:
    """Render P1S start/end G-code for Bambu Lab printers.

    Returns (start_gcode, end_gcode) as rendered strings.
    """
    bed = profile.material_bed_temperature
    nozzle = profile.material_print_temperature

    start = f"""\
M140 S{bed}  ; set bed temp
M104 S{nozzle}  ; set nozzle temp
G28  ; home all axes
M190 S{bed}  ; wait for bed temp
M109 S{nozzle}  ; wait for nozzle temp
G92 E0  ; reset extruder
G1 Z2.0 F3000  ; move Z up
G1 X5 Y5 F5000  ; move to start
G1 Z0.28 F1500  ; lower to first layer
G1 X60 E9 F1000  ; prime line
G1 X100 E12.5 F1000  ; prime line
G92 E0  ; reset extruder
G1 Z2.0 F3000  ; lift nozzle
"""

    end = """\
G91  ; relative positioning
G1 E-2 F2700  ; retract
G1 Z5 F3000  ; lift nozzle
G90  ; absolute positioning
G1 X0 Y250 F5000  ; present print
M104 S0  ; turn off nozzle
M140 S0  ; turn off bed
M107  ; turn off fan
M84  ; disable steppers
"""
    return start, end


def _settings_flags(profile: CuraProfile) -> list[str]:
    """Build -s key=value flags from profile."""
    pairs: dict[str, object] = {
        "layer_height": profile.layer_height,
        "layer_height_0": profile.layer_height_0,
        "material_print_temperature": profile.material_print_temperature,
        "material_print_temperature_layer_0": profile.material_print_temperature,
        "material_bed_temperature": profile.material_bed_temperature,
        "material_bed_temperature_layer_0": profile.material_bed_temperature,
        "material_diameter": profile.material_diameter,
        "infill_sparse_density": profile.infill_sparse_density,
        "wall_line_count": profile.wall_line_count,
        "top_layers": profile.top_layers,
        "bottom_layers": profile.bottom_layers,
        "speed_print": profile.speed_print,
        "speed_travel": profile.speed_travel,
        "speed_wall_0": profile.speed_wall_0,
        "speed_infill": profile.speed_infill,
        "machine_width": profile.machine_width,
        "machine_depth": profile.machine_depth,
        "machine_height": profile.machine_height,
        "machine_heated_bed": "true" if profile.machine_heated_bed else "false",
        "material_print_temp_prepend": "false",
        "material_bed_temp_prepend": "false",
        "adhesion_type": "none",
        # CuraEngine 5.12 requires these explicitly (not resolved from def)
        "roofing_layer_count": 0,
        "flooring_layer_count": 0,
    }
    pairs.update(profile.overrides)

    flags: list[str] = []
    for k, v in pairs.items():
        flags.extend(["-s", f"{k}={v}"])
    return flags


def slice_stl(
    stl_path: Path,
    output_dir: Path,
    profile: CuraProfile | None = None,
    image: str | None = None,
) -> Path:
    """Slice an STL file with CuraEngine and return the output directory.

    Uses Docker with the estampo/estampo:cura-X.Y.Z image (same layered
    pattern as OrcaSlicer). Injects BBL P1S start/end G-code via Jinja2
    templates, written as files under output_dir and read inside the
    container via volume mount.

    Args:
        stl_path: Path to the input STL file.
        output_dir: Directory for output G-code.
        profile: Slicer profile. Defaults to P1S / PETG-CF / 0.2mm.
        image: Docker image override. Defaults to estampo/estampo:cura-5.12.0.

    Returns:
        The output directory (matching slicer.slice_plate contract).
    """
    if profile is None:
        profile = CuraProfile()
    if image is None:
        image = cura_docker_image()

    stl_path = stl_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Render BBL start/end G-code to files under output_dir so they're
    # accessible via the same volume mount as the output.
    start_gcode, end_gcode = _render_bbl_gcode(profile)
    staging = output_dir / ".cura-staging"
    staging.mkdir(exist_ok=True)
    (staging / "start.gcode").write_text(start_gcode)
    (staging / "end.gcode").write_text(end_gcode)

    # Copy STL into staging so it's accessible via volume mount
    stl_in_staging = staging / stl_path.name
    shutil.copy2(stl_path, stl_in_staging)

    # Container paths (output_dir mounted at /work/output)
    c_staging = "/work/output/.cura-staging"
    c_stl = f"{c_staging}/{stl_path.name}"
    c_output = "/work/output/" + stl_path.stem + ".gcode"

    # Build the shell command that runs inside the container.
    # Start/end gcode are loaded from files into shell vars because
    # -s values can't contain newlines directly.
    settings = _settings_flags(profile)
    inner_cmd = (
        f"START=$(cat {c_staging}/start.gcode) && "
        f"END=$(cat {c_staging}/end.gcode) && "
        f"CuraEngine slice "
        f"-j {_DEFS_DIR}/fdmprinter.def.json "
        f"-o {c_output} "
        + " ".join(f'"{s}"' for s in settings)
        + ' -s "machine_start_gcode=$START" '
        + '-s "machine_end_gcode=$END" '
        + f"-l {c_stl}"
    )

    cmd = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "-v",
        f"{output_dir}:/work/output",
        "--entrypoint",
        "/bin/bash",
        image,
        "-c",
        inner_cmd,
    ]

    from estampo import ui

    log.info("Slicing via Docker (%s)", image)
    with ui.status("Slicing (CuraEngine)"):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    # Cleanup staging
    shutil.rmtree(staging, ignore_errors=True)

    if result.returncode != 0:
        combined = (result.stdout + "\n" + result.stderr).strip()
        log.error("CuraEngine output:\n%s", combined)
        raise EstampoError(f"CuraEngine failed (exit {result.returncode}):\n{combined[:500]}")

    output_gcode = output_dir / (stl_path.stem + ".gcode")
    if not output_gcode.exists() or output_gcode.stat().st_size < 100:
        combined = (result.stdout + "\n" + result.stderr).strip()
        raise EstampoError(f"CuraEngine produced no output:\n{combined[:500]}")

    log.info("CuraEngine output: %s (%d bytes)", output_gcode, output_gcode.stat().st_size)
    return output_dir


def cura_profile_from_config(
    overrides: dict[str, object] | None = None,
    bed_type: str | None = None,
    filament_type: str | None = None,
) -> CuraProfile:
    """Build a CuraProfile from estampo config overrides.

    Maps estampo-style override keys (which may use OrcaSlicer names) to
    CuraEngine equivalents where possible.
    """
    profile = CuraProfile()

    if bed_type:
        profile.bed_type = bed_type

    if filament_type:
        profile.filament_type = filament_type

    if overrides:
        # Map common OrcaSlicer override names to CuraProfile fields
        orca_to_cura = {
            "layer_height": "layer_height",
            "initial_layer_print_height": "layer_height_0",
            "wall_loops": "wall_line_count",
            "top_shell_layers": "top_layers",
            "bottom_shell_layers": "bottom_layers",
            "sparse_infill_density": "infill_sparse_density",
            "nozzle_temperature": "material_print_temperature",
            "bed_temperature": "material_bed_temperature",
        }
        cura_overrides: dict[str, str] = {}
        for key, value in overrides.items():
            if key in orca_to_cura:
                attr = orca_to_cura[key]
                if hasattr(profile, attr):
                    setattr(profile, attr, value)
            else:
                # Pass through as raw CuraEngine -s override
                cura_overrides[key] = str(value)

        if cura_overrides:
            profile.overrides = cura_overrides

    return profile

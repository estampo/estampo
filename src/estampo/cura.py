"""CuraEngine slicer backend.

Slices STL files using CuraEngine via Docker, with a proper Bambu Lab P1S
machine definition (inheriting from bambulab_base → fdmprinter).  Produces
plain G-code that can be packaged into .gcode.3mf.

Uses CuraEngine 5.12.0 built from source, packaged in a minimal Docker
image with bundled printer definitions.
"""

from __future__ import annotations

import importlib.resources
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from estampo import EstampoError

log = logging.getLogger(__name__)

DOCKERHUB_REPO = "estampo/estampo"
CURAENGINE_VERSION = "5.12.0"

# Definitions directory inside the Docker image (fdmprinter.def.json etc.)
_DEFS_DIR = "/opt/cura/definitions"

# Bundled BBL definition files shipped with estampo
_DATA_PKG = "estampo.data"
_BBL_DEFS = ("bambulab_base.def.json", "bambulab_p1s.def.json")


def _bundled_def_path(name: str) -> Path:
    """Return the filesystem path of a bundled definition file."""
    ref = importlib.resources.files(_DATA_PKG).joinpath(name)
    # importlib.resources may return a traversable; as_posix works for
    # files already on disk (installed via pip / editable).
    return Path(str(ref))


def cura_docker_image(version: str | None = None) -> str:
    """Return the Docker image name for a given CuraEngine version."""
    if version:
        return f"{DOCKERHUB_REPO}:cura-{version}"
    return f"{DOCKERHUB_REPO}:cura-{CURAENGINE_VERSION}"


@dataclass
class CuraProfile:
    """Slicer profile for CuraEngine targeting a BBL printer.

    Machine geometry and start/end G-code come from the bambulab_p1s
    definition file.  This profile controls process settings (layer
    height, speeds, temperatures, infill) passed as ``-s`` overrides.
    """

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


def _settings_flags(profile: CuraProfile) -> list[str]:
    """Build -s key=value flags from profile.

    Machine settings (bed size, heated bed, start/end gcode) are handled
    by the bambulab_p1s definition — only process/material settings here.
    """
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
        "material_print_temp_prepend": "false",
        "material_bed_temp_prepend": "false",
        # CuraEngine 5.12 requires these explicitly (not resolved from def)
        "roofing_layer_count": 0,
        "flooring_layer_count": 0,
    }
    pairs.update(profile.overrides)

    flags: list[str] = []
    for k, v in pairs.items():
        flags.extend(["-s", f"{k}={v}"])
    return flags


def _patch_gcode_header(gcode_path: Path, stderr: str) -> None:
    """Patch CuraEngine placeholder header with real values from stderr.

    Safety net for cases where CuraEngine doesn't seek back to update the
    G-code header after slicing.  With the source-built binary this should
    not be needed, but we keep it as a fallback.
    """
    m = re.search(
        r"Gcode header after slicing:\s*(;FLAVOR:.*?;TARGET_MACHINE\.NAME:\S+)",
        stderr,
        re.DOTALL,
    )
    if not m:
        log.debug("Could not find real header in CuraEngine stderr; skipping patch")
        return

    real_header = m.group(1).strip() + "\n"

    text = gcode_path.read_text()
    patched = re.sub(
        r";FLAVOR:.*?;TARGET_MACHINE\.NAME:\S+\n",
        real_header,
        text,
        count=1,
        flags=re.DOTALL,
    )
    if patched != text:
        gcode_path.write_text(patched)
        log.info("Patched G-code header with real values from CuraEngine stderr")
    else:
        log.debug("G-code header patch had no effect")


def slice_stl(
    stl_path: Path,
    output_dir: Path,
    profile: CuraProfile | None = None,
    image: str | None = None,
) -> Path:
    """Slice an STL file with CuraEngine and return the output directory.

    Uses Docker with the estampo/estampo:cura-X.Y.Z image.  The Bambu Lab
    P1S machine definition (bundled with estampo) provides machine geometry
    and start/end G-code; process settings come from the CuraProfile.

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

    staging = output_dir / ".cura-staging"
    staging.mkdir(exist_ok=True)

    # Copy bundled BBL definition files so CuraEngine can resolve the
    # bambulab_p1s → bambulab_base → fdmprinter inheritance chain.
    for def_name in _BBL_DEFS:
        shutil.copy2(_bundled_def_path(def_name), staging / def_name)

    # Copy STL into staging so it's accessible via volume mount
    shutil.copy2(stl_path, staging / stl_path.name)

    # Container paths (output_dir mounted at /work/output)
    c_staging = "/work/output/.cura-staging"
    c_stl = f"{c_staging}/{stl_path.name}"
    c_output = "/work/output/" + stl_path.stem + ".gcode"

    # Build the CuraEngine command.
    # -d adds search paths for definition file resolution (inherits chain).
    # -j loads the P1S definition (machine geometry + start/end gcode).
    # -g starts a mesh group, -e0 sets extruder 0 context for per-extruder
    # settings (material_diameter etc.) that CuraEngine requires.
    settings = _settings_flags(profile)
    settings_str = " ".join(f'"{s}"' for s in settings)
    inner_cmd = (
        f"CuraEngine slice "
        f"-d {c_staging}:{_DEFS_DIR}:/opt/cura/extruders "
        f"-j {c_staging}/bambulab_p1s.def.json "
        f"-o {c_output} "
        f"{settings_str} "
        f"-g -e0 {settings_str} "
        f"-l {c_stl}"
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

    _patch_gcode_header(output_gcode, result.stderr)

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

"""CuraEngine slicer backend.

Slices STL files using CuraEngine via Docker, with BBL-specific start/end
G-code injected from the Jinja2 templates in bambu-3mf. Produces plain
G-code that can be packaged into .gcode.3mf.

Prototype: uses rkneills/curaengine Docker image (CuraEngine ~3.6 era)
with fdmprinter.def.json from Cura 3.6.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from estampo import EstampoError

log = logging.getLogger(__name__)

DOCKER_IMAGE = "rkneills/curaengine:latest"
CURAENGINE_BIN = "/CuraEngine/build/CuraEngine"
FDMPRINTER_URL = (
    "https://raw.githubusercontent.com/Ultimaker/Cura/3.6/resources/definitions/fdmprinter.def.json"
)

# Base definitions directory inside the Docker image.
_DEFS_DIR = "/opt/defs"


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
    """Render P1S start/end G-code from Jinja2 templates.

    Returns (start_gcode, end_gcode) as rendered strings.
    """
    from bambu_3mf.templates import render_template

    bed_temp = profile.material_bed_temperature
    nozzle_temp = profile.material_print_temperature
    # The templates index into arrays like nozzle_temperature_initial_layer[0]
    context = {
        "bed_temperature_initial_layer_single": bed_temp,
        "nozzle_temperature_initial_layer": [nozzle_temp],
        "initial_extruder": 0,
        "filament_type": [profile.filament_type],
        "bed_temperature": [bed_temp],
        "bed_temperature_initial_layer": [bed_temp],
        "nozzle_temperature_range_high": [min(nozzle_temp + 15, 300)],
        "filament_max_volumetric_speed": [15.0],
        "outer_wall_volumetric_speed": 8.0,
        "curr_bed_type": profile.bed_type,
        "first_layer_print_min": [0, 0],
        "first_layer_print_size": [profile.machine_width, profile.machine_depth],
        "max_layer_z": 10.0,
    }

    start = render_template("p1s_start.gcode.j2", context)
    end = render_template("p1s_end.gcode.j2", context)
    return start, end


def _build_printer_def(
    profile: CuraProfile,
    start_gcode: str,
    end_gcode: str,
    extruder_def_path: str,
) -> dict:
    """Build a CuraEngine printer definition JSON."""
    return {
        "id": "bambu_p1s",
        "version": 2,
        "name": profile.machine_name,
        "inherits": "fdmprinter",
        "metadata": {
            "visible": True,
            "author": "estampo",
            "manufacturer": "Bambu Lab",
            "machine_extruder_trains": {"0": extruder_def_path},
        },
        "overrides": {
            "machine_name": {"default_value": profile.machine_name},
            "machine_width": {"default_value": profile.machine_width},
            "machine_depth": {"default_value": profile.machine_depth},
            "machine_height": {"default_value": profile.machine_height},
            "machine_heated_bed": {"default_value": profile.machine_heated_bed},
            "machine_center_is_zero": {"default_value": False},
            "machine_gcode_flavor": {"default_value": "RepRap (Marlin/Sprinter)"},
            "machine_start_gcode": {"default_value": start_gcode},
            "machine_end_gcode": {"default_value": end_gcode},
            "material_print_temp_prepend": {"default_value": False},
            "material_bed_temp_prepend": {"default_value": False},
        },
    }


def _build_extruder_def(profile: CuraProfile) -> dict:
    """Build a CuraEngine extruder definition JSON."""
    return {
        "id": "bambu_p1s_extruder_0",
        "version": 2,
        "name": "Extruder 0",
        "metadata": {
            "type": "extruder",
            "author": "estampo",
            "manufacturer": "Bambu Lab",
            "position": "0",
        },
        "settings": {
            "machine_settings": {
                "children": {
                    "extruder_nr": {
                        "label": "Extruder",
                        "description": "Extruder number.",
                        "type": "int",
                        "default_value": 0,
                    },
                    "machine_nozzle_offset_x": {
                        "label": "Nozzle X Offset",
                        "description": "X offset.",
                        "type": "float",
                        "default_value": 0,
                    },
                    "machine_nozzle_offset_y": {
                        "label": "Nozzle Y Offset",
                        "description": "Y offset.",
                        "type": "float",
                        "default_value": 0,
                    },
                    "machine_nozzle_size": {
                        "label": "Nozzle Diameter",
                        "description": "Nozzle diameter.",
                        "type": "float",
                        "default_value": profile.nozzle_diameter,
                    },
                    "material_diameter": {
                        "label": "Material Diameter",
                        "description": "Filament diameter.",
                        "type": "float",
                        "default_value": profile.material_diameter,
                    },
                    "machine_nozzle_id": {
                        "label": "Nozzle ID",
                        "description": "Nozzle ID.",
                        "type": "str",
                        "default_value": "unknown",
                    },
                    "machine_extruder_start_code": {
                        "label": "Extruder Start G-Code",
                        "description": "Start code.",
                        "type": "str",
                        "default_value": "",
                    },
                    "machine_extruder_end_code": {
                        "label": "Extruder End G-Code",
                        "description": "End code.",
                        "type": "str",
                        "default_value": "",
                    },
                    "machine_extruder_start_pos_abs": {
                        "label": "Start Pos Absolute",
                        "description": "Absolute.",
                        "type": "bool",
                        "default_value": False,
                    },
                    "machine_extruder_start_pos_x": {
                        "label": "Start Pos X",
                        "description": "X.",
                        "type": "float",
                        "default_value": 0,
                    },
                    "machine_extruder_start_pos_y": {
                        "label": "Start Pos Y",
                        "description": "Y.",
                        "type": "float",
                        "default_value": 0,
                    },
                    "machine_extruder_end_pos_abs": {
                        "label": "End Pos Absolute",
                        "description": "Absolute.",
                        "type": "bool",
                        "default_value": False,
                    },
                    "machine_extruder_end_pos_x": {
                        "label": "End Pos X",
                        "description": "X.",
                        "type": "float",
                        "default_value": 0,
                    },
                    "machine_extruder_end_pos_y": {
                        "label": "End Pos Y",
                        "description": "Y.",
                        "type": "float",
                        "default_value": 0,
                    },
                    "machine_extruder_cooling_fan_number": {
                        "label": "Fan Number",
                        "description": "Fan.",
                        "type": "int",
                        "default_value": 0,
                    },
                },
            },
        },
    }


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
        "machine_heated_bed": "true" if profile.machine_heated_bed else "false",
        "material_print_temp_prepend": "false",
        "material_bed_temp_prepend": "false",
        "adhesion_type": "none",
    }
    pairs.update(profile.overrides)

    flags: list[str] = []
    for k, v in pairs.items():
        flags.extend(["-s", f"{k}={v}"])
    return flags


def _ensure_fdmprinter(dest: Path) -> None:
    """Download fdmprinter.def.json from GitHub if not present."""
    if dest.exists() and dest.stat().st_size > 100_000:
        return

    import urllib.request

    log.info("Downloading fdmprinter.def.json from Cura 3.6...")
    urllib.request.urlretrieve(FDMPRINTER_URL, str(dest))
    if not dest.exists() or dest.stat().st_size < 100_000:
        raise EstampoError(f"Failed to download fdmprinter.def.json to {dest}")


def slice_stl(
    stl_path: Path,
    output_dir: Path,
    profile: CuraProfile | None = None,
) -> Path:
    """Slice an STL file with CuraEngine and return the output directory.

    Uses Docker with the rkneills/curaengine image. Injects BBL P1S
    start/end G-code via Jinja2 templates.

    Args:
        stl_path: Path to the input STL file.
        output_dir: Directory for output G-code.
        profile: Slicer profile. Defaults to P1S / PETG-CF / 0.2mm.

    Returns:
        The output directory (matching slicer.slice_plate contract).
    """
    if profile is None:
        profile = CuraProfile()

    stl_path = stl_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    output_gcode = output_dir / (stl_path.stem + ".gcode")

    # Render BBL start/end G-code
    start_gcode, end_gcode = _render_bbl_gcode(profile)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Write definitions
        extruder_def = _build_extruder_def(profile)
        extruder_path = tmp / "bambu_p1s_extruder_0.def.json"
        extruder_path.write_text(json.dumps(extruder_def, indent=2))

        printer_def = _build_printer_def(profile, start_gcode, end_gcode, "bambu_p1s_extruder_0")
        printer_path = tmp / "bambu_p1s.def.json"
        printer_path.write_text(json.dumps(printer_def, indent=2))

        # Download fdmprinter.def.json
        fdm_path = tmp / "fdmprinter.def.json"
        _ensure_fdmprinter(fdm_path)

        # Build baked Docker image (bind mounts don't work in all envs)
        dockerfile = tmp / "Dockerfile"
        dockerfile.write_text(
            f"FROM {DOCKER_IMAGE}\nCOPY . /opt/defs/\nCOPY {stl_path.name} /tmp/input.stl\n"
        )

        # Copy STL into build context
        shutil.copy2(stl_path, tmp / stl_path.name)

        # Build
        tag = "estampo-cura-tmp"
        build_cmd = ["docker", "build", "-t", tag, str(tmp)]
        log.info("Building CuraEngine Docker image")
        build_result = subprocess.run(build_cmd, capture_output=True, text=True, timeout=120)
        if build_result.returncode != 0:
            raise EstampoError(f"Docker build failed:\n{build_result.stderr[:500]}")

        # Slice — redirect stderr to /dev/null to keep only gcode on stdout
        slice_cmd = [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/bin/bash",
            tag,
            "-c",
            " ".join(
                [
                    CURAENGINE_BIN,
                    "slice",
                    "-j",
                    f"{_DEFS_DIR}/bambu_p1s.def.json",
                    "-o",
                    "/tmp/output.gcode",
                    *_settings_flags(profile),
                    "-l",
                    "/tmp/input.stl",
                    "2>/dev/null",
                    "&& cat /tmp/output.gcode",
                ]
            ),
        ]

        from estampo import ui

        log.info("Slicing with CuraEngine")
        with ui.status("Slicing (CuraEngine)"):
            slice_result = subprocess.run(slice_cmd, capture_output=True, timeout=300)

        if slice_result.returncode != 0:
            stderr = slice_result.stderr.decode(errors="replace") if slice_result.stderr else ""
            stdout = slice_result.stdout.decode(errors="replace") if slice_result.stdout else ""
            raise EstampoError(
                f"CuraEngine failed (exit {slice_result.returncode}):\n{stderr[:500]}\n"
                f"{stdout[:500]}"
            )

        gcode = slice_result.stdout
        if not gcode or len(gcode) < 100:
            stderr = slice_result.stderr.decode(errors="replace") if slice_result.stderr else ""
            raise EstampoError(f"CuraEngine produced no output:\n{stderr[:500]}")

        output_gcode.write_bytes(gcode)
        log.info("CuraEngine output: %s (%d bytes)", output_gcode, len(gcode))

        # Cleanup temp image
        subprocess.run(["docker", "rmi", tag], capture_output=True, timeout=30)

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

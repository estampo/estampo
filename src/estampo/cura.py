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
        r"Gcode header after slicing:\s*(;FLAVOR:.*?;TARGET_MACHINE\.NAME:.+)",
        stderr,
        re.DOTALL,
    )
    if not m:
        log.debug("Could not find real header in CuraEngine stderr; skipping patch")
        return

    real_header = m.group(1).strip() + "\n"

    text = gcode_path.read_text()
    patched = re.sub(
        r";FLAVOR:.*?;TARGET_MACHINE\.NAME:[^\n]+\n",
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


def _place_on_bed(stl_path: Path, staging_dir: Path) -> Path:
    """Copy STL into staging, ensuring the mesh sits on the bed (Z≥0).

    CuraEngine only slices geometry above Z=0.  If the mesh minimum Z
    is negative (common for origin-centered models), shift it up so
    the lowest vertex touches Z=0.
    """
    import trimesh

    mesh: trimesh.Trimesh = trimesh.load(str(stl_path), force="mesh")  # type: ignore[assignment]
    z_min = float(mesh.bounds[0][2])
    if z_min < 0:
        mesh.vertices[:, 2] -= z_min
        log.info("Shifted mesh up by %.2fmm to place on bed", -z_min)
    out = staging_dir / stl_path.name
    mesh.export(str(out), file_type="stl")
    return out


def _substitute_gcode_templates(gcode_path: Path, profile: CuraProfile) -> None:
    """Replace OrcaSlicer-style ``{variable}`` placeholders in G-code.

    CuraEngine emits start/end G-code verbatim from the machine
    definition — it does not resolve ``{material_bed_temperature_layer_0}``
    and similar template variables.  This function substitutes them with
    values from the profile.
    """
    text = gcode_path.read_text()

    replacements = {
        "material_bed_temperature_layer_0": str(profile.material_bed_temperature),
        "material_bed_temperature": str(profile.material_bed_temperature),
        "material_print_temperature_layer_0": str(profile.material_print_temperature),
        "material_print_temperature": str(profile.material_print_temperature),
    }

    changed = False
    for key, value in replacements.items():
        # Simple {key} replacement
        placeholder = "{" + key + "}"
        if placeholder in text:
            text = text.replace(placeholder, value)
            changed = True

    # Handle expressions like {material_print_temperature_layer_0 - 20}
    def _eval_expr(m: re.Match[str]) -> str:
        expr = m.group(1).strip()
        for k, v in replacements.items():
            expr = expr.replace(k, v)
        try:
            return str(int(eval(expr)))  # noqa: S307
        except Exception:
            return m.group(0)

    text, n = re.subn(r"\{([^}]*\b(?:material_\w+)\b[^}]*)\}", _eval_expr, text)
    if n > 0:
        changed = True

    # Handle conditionals: {if condition}...{endif}
    # Simple approach: evaluate the condition and keep/remove the block
    def _eval_conditional(m: re.Match[str]) -> str:
        condition = m.group(1).strip()
        body = m.group(2)
        # Replace known variables in condition
        cond_eval = condition
        cond_eval = cond_eval.replace(
            "machine_buildplate_type",
            repr(profile.bed_type.lower().replace(" ", "_")),
        )
        try:
            if eval(cond_eval):  # noqa: S307
                return body
        except Exception:
            pass
        return ""

    text, n_cond = re.subn(
        r"\{if\s+([^}]+)\}(.*?)\{endif\}",
        _eval_conditional,
        text,
        flags=re.DOTALL,
    )

    if changed or n > 0 or n_cond > 0:
        gcode_path.write_text(text)
        log.info("Substituted template variables in G-code")


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

    # Place mesh on the build plate (Z≥0) before slicing.  STL files
    # centered at origin (e.g. Z from -5 to +5) would lose the bottom
    # half because CuraEngine only slices above Z=0.
    staged_stl = _place_on_bed(stl_path, staging)

    # Container paths (output_dir mounted at /work/output)
    c_staging = "/work/output/.cura-staging"
    c_stl = f"{c_staging}/{staged_stl.name}"
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
    _substitute_gcode_templates(output_gcode, profile)

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
                # OrcaSlicer key name → CuraProfile attribute
                attr = orca_to_cura[key]
                if hasattr(profile, attr):
                    setattr(profile, attr, value)
            elif hasattr(profile, key):
                # Native CuraEngine key that matches a CuraProfile attribute
                setattr(profile, key, value)
            else:
                # Pass through as raw CuraEngine -s override
                cura_overrides[key] = str(value)

        if cura_overrides:
            profile.overrides = cura_overrides

    return profile

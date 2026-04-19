"""Slicer dispatch — routes to engine-specific modules (orca, cura)."""

from __future__ import annotations

import logging
from pathlib import Path

from estampo import EstampoError
from estampo.gcode import parse_gcode_metadata

# Re-export OrcaSlicer symbols for backward compatibility.
# Tests and scripts may import these from estampo.slicer.
from estampo.orca import (  # noqa: F401, E402
    _apply_overrides,
    _check_slicer_version,
    _detect_slicer_version,
    _resolve_profiles,
    _slice_via_docker,
    _write_tmp_profile,
    docker_image,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Slicer discovery (shared across engines)
# ---------------------------------------------------------------------------


def _get_engine_module(engine: str):  # noqa: ANN202
    """Return the engine module for the given engine key."""
    from estampo import cura, orca

    engines = {"orca": orca, "cura": cura}
    if engine not in engines:
        raise ValueError(f"Unknown slicer engine: '{engine}'. Supported: {list(engines)}")
    return engines[engine]


def find_slicer(engine: str) -> Path:
    """Find the slicer executable for the given engine.

    Delegates to the engine module's ``find_binary()`` function.
    """
    return _get_engine_module(engine).find_binary()


# ---------------------------------------------------------------------------
# Printer-specific post-processing
# ---------------------------------------------------------------------------


def find_deliverable(sliced_output_dir: Path) -> Path:
    """Find the deliverable file in slicer output.

    Returns the first .gcode.3mf or .gcode file found.
    For Bambu-specific post-processing, use ``bambox repack`` as a
    command stage in the pipeline.
    """
    sliced_3mfs = sorted(
        sliced_output_dir.glob("*_sliced.gcode.3mf"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if sliced_3mfs:
        return sliced_3mfs[0]

    gcode_files = sorted(
        sliced_output_dir.glob("*.gcode"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if gcode_files:
        return gcode_files[0]

    raise EstampoError(
        f"No sliced output found in {sliced_output_dir} — expected a .gcode.3mf or "
        f".gcode file. Check that the slice stage completed successfully."
    )


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
        import numpy as np
        import trimesh

        from estampo.cura import (
            build_cura_config,
            cura_docker_image,
            resolve_cura_bed_size,
            resolve_cura_center_is_zero,
            slice_stl_multi,
        )

        if output_dir is None:
            output_dir = input_3mf.parent / "output"
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        if isinstance(filaments, dict):
            filament_type = next(iter(filaments.values()), None)
        elif filaments:
            filament_type = filaments[0]
        else:
            filament_type = None

        cura_overrides, cura_per_extruder = build_cura_config(
            overrides=overrides,
            bed_type=bed_type,
            filament_type=filament_type,
            filaments=filaments if isinstance(filaments, list) else None,
            printer=printer,
            project_dir=project_dir,
            profiles_dir=profiles_dir,
        )
        image = cura_docker_image(docker_version or required_version)

        scene = trimesh.load(str(input_3mf))
        if isinstance(scene, trimesh.Scene):
            meshes: list[trimesh.Trimesh] = list(scene.dump(concatenate=False))  # type: ignore[arg-type]
        else:
            meshes = [scene]  # type: ignore[list-item]

        if not meshes:
            raise EstampoError(f"No geometry found in {input_3mf}")

        if filament_ids and len(filament_ids) == len(meshes):
            extruder_ids = [fid - 1 for fid in filament_ids]
        else:
            if filament_ids and len(filament_ids) != len(meshes):
                log.warning(
                    "filament_ids length (%d) does not match scene geometry count (%d) "
                    "— assigning all meshes to extruder 0",
                    len(filament_ids),
                    len(meshes),
                )
            extruder_ids = [0] * len(meshes)

        bed_w, bed_d = resolve_cura_bed_size(printer or "", project_dir, profiles_dir)
        center_is_zero = resolve_cura_center_is_zero(printer or "", project_dir, profiles_dir)
        target_x = 0.0 if center_is_zero else bed_w / 2
        target_y = 0.0 if center_is_zero else bed_d / 2

        bounds = np.array([m.bounds for m in meshes])
        group_min = bounds[:, 0, :].min(axis=0)
        group_max = bounds[:, 1, :].max(axis=0)
        dx = float(target_x - (group_min[0] + group_max[0]) / 2)
        dy = float(target_y - (group_min[1] + group_max[1]) / 2)
        dz = float(-group_min[2]) if group_min[2] < 0 else 0.0

        # Diagnostic for #621: surface inputs + delta so a single slice
        # reveals whether a +bed/2 shift is coming from the resolver, the
        # bed size, or from CuraEngine re-interpreting the STL.
        log.info(
            "cura placement: bed=(%.1f,%.1f) center_is_zero=%s "
            "target=(%.1f,%.1f) group=(%.1f..%.1f, %.1f..%.1f) "
            "delta=(%.2f,%.2f,%.2f)",
            bed_w,
            bed_d,
            center_is_zero,
            target_x,
            target_y,
            group_min[0],
            group_max[0],
            group_min[1],
            group_max[1],
            dx,
            dy,
            dz,
        )

        stl_dir = output_dir / ".cura-parts"
        stl_dir.mkdir(exist_ok=True)
        stl_meshes: list[tuple[int, Path]] = []
        for i, (ext_idx, mesh) in enumerate(zip(extruder_ids, meshes)):
            positioned = mesh.copy()
            positioned.vertices[:, 0] += dx
            positioned.vertices[:, 1] += dy
            positioned.vertices[:, 2] += dz
            stl_path = stl_dir / f"part_{i}.stl"
            positioned.export(str(stl_path), file_type="stl")
            stl_meshes.append((ext_idx, stl_path))

        return slice_stl_multi(
            stl_meshes,
            output_dir,
            overrides=cura_overrides,
            per_extruder=cura_per_extruder,
            image=image,
            printer=printer,
            project_dir=project_dir,
            profiles_dir=profiles_dir,
            local=local,
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

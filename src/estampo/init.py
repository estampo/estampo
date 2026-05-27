"""estampo init and validate commands."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from estampo import EstampoError
from estampo.config import DEFAULT_STAGES, SUPPORTED_EXTENSIONS

if TYPE_CHECKING:
    from estampo.config import EstampoConfig

log = logging.getLogger(__name__)

# Source of truth: BedType enum + curr_bed_type enum_values in OrcaSlicer
# libslic3r/PrintConfig.{hpp,cpp}. Order must match the enum so menu indexes
# are stable. Update when bumping the pinned Orca version.
BED_TYPES = [
    "Cool Plate",
    "Engineering Plate",
    "High Temp Plate",
    "Textured PEI Plate",
    "Textured Cool Plate",
    "Supertack Plate",
]

# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

_TEMPLATE = """\
# estampo.toml — reproducible 3D print pipeline config
# Docs: https://github.com/estampo/estampo/blob/main/docs/config.md

[pipeline]
# Stages to run: load, arrange, plate, slice
stages = ["load", "arrange", "plate", "slice"]

[plate]
size = [256, 256]       # bed size in mm [x, y]
padding = 5.0           # gap between parts in mm

[slicer]
engine = "orca"                            # "orca" (OrcaSlicer) or "cura" (CuraEngine)
# version = "2.3.1"                        # pin slicer version for reproducibility
# bed_type = "Textured PEI Plate"          # run `estampo info` for the full list

# OrcaSlicer profile chain:
[slicer.orca]
printer = "My Printer 0.4 nozzle"          # machine profile name
process = "0.20mm Standard @base"          # process/quality profile
filaments = ["Generic PLA @base"]          # filament profiles (one per slot)

# Per-slot filament mapping (alternative to filaments list):
# [slicer.orca.slots]
# 1 = "Generic PLA @base"
# 2 = "Generic PETG @base"

# Machine profile overrides (e.g. if you upgraded your nozzle):
# [slicer.orca.machine_overrides]
# nozzle_type = "hardened_steel"   # brass, stainless_steel, or hardened_steel

# OrcaSlicer setting overrides:
# [slicer.orca.overrides]
# sparse_infill_density = "25%"
# wall_loops = 3

# CuraEngine overrides (used when engine = "cura"):
# [slicer.cura.overrides]
# infill_sparse_density = 25
# support_structure = "tree"

[[parts]]
file = "my-part.stl"          # path relative to this file
copies = 1                     # number of copies
orient = "flat"                # flat, upright, side, or upside-down
# filament = "Generic PLA @base"  # filament name or slot number (default: 1)
# scale = 1.0                     # uniform scale factor
# rotate = [0, 0, 45]            # [rx, ry, rz] in degrees (overrides orient)
# sequence = 1                    # print order for sequential printing

# Add more parts:
# [[parts]]
# file = "another-part.step"
# copies = 2
# orient = "upright"
"""


def dump_template() -> str:
    """Return the commented TOML template string."""
    return _TEMPLATE


# ---------------------------------------------------------------------------
# GitHub Actions workflow generation
# ---------------------------------------------------------------------------

_WORKFLOW_TEMPLATE = """\
name: Slice
on: [push, pull_request]

jobs:
  slice:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: estampo/estampo/action@main
        with:
          config: {config}
"""


def generate_workflow(config_path: str = "estampo.toml") -> str:
    """Return a GitHub Actions workflow YAML for slicing."""
    return _WORKFLOW_TEMPLATE.format(config=config_path)


def write_workflow(config_path: str = "estampo.toml") -> Path:
    """Write a GitHub Actions slice workflow and return the path."""
    from estampo import ui

    workflow_dir = Path(".github/workflows")
    workflow_dir.mkdir(parents=True, exist_ok=True)
    dest = workflow_dir / "slice.yml"
    if dest.exists():
        ui.warn(f"{dest} already exists — skipping workflow generation")
        return dest
    dest.write_text(generate_workflow(config_path))
    ui.success(f"Wrote {dest}")
    return dest


# ---------------------------------------------------------------------------
# Load existing config for pre-population
# ---------------------------------------------------------------------------


@dataclass
class _ExistingConfig:
    """Pre-populated values from an existing estampo.toml."""

    project_name: str | None = None
    printer: str | None = None
    process: str | None = None
    filaments: list[str] | None = None
    bed_type: str | None = None
    nozzle_type: str | None = None
    slicer_version: str | None = None
    plate_size: tuple[int, int] | None = None
    overrides: dict[str, str] | None = None
    parts: list[dict] | None = None
    stages: list[str] | None = None


def _load_existing(path: Path) -> _ExistingConfig | None:
    """Try to load an existing estampo.toml for pre-population."""
    import tomllib

    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        log.debug("Failed to read existing config %s", path, exc_info=True)
        return None

    slicer = raw.get("slicer", {})
    plate = raw.get("plate", {})
    pipeline = raw.get("pipeline", {})

    parts = None
    raw_parts = raw.get("parts", [])
    if raw_parts:
        parts = [{"file": p.get("file", ""), **p} for p in raw_parts]

    orca = slicer.get("orca") or {}
    cura = slicer.get("cura") or {}
    printer_val = orca.get("printer")
    process_val = orca.get("process")
    filaments_val = orca.get("filaments")
    nozzle_type = orca.get("machine_overrides", {}).get("nozzle_type")
    overrides = orca.get("overrides") or cura.get("overrides")

    if overrides:
        overrides = {k: str(v) for k, v in overrides.items()}

    plate_raw = plate.get("size")
    plate_size = None
    if isinstance(plate_raw, list) and len(plate_raw) == 2:
        plate_size = (int(plate_raw[0]), int(plate_raw[1]))

    return _ExistingConfig(
        project_name=raw.get("name"),
        printer=printer_val,
        process=process_val,
        filaments=filaments_val,
        bed_type=slicer.get("bed_type"),
        nozzle_type=nozzle_type,
        slicer_version=slicer.get("version"),
        plate_size=plate_size,
        overrides=overrides,
        parts=parts,
        stages=pipeline.get("stages"),
    )


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Result of config validation with passes, warnings, and errors."""

    passes: list[str]
    warnings: list[str]
    errors: list[str] | None = None

    def __iter__(self):  # type: ignore[override]
        """Iterate over warnings for backward compatibility."""
        return iter(self.warnings)


def _check_profile_type(name: str, engine: str, category: str) -> str | None:
    """Check the JSON 'type' field of a profile file, if it exists.

    Returns the type string (e.g. 'machine', 'machine_model'), or None if not found.
    """
    import json

    from estampo.profiles import SYSTEM_DIRS

    base = SYSTEM_DIRS.get(engine)
    if not base:
        return None
    path = base / category / f"{name}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f).get("type")
    except (json.JSONDecodeError, OSError):
        return None


def _check_orca_process_compat(
    printer: str, process: str, project_dir: Path, profiles_dir: str
) -> str | None:
    """Verify the process's ``compatible_printers`` list contains *printer*.

    Loads the flattened process profile (pinned → system → bundled) and reads
    the resolved ``compatible_printers`` list. Returns a warning string if the
    printer is missing from the list, otherwise ``None``.

    Returns ``None`` when compatibility cannot be determined (process file not
    readable, or ``compatible_printers_condition`` is set — a dynamic Orca
    expression we can't evaluate statically).
    """
    from estampo.profiles import resolve_profile_data

    try:
        data = resolve_profile_data(
            process, "orca", "process", project_dir=project_dir, profiles_dir=profiles_dir
        )
    except (EstampoError, FileNotFoundError, OSError):
        return None

    if data.get("compatible_printers_condition"):
        return None

    compat = data.get("compatible_printers")
    if not compat or not isinstance(compat, list):
        return None

    if printer in compat:
        return None

    compat_str = ", ".join(f"'{p}'" for p in compat)
    return (
        f"slicer.process '{process}' is not compatible with slicer.printer '{printer}'.\n"
        f"  Process's compatible_printers: {compat_str}.\n"
        f"  Note: this combination fails at slice time with a silent exit 239.\n"
        f"  Fix: pick a process whose compatible_printers includes '{printer}', "
        f"or choose a different printer."
    )


# Conservative flow ceiling that any generic/third-party PLA-class filament can
# sustain through a stock 0.4mm hotend. Bambu Lab's own profiles assume their
# in-house filament and set the limit at 21+ mm³/s, which under-extrudes badly
# when fed generic filament — the hotend physically can't melt that fast.
_GENERIC_FLOW_CEILING_MM3S = 15.0


def _filament_max_vol_speed(data: dict) -> float | None:
    """Return the filament_max_volumetric_speed as a float, or None if missing/unparseable.

    OrcaSlicer stores the value as a stringly-typed list (e.g. ``["21"]``) or a
    bare string. Take the first entry and coerce to float.
    """
    raw = data.get("filament_max_volumetric_speed")
    if raw is None:
        return None
    if isinstance(raw, list):
        if not raw:
            return None
        raw = raw[0]
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _check_filament_vendor_lock(
    filament: str, engine: str, project_dir: Path, profiles_dir: str
) -> str | None:
    """Warn when a filament profile assumes a flow rate only the matching vendor's
    own filament can sustain.

    Vendor-branded profiles (``Bambu PLA Basic``, ``Polymaker ...``, etc.) are
    calibrated for that vendor's actual filament — including a high
    ``filament_max_volumetric_speed`` (often 21 mm³/s). Feeding generic or
    third-party filament through such a profile causes severe under-extrusion
    because the hotend can't physically melt the planned flow rate; walls come
    out wavy and features fail. ``estampo run`` has no way to know what
    filament is actually loaded, so this warning fires whenever the resolved
    flow ceiling exceeds the generic-safe value — telling the user to either
    override ``filament_max_volumetric_speed`` or pick a ``Generic ...``
    profile if the filament is not the vendor's own.
    """
    if engine != "orca":
        return None

    from estampo.profiles import resolve_profile_data

    try:
        data = resolve_profile_data(
            filament, "orca", "filament", project_dir=project_dir, profiles_dir=profiles_dir
        )
    except (EstampoError, FileNotFoundError, OSError):
        return None

    vol = _filament_max_vol_speed(data)
    if vol is None or vol <= _GENERIC_FLOW_CEILING_MM3S:
        return None

    return (
        f"filament '{filament}' sets filament_max_volumetric_speed = {vol:g} mm³/s, "
        f"which is calibrated for that vendor's own filament. Generic/third-party "
        f"filament cannot sustain that flow rate — a stock 0.4mm hotend tops out "
        f"around {_GENERIC_FLOW_CEILING_MM3S:g} mm³/s for generic PLA — and the "
        f"slicer will plan for a flow the hotend can't deliver, causing "
        f"under-extrusion (wavy walls, missed features, failed in-place parts).\n"
        f"  Fix one of:\n"
        f"    - If using the matching vendor filament, ignore this warning.\n"
        f"    - If using generic/third-party filament, switch to a 'Generic <type>' "
        f"profile (e.g. 'Generic PLA @base'), or override "
        f"filament_max_volumetric_speed to {int(_GENERIC_FLOW_CEILING_MM3S)} or below."
    )


def _check_cura_def_reachable(printer: str, project_dir: Path, profiles_dir: str) -> str | None:
    """Warn when a Cura printer name is known but the def.json isn't local.

    The bundled Cura name manifest enumerates every machine present in the
    Docker image, including non-stock definitions (e.g. ``bambox_p1s``).
    Their ``.def.json`` files are not shipped in the estampo pip package,
    so a slice without Docker (local fallback) would fail with a definition
    -not-found error.  Flag this at validate time instead of letting run
    surface it.

    URL or filesystem-path printers are treated as reachable — the
    downstream resolver fetches/reads them directly.
    """
    from estampo.cura import _printer_is_file, _printer_is_url, _resolve_def_chain_for_printer

    if _printer_is_url(printer) or _printer_is_file(printer, project_dir):
        return None

    chain = _resolve_def_chain_for_printer(printer, project_dir, profiles_dir)
    if chain:
        return None

    return (
        f"slicer.printer '{printer}' is known to the CuraEngine Docker image "
        f"but no matching definition file is reachable locally (neither pinned "
        f"under {profiles_dir}/cura/definitions/ nor bundled with estampo).\n"
        f"  Without Docker (e.g. `estampo run --local`), slice will fail.\n"
        f"  Fix: run 'estampo profiles pin' to extract the definition from the "
        f"Docker image, or drop '{printer}.def.json' into {profiles_dir}/cura/definitions/."
    )


def validate_config(path: Path) -> ValidationResult:
    """Validate an estampo.toml and return passes and warnings.

    Raises EstampoError for hard errors (via load_config).
    Returns a ValidationResult with passes and warnings.
    """
    import tomllib

    from estampo.config import detect_unknown_keys, load_config
    from estampo.pipeline import STAGE_OUTPUTS
    from estampo.profiles import discover_profile_names, validate_override_keys

    cfg = load_config(path)
    passes: list[str] = []
    warnings: list[str] = []

    with open(path, "rb") as f:
        raw_toml = tomllib.load(f)
    warnings.extend(detect_unknown_keys(raw_toml))

    # Check slicer version pinning
    if not cfg.slicer.version:
        warnings.append(
            'slicer.version is not set — pin it for reproducible builds (e.g. version = "2.3.1")'
        )
    else:
        passes.append(f"Slicer version pinned: {cfg.slicer.version}")

    # Check profile names — system → pinned → bundled
    profiles, source = discover_profile_names(
        cfg.slicer.engine,
        version=cfg.slicer.version,
        project_dir=cfg.base_dir,
        profiles_dir=cfg.slicer.profiles_dir,
    )

    active = cfg.slicer.active
    orca = cfg.slicer.orca if cfg.slicer.engine == "orca" else None

    profile_ok = True
    if source != "none":
        if active.printer:
            machines = profiles.get("machine", [])
            if machines and active.printer not in machines:
                close = _closest_match(active.printer, machines)
                hint = f" Did you mean '{close}'?" if close else ""
                # Check if it's a machine_model (wrong type)
                _is_model = _check_profile_type(active.printer, cfg.slicer.engine, "machine")
                if _is_model == "machine_model":
                    warnings.append(
                        f"slicer.printer '{active.printer}' is a printer model "
                        f"definition, not a slicer profile. Use the nozzle-specific "
                        f"variant, e.g. '{active.printer} 0.4 nozzle'.\n"
                        f"  Fix: run 'estampo profiles list --engine {cfg.slicer.engine}' "
                        f"to see available machine profiles."
                    )
                else:
                    pin_hint = ""
                    if source != "pinned":
                        pin_hint = (
                            " Run 'estampo profiles pin' to extract profiles from the Docker image."
                        )
                    warnings.append(
                        f"slicer.printer '{active.printer}' not found in "
                        f"{cfg.slicer.engine} profiles ({source}).{hint}{pin_hint}"
                    )
                profile_ok = False

        if orca and orca.process:
            processes = profiles.get("process", [])
            if processes and orca.process not in processes:
                close = _closest_match(orca.process, processes)
                hint = f" Did you mean '{close}'?" if close else ""
                pin_hint = ""
                if source != "pinned":
                    pin_hint = (
                        "\n  Fix: run 'estampo profiles pin' to extract profiles "
                        "from the Docker image."
                    )
                warnings.append(
                    f"slicer.process '{orca.process}' not found in "
                    f"{cfg.slicer.engine} profiles ({source}).{hint}{pin_hint}"
                )
                profile_ok = False

        filament_list = orca.filaments if orca else []
        known_filaments = profiles.get("filament", [])
        if known_filaments:
            for fil in filament_list:
                if fil not in known_filaments:
                    close = _closest_match(fil, known_filaments)
                    hint = f" Did you mean '{close}'?" if close else ""
                    pin_hint = ""
                    if source != "pinned":
                        pin_hint = (
                            "\n  Fix: run 'estampo profiles pin' to extract profiles "
                            "from the Docker image."
                        )
                    warnings.append(
                        f"slicer filament '{fil}' not found in "
                        f"{cfg.slicer.engine} profiles ({source}).{hint}{pin_hint}"
                    )
                    profile_ok = False
                else:
                    vendor_warn = _check_filament_vendor_lock(
                        fil, cfg.slicer.engine, cfg.base_dir, cfg.slicer.profiles_dir
                    )
                    if vendor_warn:
                        warnings.append(vendor_warn)

        if profile_ok:
            passes.append(f"Slicer profiles valid ({source})")

        # Cura-only: check that the printer definition file is reachable
        # locally.  The bundled Cura name manifest knows every printer
        # present in the Docker image (e.g. `bambox_p1s` from the
        # `cura-p1s` package), but the physical `<id>.def.json` for
        # non-stock definitions only lives in the Docker image — not in
        # estampo's pip bundle.  Without Docker the slice then fails with
        # a definition-not-found error, which `estampo validate` should
        # flag before the user ever hits run.
        if profile_ok and cfg.slicer.engine == "cura" and active.printer:
            reach_warning = _check_cura_def_reachable(
                active.printer, cfg.base_dir, cfg.slicer.profiles_dir
            )
            if reach_warning:
                warnings.append(reach_warning)

        # Check process/printer compatibility (OrcaSlicer only).
        # The pinned process JSON has a `compatible_printers` list. When the
        # active printer isn't in it, OrcaSlicer rejects the slice with
        # `run found error, return -17, exit...` which surfaces as exit 239.
        if profile_ok and orca and active.printer and orca.process:
            compat_warning = _check_orca_process_compat(
                active.printer, orca.process, cfg.base_dir, cfg.slicer.profiles_dir
            )
            if compat_warning:
                warnings.append(compat_warning)
            else:
                passes.append(
                    f"Process '{orca.process}' compatible with printer '{active.printer}'"
                )
    else:
        warnings.append(
            f"slicer profile names could not be validated — no {cfg.slicer.engine} "
            f"profiles available (not installed locally, no pinned or bundled profiles).\n"
            f"  Fix: run 'estampo profiles pin' to extract profiles from the Docker image."
        )

    # Check slicer override keys against process profile
    errors: list[str] = []
    if active.overrides:
        override_warnings = validate_override_keys(
            active.overrides,
            cfg.slicer.engine,
            orca.process if orca else None,
            project_dir=cfg.base_dir,
        )
        if override_warnings:
            errors.extend(override_warnings)
        else:
            passes.append(f"Slicer override keys valid ({len(active.overrides)} override(s))")

    # Check for absolute part paths (check raw TOML value, not resolved path)
    import tomllib

    with open(path, "rb") as f:
        raw = tomllib.load(f)
    for i, p in enumerate(raw.get("parts", [])):
        raw_file = p.get("file", "")
        if raw_file and Path(raw_file).is_absolute():
            warnings.append(
                f"parts[{i}].file is an absolute path — consider making it relative for portability"
            )

    # Check part files: readability, extension, duplicates
    # (existence and orient are already hard errors in load_config)
    seen_files: set[str] = set()
    parts_ok = True
    for i, part in enumerate(cfg.parts):
        part_path = part.file

        # Check readability (file exists at this point — load_config validated that)
        if not os.access(part_path, os.R_OK):
            warnings.append(f"parts[{i}].file '{part_path}' is not readable")
            parts_ok = False

        # Check file extension
        ext = part_path.suffix.lower()
        if ext and ext not in SUPPORTED_EXTENSIONS:
            warnings.append(
                f"parts[{i}].file has unsupported extension '{ext}' "
                f"— expected one of {sorted(SUPPORTED_EXTENSIONS)}"
            )
            parts_ok = False

        # Check for duplicate files
        canon = str(part_path)
        if canon in seen_files:
            warnings.append(f"parts[{i}].file '{part_path.name}' appears more than once")
            parts_ok = False
        seen_files.add(canon)

    n = len(cfg.parts)
    if parts_ok:
        passes.append(f"{n} part file{'s' if n != 1 else ''} readable")

    # Check plate dimensions
    width, depth = cfg.plate.size
    plate_ok = True
    if width < 50 or depth < 50:
        warnings.append(
            f"plate.size [{width}, {depth}] seems very small — most beds are at least 100mm"
        )
        plate_ok = False
    if width > 1000 or depth > 1000:
        warnings.append(f"plate.size [{width}, {depth}] seems very large — check units are in mm")
        plate_ok = False
    if plate_ok:
        passes.append(f"Plate size {width:.0f}×{depth:.0f}mm")

    # Check pipeline stages
    stages_ok = True
    for stage in cfg.pipeline.stages:
        if stage not in STAGE_OUTPUTS and stage not in cfg.pipeline.command_stages:
            valid = sorted(STAGE_OUTPUTS.keys())
            warnings.append(
                f"pipeline stage '{stage}' is unknown.\n"
                f"  Built-in stages: {', '.join(valid)}.\n"
                f"  For custom stages, add a [{stage}] section with a 'command' key."
            )
            stages_ok = False

    # Check pipeline stage ordering
    stage_order = list(STAGE_OUTPUTS.keys())
    prev_idx = -1
    for stage in cfg.pipeline.stages:
        if stage in stage_order:
            idx = stage_order.index(stage)
            if idx < prev_idx:
                warnings.append(
                    f"pipeline stage '{stage}' is out of order — expected after "
                    f"'{stage_order[prev_idx]}'"
                )
                stages_ok = False
            prev_idx = idx

    if stages_ok:
        passes.append(f"Pipeline: {' → '.join(cfg.pipeline.stages)}")

    # Check command stage executables
    import shutil

    for stage_name, stage_cfg in cfg.pipeline.command_stages.items():
        executable = stage_cfg.command.split()[0]
        if not stage_cfg.docker and shutil.which(executable) is None:
            warnings.append(
                f"command stage '{stage_name}' uses '{executable}' which is not "
                f"on PATH.\n"
                f"  Fix: add 'docker = true' to [{stage_name}] to run it inside "
                f"the slicer Docker image, or install '{executable}' locally."
            )

    # Check CuraEngine definitions for unresolved template variables
    if cfg.slicer.engine == "cura" and active.printer and "slice" in cfg.pipeline.stages:
        _check_cura_template_gcode(cfg, warnings, errors)

    return ValidationResult(passes=passes, warnings=warnings, errors=errors or None)


def _check_cura_template_gcode(
    cfg: "EstampoConfig",
    warnings: list[str],
    errors: list[str],
) -> None:
    """Warn if CuraEngine start gcode has template variables but no resolve stage."""
    import json
    import re

    from estampo.cura import _resolve_def_chain, _resolve_def_name

    try:
        def_id = _resolve_def_name(cfg.slicer.active.printer)
    except Exception:
        return  # can't resolve — other warnings will cover this

    chain = _resolve_def_chain(def_id, cfg.base_dir, cfg.slicer.profiles_dir)
    if not chain:
        return

    # Read start gcode from the leaf definition
    try:
        with open(chain[0]) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    start_gcode = data.get("overrides", {}).get("machine_start_gcode", {})
    gcode_text = start_gcode.get("default_value", "")
    if not gcode_text:
        return

    # Check for CuraEngine template variables like {material_bed_temperature_layer_0}
    templates = re.findall(r"\{(\w+)\}", gcode_text)
    # Filter to likely CuraEngine setting names (not command stage variables)
    cura_templates = [t for t in templates if "_" in t and not t.startswith("if ")]
    if not cura_templates:
        return

    # Check if any pipeline stage resolves templates
    has_resolver = False
    for stage_name in cfg.pipeline.stages:
        if stage_name in cfg.pipeline.command_stages:
            cmd = cfg.pipeline.command_stages[stage_name].command
            if "resolve" in cmd.lower():
                has_resolver = True
                break

    if not has_resolver:
        examples = ", ".join(cura_templates[:3])
        errors.append(
            f"CuraEngine printer definition '{def_id}' uses template variables "
            f"in start gcode (e.g. {examples}) but the pipeline has no stage to "
            f"resolve them. Unresolved templates cause dangerous printer behavior.\n"
            f"  Fix: add a resolve_templates stage to your pipeline:\n"
            f"    [pipeline]\n"
            f'    stages = [..., "slice", "resolve_templates", "pack"]\n'
            f"\n"
            f"    [resolve_templates]\n"
            f'    command = "cura-p1s resolve {{sliced_dir}}/plate.gcode '
            f'--settings {{cura_settings}}"\n'
            f"    docker = true"
        )


def _closest_match(name: str, candidates: list[str]) -> str | None:
    """Return the closest matching string from candidates, or None."""
    if not candidates:
        return None
    name_lower = name.lower()
    # Try substring match first
    for c in candidates:
        if name_lower in c.lower() or c.lower() in name_lower:
            return c
    # Simple prefix match
    for c in candidates:
        if c.lower().startswith(name_lower[:8]):
            return c
    return None


# ---------------------------------------------------------------------------
# Interactive wizard
# ---------------------------------------------------------------------------


@dataclass
class _MachineInfo:
    """Information extracted from a machine profile."""

    plate_size: tuple[int, int] | None = None
    multi_material: bool = False


def _read_machine_info(profile_name: str, engine: str) -> _MachineInfo:
    """Extract build plate size and multi-material capability from a machine profile."""
    info = _MachineInfo()
    try:
        from estampo.profiles import resolve_profile_data

        data = resolve_profile_data(profile_name, engine, "machine")

        # Plate size from printable_area polygon (e.g. ["0x0", "256x0", "256x256", "0x256"])
        area = data.get("printable_area")
        if area and isinstance(area, list):
            max_x = max_y = 0
            for pt in area:
                parts = str(pt).split("x")
                if len(parts) == 2:
                    max_x = max(max_x, int(float(parts[0])))
                    max_y = max(max_y, int(float(parts[1])))
            if max_x > 0 and max_y > 0:
                info.plate_size = (max_x, max_y)

        # Multi-material support
        if data.get("single_extruder_multi_material"):
            info.multi_material = True
    except (OSError, KeyError, ValueError):
        log.debug("Failed to read machine info", exc_info=True)
    return info


# ---------------------------------------------------------------------------
# Common slicer overrides
# ---------------------------------------------------------------------------

# Each entry: (display_name, slicer_key, value_spec)
# value_spec is either ("text", "hint string") or ("choice", [...options])
# value_spec types:
#   ("choice", [...options])  — user picks from a list
#   ("percent", "hint")      — numeric, auto-appends % if missing
#   ("int", "hint")          — positive integer
#   ("float", "hint")        — positive float
#   ("text", "hint")         — free-form text (no validation)
OverrideSpec = tuple[str, str, tuple[str, str] | tuple[str, list[str]]]

COMMON_OVERRIDES: list[OverrideSpec] = [
    ("Infill density", "sparse_infill_density", ("percent", "e.g. 15, 25, 50")),
    (
        "Infill pattern",
        "sparse_infill_pattern",
        (
            "choice",
            [
                "grid",
                "gyroid",
                "honeycomb",
                "line",
                "cubic",
                "triangles",
                "concentric",
                "lightning",
            ],
        ),
    ),
    ("Wall loops", "wall_loops", ("int", "e.g. 2, 3, 4")),
    ("Layer height", "layer_height", ("float", "e.g. 0.12, 0.16, 0.20, 0.28")),
    (
        "Enable support",
        "enable_support",
        ("choice", ["0 (off)", "1 (on)"]),
    ),
    (
        "Support type",
        "support_type",
        ("choice", ["normal", "tree", "hybrid"]),
    ),
    ("Top shell layers", "top_shell_layers", ("int", "e.g. 3, 5")),
    ("Bottom shell layers", "bottom_shell_layers", ("int", "e.g. 3, 5")),
    (
        "Brim type",
        "brim_type",
        ("choice", ["no_brim", "outer_only", "inner_only", "outer_and_inner"]),
    ),
    (
        "Seam position",
        "seam_position",
        ("choice", ["nearest", "aligned", "back", "random"]),
    ),
]


def _validate_override(value: str, spec_type: str) -> str | None:
    """Validate and normalise an override value.

    Returns the normalised value, or ``None`` if invalid.
    """
    from estampo import ui

    value = value.strip()
    if not value:
        return None

    if spec_type == "percent":
        raw = value.rstrip("%").strip()
        try:
            num = float(raw)
        except ValueError:
            ui.warn(f"Expected a number, got '{value}'")
            return None
        if num < 0 or num > 100:
            ui.warn("Percentage must be between 0 and 100")
            return None
        # Auto-append %
        return f"{raw}%"

    if spec_type == "int":
        try:
            num = int(value)
        except ValueError:
            ui.warn(f"Expected an integer, got '{value}'")
            return None
        if num < 0:
            ui.warn("Value must be a positive integer")
            return None
        return str(num)

    if spec_type == "float":
        try:
            num = float(value)
        except ValueError:
            ui.warn(f"Expected a number, got '{value}'")
            return None
        if num <= 0:
            ui.warn("Value must be a positive number")
            return None
        return value

    # "text" or unknown — accept as-is
    return value


def _prompt_overrides() -> dict[str, str]:
    """Prompt user to add slicer overrides, returning key→value dict.

    Shows a numbered table of common overrides. User picks a number to
    configure that override, or enters N to finish.
    """
    from estampo import ui

    overrides: dict[str, str] = {}
    while True:
        # Build display list: common overrides + custom option
        items = [(name, key) for name, key, _ in COMMON_OVERRIDES]
        items.append(("Custom key...", ""))
        ui.choice_table(items, ["Name", "Slicer key"])

        raw_pick = ui.prompt_str("Pick override (or N to finish)", "n")
        if raw_pick.strip().lower() in ("n", "no", ""):
            break

        try:
            pick = int(raw_pick)
        except ValueError:
            ui.warn("Enter a number or N")
            continue

        idx = pick - 1
        if idx < 0 or idx > len(COMMON_OVERRIDES):
            ui.warn(f"Enter 1-{len(COMMON_OVERRIDES) + 1}")
            continue

        if idx == len(COMMON_OVERRIDES):
            # Custom key
            key = ui.prompt_str("Slicer key name")
            if not key:
                continue
            value = ui.prompt_str(f"Value for {key}")
            if value:
                overrides[key] = value
                ui.success(f'{key} = "{value}"')
        else:
            name, key, spec = COMMON_OVERRIDES[idx]
            ui.success(name)

            if spec[0] == "choice" and isinstance(spec[1], list):
                choices = spec[1]
                ui.choice_table([(c,) for c in choices], ["Option"])
                cpick = ui.prompt_int("Pick value", 1)
                cidx = cpick - 1
                if 0 <= cidx < len(choices):
                    raw = choices[cidx]
                    # Strip parenthetical hints like "0 (off)" → "0"
                    value = raw.split(" (")[0] if " (" in raw else raw
                    overrides[key] = value
                    ui.success(f'{key} = "{value}"')
                else:
                    ui.warn(f"Enter 1-{len(choices)}")
                    continue
            else:
                hint = spec[1]
                spec_type = spec[0]
                raw = ui.prompt_str(f"Value for {key} ({hint})")
                validated = _validate_override(raw, spec_type) if raw else None
                if validated:
                    overrides[key] = validated
                    ui.success(f'{key} = "{validated}"')
                elif raw:
                    continue  # validation failed, loop back

        ui.console.print()

    return overrides


def _wizard_pick_profiles(
    engine: str,
    profiles: dict[str, list[str]],
) -> tuple[str | None, str | None, _MachineInfo]:
    """Steps 3/4: Pick printer profile and process profile.

    Returns ``(printer_profile, process_profile, machine_info)``.
    """
    from estampo import ui

    # --- Step 3: Pick printer profile ---
    printer_profile = None
    machine_info = _MachineInfo()
    machines = sorted(profiles.get("machine", []))
    if machines:
        ui.heading("Printer Profile")
        chosen = ui.pick(machines, prompt="Pick a printer profile")
        printer_profile = machines[chosen[0]]
        machine_info = _read_machine_info(printer_profile, engine)
        ui.console.print()
    else:
        printer_profile = ui.prompt_str("Printer profile name (e.g. 'My Printer 0.4 nozzle')")
        ui.console.print()

    # --- Step 4: Pick process profile ---
    process_profile = None
    processes = sorted(profiles.get("process", []))
    if processes:
        ui.heading("Process Profile")
        chosen = ui.pick(processes, prompt="Pick a process profile")
        process_profile = processes[chosen[0]]
        ui.console.print()
    else:
        process_profile = ui.prompt_str("Process profile name (e.g. '0.20mm Standard @base')")
        ui.console.print()

    return printer_profile, process_profile, machine_info


def _wizard_pick_filaments(
    profiles: dict[str, list[str]],
    machine_info: _MachineInfo,
) -> list[str]:
    """Pick filament profiles interactively.

    Returns a list of filament profile names.
    """
    from estampo import ui

    filament_names: list[str] = []
    filament_options = sorted(profiles.get("filament", []))

    if filament_options:
        ui.heading("Filament Profile")
        # Vendor-branded profiles (Bambu PLA Basic, Polymaker, ...) are
        # calibrated for that vendor's own filament — feeding generic filament
        # through them causes under-extrusion at the planned flow rate. Default
        # to the safe option (Generic ...) unless the user explicitly confirms
        # they have the matching vendor's filament loaded.
        ui.info(
            "Vendor-branded profiles (e.g. 'Bambu PLA Basic') assume that "
            "vendor's own filament. Using them with generic/third-party "
            "filament causes under-extrusion — pick a 'Generic ...' profile "
            "instead unless you are loading the vendor's actual filament."
        )
        prefer_generic = ui.prompt_yn(
            "Restrict the menu to vendor-neutral 'Generic ...' profiles?", default=True
        )
        if prefer_generic:
            filtered = [f for f in filament_options if f.startswith("Generic ")]
            if filtered:
                filament_options = filtered
        if machine_info.multi_material:
            ui.info("Printer supports multi-material. Pick a filament for each slot.")
            slot = 1
            while True:
                chosen = ui.pick(filament_options, prompt=f"Pick filament for slot {slot}")
                filament_names.append(filament_options[chosen[0]])
                ui.success(f"Slot {slot}: {filament_names[-1]}")
                if slot >= 4:
                    break
                if not ui.prompt_yn(f"Add slot {slot + 1}?", default=slot < 2):
                    break
                slot += 1
        else:
            chosen = ui.pick(filament_options, prompt="Pick a filament")
            filament_names.append(filament_options[chosen[0]])
        ui.console.print()

    if not filament_names:
        fil = ui.prompt_str("Filament profile name", "Generic PLA @base")
        filament_names = [fil]
        ui.console.print()

    return filament_names


def _wizard_pick_bed_type(existing_bed: str | None) -> str | None:
    """Prompt for bed/plate type selection."""
    from estampo import ui

    ui.heading("Bed Type")
    ui.info("Select bed/plate type (affects filament compatibility):")
    bed_default = ""
    for i, bt in enumerate(BED_TYPES, 1):
        marker = " ←" if bt == existing_bed else ""
        ui.info(f"  {i}. {bt}{marker}")
        if bt == existing_bed:
            bed_default = str(i)
    bed_pick = ui.prompt_str("Pick bed type (or Enter to skip)", bed_default).strip()
    bed_type: str | None = None
    if bed_pick.isdigit() and 1 <= int(bed_pick) <= len(BED_TYPES):
        bed_type = BED_TYPES[int(bed_pick) - 1]
        ui.info(f"  → {bed_type}")
    ui.console.print()
    return bed_type


def _wizard_pick_nozzle_type(existing_nozzle: str) -> dict[str, str]:
    """Prompt for nozzle type selection.  Returns machine_overrides dict."""
    from estampo import ui

    ui.heading("Nozzle Type")
    nozzle_types = ["stainless_steel", "hardened_steel", "brass"]
    nozzle_default = "1"
    ui.info("Select your physical nozzle type:")
    for i, nt in enumerate(nozzle_types, 1):
        marker = " ←" if nt == existing_nozzle else ""
        ui.info(f"  {i}. {nt}{marker}")
        if nt == existing_nozzle:
            nozzle_default = str(i)
    nozzle_prompt = f"Pick nozzle type (default: {existing_nozzle})"
    nozzle_pick = ui.prompt_str(nozzle_prompt, nozzle_default).strip()
    if nozzle_pick.isdigit() and 1 <= int(nozzle_pick) <= len(nozzle_types):
        picked_nozzle = nozzle_types[int(nozzle_pick) - 1]
    elif nozzle_pick in nozzle_types:
        picked_nozzle = nozzle_pick
    else:
        picked_nozzle = "stainless_steel"
    ui.info(f"  → {picked_nozzle}")
    ui.console.print()
    machine_overrides: dict[str, str] = {}
    if picked_nozzle != "stainless_steel":
        machine_overrides["nozzle_type"] = picked_nozzle
    return machine_overrides


def _wizard_pick_command_stages(
    engine: str,
    printer_profile: str,
    stages: list[str],
) -> dict[str, dict[str, str | bool]]:
    """Prompt for Bambu Lab pack/resolve command stages.  Mutates ``stages`` in place."""
    from estampo import ui

    command_stages: dict[str, dict[str, str | bool]] = {}
    if not _is_bambu_printer(printer_profile):
        return command_stages

    ui.heading("Packaging")
    ui.info("This printer needs bambox to produce printable .gcode.3mf files.")
    if ui.prompt_yn("Add a pack stage? (requires: pipx install bambox)", default=True):
        if engine == "cura":
            stages.append("resolve_templates")
            command_stages["resolve_templates"] = {
                "command": ("cura-p1s resolve {sliced_dir}/plate.gcode --settings {cura_settings}"),
                "docker": True,
            }
            stages.append("pack")
            machine = _bambox_machine_key(printer_profile)
            machine_flag = f" -m {machine}" if machine else ""
            command_stages["pack"] = {
                "command": (
                    f"bambox pack {{sliced_dir}}/plate.gcode{machine_flag} "
                    "-o {output_dir}/plate.gcode.3mf"
                ),
                "output": "{output_dir}/plate.gcode.3mf",
                "docker": True,
            }
        else:
            stages.append("pack")
            command_stages["pack"] = {
                "command": "bambox repack {sliced_3mf}",
                "output": "{sliced_3mf}",
                "docker": True,
            }
    ui.console.print()
    return command_stages


def _wizard_pick_parts(
    existing_parts: list[dict] | None = None,
) -> list[dict]:
    """Discover CAD files and configure copies/orient.

    Returns a list of part config dicts (filament slot defaults to 1,
    assigned later by ``_wizard_assign_filament_slots``).
    """
    from estampo import ui

    ui.heading("CAD Files")

    # Show existing parts and ask to keep them
    parts_config: list[dict] = []
    if existing_parts:
        ui.info(f"Existing parts ({len(existing_parts)}):")
        for p in existing_parts:
            ui.info(f"  • {p.get('file')}")
        if ui.prompt_yn("Keep existing parts?"):
            parts_config = list(existing_parts)
        ui.console.print()

    cwd = Path.cwd()
    # Exclude files already in parts_config
    existing_files = {p.get("file") for p in parts_config}
    candidates = sorted(
        p
        for ext in ("*.stl", "*.3mf", "*.step", "*.STL", "*.3MF", "*.STEP")
        for p in cwd.glob(ext)
        if p.name not in existing_files
    )
    if candidates:
        ui.info(f"Found {len(candidates)} CAD file(s) in current directory")
        names = [p.name for p in candidates]
        chosen = ui.pick(
            names,
            prompt="Select files",
            allow_multi=True,
        )
        ui.console.print()
        for idx in chosen:
            f = candidates[idx]
            copies = ui.prompt_int(f"{f.name} — copies?", 1)
            orient_options = ["flat", "upright", "upside-down", "side", "custom rotation"]
            selected = ui.pick(orient_options, prompt=f"{f.name} — orientation")
            pick = orient_options[selected[0]]
            part: dict[str, object] = {
                "file": f.name,
                "copies": copies,
                "orient": "flat",
                "filament": 1,
            }
            if pick == "custom rotation":
                rx = ui.prompt_int("  X rotation (degrees)", 0)
                ry = ui.prompt_int("  Y rotation (degrees)", 0)
                rz = ui.prompt_int("  Z rotation (degrees)", 0)
                part["rotate"] = [rx, ry, rz]
            else:
                part["orient"] = pick
            parts_config.append(part)
        ui.console.print()

    if not parts_config:
        # No CAD files found or selected — add a placeholder
        file_name = ui.prompt_str("Part file path (relative to this directory)", "my-part.stl")
        parts_config.append({"file": file_name, "copies": 1, "orient": "flat", "filament": 1})
        ui.console.print()

    return parts_config


def _wizard_assign_filament_slots(parts_config: list[dict], filament_names: list[str]) -> None:
    """Assign filament slots to parts (mutates parts_config in place).

    Only prompts when there are multiple filaments.
    """
    if len(filament_names) <= 1:
        return

    from estampo import ui

    ui.heading("Filament Assignment")
    for p in parts_config:
        fil_slot = ui.prompt_int(f"{p['file']} — filament slot (1-{len(filament_names)})?", 1)
        p["filament"] = fil_slot
    ui.console.print()


def _wizard_pick_plate(machine_info: _MachineInfo) -> tuple[int, int]:
    """Get plate size from printer profile.

    Returns ``(plate_x, plate_y)``.
    """
    from estampo import ui

    if machine_info.plate_size:
        w, d = machine_info.plate_size
        ui.success(f"Build plate: {w}x{d}mm (from printer profile)")
        return w, d

    # Fallback if no printer profile was selected
    ui.heading("Build Plate")
    plate_x = ui.prompt_int("Plate width (mm)?", 256)
    plate_y = ui.prompt_int("Plate depth (mm)?", 256)
    ui.console.print()
    return plate_x, plate_y


def _wizard_pick_slicer_version(engine: str = "orca") -> str | None:
    """Pick slicer version to pin.

    Returns the version string, or ``None`` if skipped.
    """
    from estampo import ui

    ui.heading("Slicer Version")
    if engine == "cura":
        from estampo.cura import CURAENGINE_VERSION

        version = ui.prompt_str(
            f"CuraEngine version to pin (default: {CURAENGINE_VERSION})",
            CURAENGINE_VERSION,
        )
        ui.console.print()
        return version or None

    from estampo.orca import _prompt_slicer_version

    slicer_version = _prompt_slicer_version()
    ui.console.print()

    return slicer_version


def run_wizard(output: Path | None = None) -> str:
    """Run the interactive init wizard and return generated TOML.

    Flow: project name → CAD files → printer connection → plate size →
    slicer version → profiles → filaments → filament slots → bed type →
    nozzle type → overrides → preview.

    If an estampo.toml already exists, its values are used as defaults
    so the user can keep existing settings and add/edit parts.
    """
    from estampo import ui
    from estampo.profiles import discover_profile_names

    ui.heading("estampo init")
    ui.console.print()

    # --- Engine choice ---
    existing_engine = None
    dest = output or Path("estampo.toml")
    existing_pre = _load_existing(dest)
    if existing_pre and hasattr(existing_pre, "engine"):
        existing_engine = existing_pre.engine

    engines = ["orca", "cura"]
    engine_labels = {"orca": "OrcaSlicer", "cura": "CuraEngine"}
    default_engine = existing_engine or "orca"
    default_idx = engines.index(default_engine) + 1 if default_engine in engines else 1
    ui.info("Select slicer engine:")
    for i, eng in enumerate(engines, 1):
        marker = " ←" if eng == existing_engine else ""
        ui.info(f"  {i}. {engine_labels[eng]}{marker}")
    engine_pick = ui.prompt_str(
        f"Pick engine (default: {engine_labels[default_engine]})", str(default_idx)
    ).strip()
    if engine_pick.isdigit() and 1 <= int(engine_pick) <= len(engines):
        engine = engines[int(engine_pick) - 1]
    else:
        engine = default_engine
    ui.info(f"  → {engine_labels[engine]}")
    ui.console.print()

    # --- Load existing config for pre-population ---
    existing = existing_pre
    if existing:
        ui.info(f"Found existing {dest.name} — values shown as defaults")
        ui.console.print()

    # --- Step 1: Project name ---
    default_name = (existing and existing.project_name) or Path.cwd().name
    project_name = ui.prompt_str("Project name", default=default_name) or default_name
    ui.console.print()

    # --- Step 2: CAD files (copies, orient — filament slots assigned later) ---
    parts_config = _wizard_pick_parts(existing_parts=existing.parts if existing else None)

    stages = list(DEFAULT_STAGES)

    # --- Discover profiles (needed for picker and machine info) ---
    if engine == "cura":
        process_profile = None

        # Discover CuraEngine printer definitions (bundled manifest or pinned)
        profiles, profile_source = discover_profile_names(
            engine, project_dir=dest.parent, profiles_dir="profiles"
        )
        if profile_source == "bundled":
            ui.info("Using bundled printer definition list")
            ui.console.print()

        machines = sorted(profiles.get("machine", []))
        ui.heading("CuraEngine Printer Definition")
        if machines:
            chosen = ui.pick(machines, prompt="Pick a printer")
            printer_profile: str | None = machines[chosen[0]]
        else:
            ui.warn("No CuraEngine printer definitions found.")
            printer_profile = ui.prompt_str("Printer definition name").strip()
        ui.console.print()

        # Derive plate size from the .def.json
        machine_info = _MachineInfo()
        try:
            from estampo.cura import resolve_cura_bed_size

            w, d = resolve_cura_bed_size(printer_profile or "")
            machine_info.plate_size = (int(w), int(d))
        except (OSError, ImportError, ValueError):
            log.debug("Failed to read CuraEngine bed size", exc_info=True)
        plate_x, plate_y = _wizard_pick_plate(machine_info)
    else:
        profiles, profile_source = discover_profile_names(engine)
        if profile_source == "bundled":
            ui.info("Using bundled profile list — install the slicer locally for full access")
            ui.console.print()
        elif profile_source == "none":
            ui.warn("No profiles found — profile names will need to be entered manually")
            ui.console.print()

        # --- Step 4: Plate size ---
        # Pick printer profile first to auto-detect plate size from machine info
        printer_profile, process_profile, machine_info = _wizard_pick_profiles(engine, profiles)
        plate_x, plate_y = _wizard_pick_plate(machine_info)

    # --- Step 5: Slicer version ---
    slicer_version = _wizard_pick_slicer_version(engine)

    # --- Step 6: Filaments ---
    filament_names = _wizard_pick_filaments(profiles, machine_info)

    # --- Step 7: Assign filament slots to parts (if multiple filaments) ---
    _wizard_assign_filament_slots(parts_config, filament_names)

    # --- Step 8: Bed type ---
    bed_type = _wizard_pick_bed_type(existing.bed_type if existing else None)

    # --- Step 9: Nozzle type ---
    machine_overrides = _wizard_pick_nozzle_type(
        (existing and existing.nozzle_type) or "stainless_steel"
    )

    # --- Step 10: Slicer overrides ---
    ui.heading("Slicer Overrides")
    overrides = _prompt_overrides()
    ui.console.print()

    # --- Step 11: Command stages (pack/resolve) ---
    command_stages = _wizard_pick_command_stages(engine, printer_profile or "", stages)

    # --- Build TOML ---
    toml = _build_toml(
        project_name=project_name,
        engine=engine,
        printer_profile=printer_profile,
        process_profile=process_profile,
        filament_names=filament_names,
        parts=parts_config,
        plate_size=(plate_x, plate_y),
        slicer_version=slicer_version or None,
        stages=stages,
        bed_type=bed_type,
        overrides=overrides,
        machine_overrides=machine_overrides or None,
        command_stages=command_stages,
    )

    # --- Preview and confirm ---
    dest = output or Path("estampo.toml")

    while True:
        ui.heading("Preview")
        ui.preview_toml(toml)

        answer = ui.prompt_str("Write / Go back / Quit? (W/g/q)", "w").strip().lower()

        if answer in ("w", "write", "y", "yes", ""):
            if dest.exists():
                if not ui.prompt_yn(f"{dest} already exists. Overwrite?", default=False):
                    continue
            dest.write_text(toml)
            ui.success(f"Wrote {dest}")
            _emit_cura_pin_hint(engine, printer_profile, dest.parent)
            return toml

        if answer in ("q", "quit"):
            ui.info("Not written. Copy the output above to create your config.")
            return toml

        # Go back — re-run wizard from the top
        ui.console.print()
        return run_wizard(output=output)


def _emit_cura_pin_hint(engine: str, printer: str | None, project_dir: Path) -> None:
    """Tell the user to run ``estampo profiles pin`` if the chosen Cura def
    is only reachable via Docker.

    Without pinning, ``estampo run --local`` fails and teammates who clone
    the repo get an empty ``profiles/`` directory.
    """
    if engine != "cura" or not printer:
        return

    from estampo import ui

    if _check_cura_def_reachable(printer, project_dir, "profiles") is None:
        return

    ui.console.print()
    ui.warn(
        f"Printer '{printer}' is not bundled with estampo — its definition "
        f"only exists inside the Docker image."
    )
    ui.info("Next: run 'estampo profiles pin' and commit the profiles/ directory")
    ui.info("      so local slicing and clean clones slice identically.")


def _is_bambu_printer(printer: str) -> bool:
    """Check if a printer profile name refers to a Bambu Lab printer."""
    lower = printer.lower()
    return any(kw in lower for kw in ("bambu", "bbl", "bambox"))


def _bambox_machine_key(printer: str) -> str | None:
    """Map a Bambu printer profile name to a ``bambox --machine`` key.

    Used to forward the printer identity to ``bambox pack`` so the resulting
    .gcode.3mf has ``printer_model_id`` set (see issue #685). Returns ``None``
    when the model can't be derived; caller should omit the ``-m`` flag.
    """
    lower = printer.lower()
    # Order matters: check more specific patterns first.
    for pattern, key in (
        ("a1 mini", "a1mini"),
        ("a1mini", "a1mini"),
        ("p1s", "p1s"),
        ("p1p", "p1p"),
        ("x1e", "x1e"),
        ("x1c", "x1c"),
        ("x1 carbon", "x1c"),
        ("x1", "x1"),
        ("a1", "a1"),
    ):
        if pattern in lower:
            return key
    return None


def _build_toml(
    *,
    project_name: str | None = None,
    engine: str,
    printer_profile: str | None,
    process_profile: str | None,
    filament_names: list[str],
    parts: list[dict],
    plate_size: tuple[int, int],
    slicer_version: str | None,
    stages: list[str],
    bed_type: str | None = None,
    overrides: dict[str, str] | None = None,
    machine_overrides: dict[str, str] | None = None,
    command_stages: dict[str, dict[str, str | bool]] | None = None,
) -> str:
    """Build a TOML string from wizard answers."""
    lines: list[str] = []

    # Project name
    if project_name:
        lines.append(f'name = "{project_name}"')
        lines.append("")

    # Pipeline
    stage_list = ", ".join(f'"{s}"' for s in stages)
    lines.append("[pipeline]")
    lines.append(f"stages = [{stage_list}]")
    lines.append("")

    # Plate
    lines.append("[plate]")
    lines.append(f"size = [{plate_size[0]}, {plate_size[1]}]")
    lines.append("padding = 5.0")
    lines.append("")

    # Slicer — common fields
    lines.append("[slicer]")
    lines.append(f'engine = "{engine}"')
    if slicer_version:
        lines.append(f'version = "{slicer_version}"')
    if bed_type:
        lines.append(f'bed_type = "{bed_type}"')
    lines.append("")

    # Engine-specific sections
    if engine == "orca":
        lines.append("[slicer.orca]")
        if printer_profile:
            lines.append(f'printer = "{printer_profile}"')
        if process_profile:
            lines.append(f'process = "{process_profile}"')
        if filament_names:
            fil_list = ", ".join(f'"{f}"' for f in filament_names)
            lines.append(f"filaments = [{fil_list}]")
        lines.append("")

        if overrides:
            lines.append("[slicer.orca.overrides]")
            for key, value in overrides.items():
                try:
                    float(value)
                    lines.append(f"{key} = {value}")
                except ValueError:
                    lines.append(f'{key} = "{value}"')
            lines.append("")

        if machine_overrides:
            lines.append("[slicer.orca.machine_overrides]")
            for key, value in machine_overrides.items():
                lines.append(f'{key} = "{value}"')
            lines.append("")

    elif engine == "cura":
        if printer_profile or overrides:
            lines.append("[slicer.cura]")
            if printer_profile:
                lines.append(f'printer = "{printer_profile}"')
            lines.append("")
        if overrides:
            lines.append("[slicer.cura.overrides]")
            for key, value in overrides.items():
                try:
                    float(value)
                    lines.append(f"{key} = {value}")
                except ValueError:
                    lines.append(f'{key} = "{value}"')
            lines.append("")

    # Parts
    for p in parts:
        lines.append("[[parts]]")
        lines.append(f'file = "{p["file"]}"')
        if p.get("copies", 1) != 1:
            lines.append(f"copies = {p['copies']}")
        if p.get("rotate"):
            lines.append(f"rotate = {p['rotate']}")
        elif p.get("orient", "flat") != "flat":
            lines.append(f'orient = "{p["orient"]}"')
        if p.get("filament", 1) != 1:
            lines.append(f"filament = {p['filament']}")
        lines.append("")

    # Command stages
    if command_stages:
        for stage_name, stage_cfg in command_stages.items():
            lines.append(f"[{stage_name}]")
            for key, val in stage_cfg.items():
                if isinstance(val, bool):
                    lines.append(f"{key} = {str(val).lower()}")
                else:
                    lines.append(f'{key} = "{val}"')
            lines.append("")

    return "\n".join(lines)


def build_config_toml(
    *,
    engine: str,
    printer: str | None,
    process: str | None = None,
    filaments: list[str],
    parts: list[str],
    plate_size: tuple[int, int] = (256, 256),
    slicer_version: str | None = None,
    stages: list[str] | None = None,
    bed_type: str | None = None,
    name: str | None = None,
) -> str:
    """Build estampo.toml content from explicit parameters (non-interactive)."""
    part_dicts = [{"file": p, "copies": 1, "orient": "flat", "filament": 1} for p in parts]
    effective_stages = list(stages) if stages else list(DEFAULT_STAGES)
    command_stages: dict[str, dict[str, str | bool]] | None = None

    # Auto-add resolve_templates + pack for CuraEngine with Bambu printers
    if printer and _is_bambu_printer(printer) and "pack" not in effective_stages:
        command_stages = {}
        if engine == "cura":
            effective_stages.append("resolve_templates")
            command_stages["resolve_templates"] = {
                "command": ("cura-p1s resolve {sliced_dir}/plate.gcode --settings {cura_settings}"),
                "docker": True,
            }
        effective_stages.append("pack")
        if engine == "cura":
            machine = _bambox_machine_key(printer)
            machine_flag = f" -m {machine}" if machine else ""
            pack_cmd = (
                f"bambox pack {{sliced_dir}}/plate.gcode{machine_flag} "
                "-o {output_dir}/plate.gcode.3mf"
            )
            pack_output = "{output_dir}/plate.gcode.3mf"
        else:
            pack_cmd = "bambox repack {sliced_3mf}"
            pack_output = "{sliced_3mf}"
        command_stages["pack"] = {
            "command": pack_cmd,
            "output": pack_output,
            "docker": True,
        }

    return _build_toml(
        project_name=name,
        engine=engine,
        printer_profile=printer,
        process_profile=process,
        filament_names=filaments,
        parts=part_dicts,
        plate_size=plate_size,
        slicer_version=slicer_version,
        stages=effective_stages,
        bed_type=bed_type,
        command_stages=command_stages,
    )


# ---------------------------------------------------------------------------
# Extract config from OrcaSlicer 3MF
# ---------------------------------------------------------------------------


def extract_from_3mf(path: Path) -> str:
    """Read an OrcaSlicer 3MF and generate an estampo.toml."""
    from estampo.orca import extract_from_3mf as _impl

    return _impl(path)

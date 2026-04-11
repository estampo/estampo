"""estampo init and validate commands."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from estampo.config import DEFAULT_STAGES

log = logging.getLogger(__name__)

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
# bed_type = "Textured PEI Plate"          # or: Cool Plate, Engineering Plate, High Temp Plate

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
    """Result of config validation with passes and warnings."""

    passes: list[str]
    warnings: list[str]

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


def validate_config(path: Path) -> ValidationResult:
    """Validate an estampo.toml and return passes and warnings.

    Raises EstampoError for hard errors (via load_config).
    Returns a ValidationResult with passes and warnings.
    """
    from estampo.config import load_config
    from estampo.pipeline import STAGE_OUTPUTS
    from estampo.profiles import discover_profile_names, validate_override_keys

    cfg = load_config(path)
    passes: list[str] = []
    warnings: list[str] = []

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
                        f"variant, e.g. '{active.printer} 0.4 nozzle'"
                    )
                else:
                    warnings.append(
                        f"slicer.printer '{active.printer}' not found in "
                        f"{cfg.slicer.engine} profiles ({source}).{hint}"
                    )
                profile_ok = False

        if orca and orca.process:
            processes = profiles.get("process", [])
            if processes and orca.process not in processes:
                close = _closest_match(orca.process, processes)
                hint = f" Did you mean '{close}'?" if close else ""
                warnings.append(
                    f"slicer.process '{orca.process}' not found in "
                    f"{cfg.slicer.engine} profiles ({source}).{hint}"
                )
                profile_ok = False

        filament_list = orca.filaments if orca else []
        known_filaments = profiles.get("filament", [])
        if known_filaments:
            for fil in filament_list:
                if fil not in known_filaments:
                    close = _closest_match(fil, known_filaments)
                    hint = f" Did you mean '{close}'?" if close else ""
                    warnings.append(
                        f"slicer filament '{fil}' not found in "
                        f"{cfg.slicer.engine} profiles ({source}).{hint}"
                    )
                    profile_ok = False

        if profile_ok:
            passes.append(f"Slicer profiles valid ({source})")
    else:
        warnings.append(
            f"slicer profile names could not be validated — {cfg.slicer.engine} is not "
            "installed locally, no pinned profiles found, and no bundled profile list available. "
            "Run 'estampo profiles pin' or "
            f"'python scripts/extract_profiles.py {cfg.slicer.version or '<version>'}' to add one."
        )

    # Check slicer override keys against process profile
    if active.overrides:
        override_warnings = validate_override_keys(
            active.overrides,
            cfg.slicer.engine,
            orca.process if orca else None,
            project_dir=cfg.base_dir,
        )
        if override_warnings:
            warnings.extend(override_warnings)
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
    _SUPPORTED_EXTENSIONS = {".stl", ".3mf", ".step", ".stp", ".obj"}
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
        if ext and ext not in _SUPPORTED_EXTENSIONS:
            warnings.append(
                f"parts[{i}].file has unsupported extension '{ext}' "
                f"— expected one of {sorted(_SUPPORTED_EXTENSIONS)}"
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
        if stage not in STAGE_OUTPUTS:
            warnings.append(f"pipeline stage '{stage}' is unknown")
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

    return ValidationResult(passes=passes, warnings=warnings)


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


def _detect_orca_version() -> str | None:
    """Try to detect the installed OrcaSlicer version."""
    from estampo.orca import _detect_orca_version as _impl

    return _impl()


def _fetch_available_versions() -> list[str]:
    """Return OrcaSlicer versions available as Docker images."""
    from estampo.orca import _fetch_available_versions as _impl

    return _impl()


def _prompt_slicer_version() -> str | None:
    """Prompt for OrcaSlicer version, offering available Docker image versions."""
    from estampo.orca import _prompt_slicer_version as _impl

    return _impl()


def _prompt_choice(prompt: str, options: list[str], allow_multi: bool = False) -> list[int]:
    """Interactive picker — delegates to ``ui.pick``."""
    from estampo import ui

    return ui.pick(options, prompt=prompt, allow_multi=allow_multi)


def _prompt_str(prompt: str, default: str | None = None) -> str:
    """Prompt for a string value with optional default."""
    from estampo import ui

    return ui.prompt_str(prompt, default)


def _prompt_int(prompt: str, default: int) -> int:
    """Prompt for an integer with a default."""
    from estampo import ui

    return ui.prompt_int(prompt, default)


def _prompt_yn(prompt: str, default: bool = True) -> bool:
    """Prompt yes/no with a default."""
    from estampo import ui

    return ui.prompt_yn(prompt, default)


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

        raw_pick = _prompt_str("Pick override (or N to finish)", "n")
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
            key = _prompt_str("Slicer key name")
            if not key:
                continue
            value = _prompt_str(f"Value for {key}")
            if value:
                overrides[key] = value
                ui.success(f'{key} = "{value}"')
        else:
            name, key, spec = COMMON_OVERRIDES[idx]
            ui.success(name)

            if spec[0] == "choice" and isinstance(spec[1], list):
                choices = spec[1]
                ui.choice_table([(c,) for c in choices], ["Option"])
                cpick = _prompt_int("Pick value", 1)
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
                raw = _prompt_str(f"Value for {key} ({hint})")
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
        chosen = _prompt_choice("Pick a printer profile", machines)
        printer_profile = machines[chosen[0]]
        machine_info = _read_machine_info(printer_profile, engine)
        ui.console.print()
    else:
        printer_profile = _prompt_str("Printer profile name (e.g. 'My Printer 0.4 nozzle')")
        ui.console.print()

    # --- Step 4: Pick process profile ---
    process_profile = None
    processes = sorted(profiles.get("process", []))
    if processes:
        ui.heading("Process Profile")
        chosen = _prompt_choice("Pick a process profile", processes)
        process_profile = processes[chosen[0]]
        ui.console.print()
    else:
        process_profile = _prompt_str("Process profile name (e.g. '0.20mm Standard @base')")
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
        if machine_info.multi_material:
            ui.info("Printer supports multi-material. Pick a filament for each slot.")
            slot = 1
            while True:
                chosen = _prompt_choice(f"Pick filament for slot {slot}", filament_options)
                filament_names.append(filament_options[chosen[0]])
                ui.success(f"Slot {slot}: {filament_names[-1]}")
                if slot >= 4:
                    break
                if not _prompt_yn(f"Add slot {slot + 1}?", default=slot < 2):
                    break
                slot += 1
        else:
            chosen = _prompt_choice("Pick a filament", filament_options)
            filament_names.append(filament_options[chosen[0]])
        ui.console.print()

    if not filament_names:
        fil = _prompt_str("Filament profile name", "Generic PLA @base")
        filament_names = [fil]
        ui.console.print()

    return filament_names


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
        if _prompt_yn("Keep existing parts?"):
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
        chosen = _prompt_choice(
            "Select files",
            names,
            allow_multi=True,
        )
        ui.console.print()
        for idx in chosen:
            f = candidates[idx]
            copies = _prompt_int(f"{f.name} — copies?", 1)
            orient_options = ["flat", "upright", "upside-down", "side", "custom rotation"]
            selected = _prompt_choice(f"{f.name} — orientation", orient_options)
            pick = orient_options[selected[0]]
            part: dict[str, object] = {
                "file": f.name,
                "copies": copies,
                "orient": "flat",
                "filament": 1,
            }
            if pick == "custom rotation":
                rx = _prompt_int("  X rotation (degrees)", 0)
                ry = _prompt_int("  Y rotation (degrees)", 0)
                rz = _prompt_int("  Z rotation (degrees)", 0)
                part["rotate"] = [rx, ry, rz]
            else:
                part["orient"] = pick
            parts_config.append(part)
        ui.console.print()

    if not parts_config:
        # No CAD files found or selected — add a placeholder
        file_name = _prompt_str("Part file path (relative to this directory)", "my-part.stl")
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
        fil_slot = _prompt_int(f"{p['file']} — filament slot (1-{len(filament_names)})?", 1)
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
    plate_x = _prompt_int("Plate width (mm)?", 256)
    plate_y = _prompt_int("Plate depth (mm)?", 256)
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

        version = _prompt_str(
            f"CuraEngine version to pin (default: {CURAENGINE_VERSION})",
            CURAENGINE_VERSION,
        )
        ui.console.print()
        return version or None

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
    engine_labels = {"orca": "OrcaSlicer", "cura": "CuraEngine (experimental)"}
    default_engine = existing_engine or "orca"
    default_idx = engines.index(default_engine) + 1 if default_engine in engines else 1
    ui.info("Select slicer engine:")
    for i, eng in enumerate(engines, 1):
        marker = " ←" if eng == existing_engine else ""
        ui.info(f"  {i}. {engine_labels[eng]}{marker}")
    engine_pick = _prompt_str(
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
            chosen = _prompt_choice("Pick a printer", machines)
            printer_profile: str | None = machines[chosen[0]]
        else:
            ui.warn("No CuraEngine printer definitions found.")
            printer_profile = _prompt_str("Printer definition name").strip()
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
    ui.heading("Bed Type")
    BED_TYPES = ["Cool Plate", "Engineering Plate", "High Temp Plate", "Textured PEI Plate"]
    ui.info("Select bed/plate type (affects filament compatibility):")
    existing_bed = existing.bed_type if existing else None
    bed_default = ""
    for i, bt in enumerate(BED_TYPES, 1):
        marker = " ←" if bt == existing_bed else ""
        ui.info(f"  {i}. {bt}{marker}")
        if bt == existing_bed:
            bed_default = str(i)
    bed_pick = _prompt_str("Pick bed type (or Enter to skip)", bed_default).strip()
    bed_type: str | None = None
    if bed_pick.isdigit() and 1 <= int(bed_pick) <= len(BED_TYPES):
        bed_type = BED_TYPES[int(bed_pick) - 1]
        ui.info(f"  → {bed_type}")
    ui.console.print()

    # --- Step 9: Nozzle type ---
    ui.heading("Nozzle Type")
    NOZZLE_TYPES = ["stainless_steel", "hardened_steel", "brass"]
    existing_nozzle = (existing and existing.nozzle_type) or "stainless_steel"
    nozzle_default = "1"
    ui.info("Select your physical nozzle type:")
    for i, nt in enumerate(NOZZLE_TYPES, 1):
        marker = " ←" if nt == existing_nozzle else ""
        ui.info(f"  {i}. {nt}{marker}")
        if nt == existing_nozzle:
            nozzle_default = str(i)
    nozzle_prompt = f"Pick nozzle type (default: {existing_nozzle})"
    nozzle_pick = _prompt_str(nozzle_prompt, nozzle_default).strip()
    machine_overrides: dict[str, str] = {}
    if nozzle_pick.isdigit() and 1 <= int(nozzle_pick) <= len(NOZZLE_TYPES):
        picked_nozzle = NOZZLE_TYPES[int(nozzle_pick) - 1]
    elif nozzle_pick in NOZZLE_TYPES:
        picked_nozzle = nozzle_pick
    else:
        picked_nozzle = "stainless_steel"
    if picked_nozzle != "stainless_steel":
        machine_overrides["nozzle_type"] = picked_nozzle
    ui.info(f"  → {picked_nozzle}")
    ui.console.print()

    # --- Step 10: Slicer overrides ---
    ui.heading("Slicer Overrides")
    overrides = _prompt_overrides()
    ui.console.print()

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
    )

    # --- Preview and confirm ---
    dest = output or Path("estampo.toml")

    while True:
        ui.heading("Preview")
        ui.preview_toml(toml)

        answer = _prompt_str("Write / Go back / Quit? (W/g/q)", "w").strip().lower()

        if answer in ("w", "write", "y", "yes", ""):
            if dest.exists():
                if not _prompt_yn(f"{dest} already exists. Overwrite?", default=False):
                    continue
            dest.write_text(toml)
            ui.success(f"Wrote {dest}")
            return toml

        if answer in ("q", "quit"):
            ui.info("Not written. Copy the output above to create your config.")
            return toml

        # Go back — re-run wizard from the top
        ui.console.print()
        return run_wizard(output=output)


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

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Extract config from OrcaSlicer 3MF
# ---------------------------------------------------------------------------


def extract_from_3mf(path: Path) -> str:
    """Read an OrcaSlicer 3MF and generate an estampo.toml."""
    from estampo.orca import extract_from_3mf as _impl

    return _impl(path)

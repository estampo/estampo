"""Load and validate estampo.toml configuration."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from estampo import EstampoError

log = logging.getLogger(__name__)

VALID_ORIENTS = {"flat", "upright", "side", "upside-down"}


@dataclass
class PlateConfig:
    size: tuple[float, float] = (256.0, 256.0)
    padding: float = 5.0


@dataclass
class OrcaSlicerConfig:
    """OrcaSlicer-specific settings: profile chain (printer/process/filament)."""

    printer: str | None = None
    process: str | None = None
    filaments: list[str] = field(default_factory=list)
    slots: dict[int, str] = field(default_factory=dict)  # slot (1-indexed) → profile name
    overrides: dict[str, object] = field(default_factory=dict)
    machine_overrides: dict[str, object] = field(default_factory=dict)
    filament_overrides: dict[str, object] = field(default_factory=dict)


@dataclass
class CuraSlicerConfig:
    """CuraEngine-specific settings: printer definition + flat key-value overrides."""

    printer: str | None = None  # CuraEngine printer definition name
    overrides: dict[str, object] = field(default_factory=dict)


@dataclass
class SlicerConfig:
    engine: str = "orca"
    version: str | None = None  # required slicer version (e.g. "2.3.1", "5.12.0")
    bed_type: str | None = None  # e.g. "Textured PEI Plate", "Engineering Plate"
    profiles_dir: str = "profiles"

    # Engine-specific sub-configs (both may be populated; engine selects active one)
    orca: OrcaSlicerConfig = field(default_factory=OrcaSlicerConfig)
    cura: CuraSlicerConfig = field(default_factory=CuraSlicerConfig)

    # Active-engine fields — populated from the active engine's sub-config during
    # load_config().  Existing code reads these directly (facade pattern).
    printer: str | None = None
    process: str | None = None
    filaments: list[str] = field(default_factory=list)
    slots: dict[int, str] = field(default_factory=dict)  # slot (1-indexed) → profile name
    overrides: dict[str, object] = field(default_factory=dict)
    machine_overrides: dict[str, object] = field(default_factory=dict)
    filament_overrides: dict[str, object] = field(default_factory=dict)


@dataclass
class PartConfig:
    file: Path
    copies: int = 1
    orient: str = "flat"
    rotate: list[float] | None = None  # [rx, ry, rz] in degrees, overrides orient
    filament: int = 1  # slicer filament slot (1-indexed), resolved from name or int
    scale: float = 1.0  # uniform scale factor
    object_filaments: dict[str, int] = field(default_factory=dict)  # 3MF object → slot
    object: str | None = None  # select named object from multi-object 3MF
    sequence: int = 1  # print order for sequential printing


@dataclass
class PrinterConfig:
    name: str  # references a printer in ~/.config/estampo/credentials.toml


DEFAULT_STAGES = ["load", "arrange", "plate", "slice"]


@dataclass
class PipelineConfig:
    stages: list[str] = field(default_factory=lambda: list(DEFAULT_STAGES))


@dataclass
class EstampoConfig:
    plate: PlateConfig
    slicer: SlicerConfig
    parts: list[PartConfig]
    base_dir: Path  # directory containing the toml file
    name: str | None = None  # optional project name, used to prefix output filenames
    output_dir: str = "estampo_output"  # output directory, relative to base_dir
    printer: PrinterConfig | None = None
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)


def _resolve_filaments(
    parts: list[PartConfig],
    slicer: SlicerConfig,
    raw_filaments: list[int | str],
    raw_obj_filaments: list[dict[str, int | str]],
) -> None:
    """Resolve filament names/indices and mutate parts in place.

    Sets ``.filament`` and ``.object_filaments`` on each part.
    May also populate ``slicer.filaments`` when auto-deriving from string refs.
    """
    # Collect all raw filament values (part defaults + per-object overrides)
    all_raw_filaments: list[int | str] = list(raw_filaments)
    for obj_fils in raw_obj_filaments:
        all_raw_filaments.extend(obj_fils.values())

    # Resolve filament names → slot indices
    has_string_filaments = any(isinstance(f, str) for f in all_raw_filaments)
    has_int_filaments = any(isinstance(f, int) for f in all_raw_filaments)

    if has_string_filaments and has_int_filaments and not slicer.filaments and not slicer.slots:
        raise EstampoError(
            "Cannot mix filament names and indices without [slicer].filaments or [slicer.slots]"
        )

    if has_int_filaments and not has_string_filaments and not slicer.slots:
        # All integers, no slots map — backward compatible, no resolution needed
        for i, raw_fil in enumerate(raw_filaments):
            if not isinstance(raw_fil, int):  # pragma: no cover
                raise EstampoError(f"parts[{i}]: expected int filament, got {type(raw_fil)}")
            parts[i].filament = raw_fil
            for obj_name, obj_fil in raw_obj_filaments[i].items():
                if not isinstance(obj_fil, int):  # pragma: no cover
                    raise EstampoError(
                        f"parts[{i}].filaments.{obj_name}: expected int, got {type(obj_fil)}"
                    )
                parts[i].object_filaments[obj_name] = obj_fil
    else:
        if not slicer.filaments:
            # Auto-derive filaments list from string refs + slots map
            # Seed with slots map entries (slot → profile)
            slot_to_name: dict[int, str] = dict(slicer.slots)
            used_slots: set[int] = set(slot_to_name.keys())

            # Collect unique string filament names from parts (default + per-object)
            unique_names: list[str] = []
            for raw_fil in all_raw_filaments:
                if isinstance(raw_fil, str) and raw_fil not in unique_names:
                    unique_names.append(raw_fil)

            # Auto-assign string filaments not already pinned via slots
            next_slot = 1
            for name in unique_names:
                if name not in slot_to_name.values():
                    while next_slot in used_slots:
                        next_slot += 1
                    slot_to_name[next_slot] = name
                    used_slots.add(next_slot)
                    next_slot += 1

            # Build the filaments list — use empty string for unused gap slots
            max_slot = max(slot_to_name.keys())
            slicer.filaments = [slot_to_name.get(s, "") for s in range(1, max_slot + 1)]

        # Build name → index lookup (first occurrence for name-based refs)
        fil_index: dict[str, int] = {}
        for idx, name in enumerate(slicer.filaments):
            if name not in fil_index:
                fil_index[name] = idx + 1

        for i, raw_fil in enumerate(raw_filaments):
            if isinstance(raw_fil, str):
                if raw_fil not in fil_index:
                    raise EstampoError(
                        f"parts[{i}]: filament '{raw_fil}' not in "
                        f"[slicer].filaments {slicer.filaments}"
                    )
                parts[i].filament = fil_index[raw_fil]
            else:
                # Integer slot ref — validate against slots map if present
                if slicer.slots and raw_fil not in slicer.slots:
                    raise EstampoError(
                        f"parts[{i}]: filament slot {raw_fil} not defined in [slicer.slots]"
                    )
                parts[i].filament = raw_fil

            # Resolve per-object filament overrides for this part
            for obj_name, obj_fil in raw_obj_filaments[i].items():
                if isinstance(obj_fil, str):
                    if obj_fil not in fil_index:
                        raise EstampoError(
                            f"parts[{i}].filaments.{obj_name}: '{obj_fil}' not in "
                            f"[slicer].filaments {slicer.filaments}"
                        )
                    parts[i].object_filaments[obj_name] = fil_index[obj_fil]
                else:
                    if slicer.slots and obj_fil not in slicer.slots:
                        raise EstampoError(
                            f"parts[{i}].filaments.{obj_name}: slot {obj_fil} "
                            f"not defined in [slicer.slots]"
                        )
                    parts[i].object_filaments[obj_name] = obj_fil


def _parse_slots(raw: dict) -> dict[int, str]:
    """Parse and validate a slots mapping from raw TOML data."""
    slots_parsed: dict[int, str] = {}
    for key, profile in raw.get("slots", {}).items():
        try:
            slot_num = int(key)
        except (TypeError, ValueError):
            raise EstampoError(f"slicer.slots: key '{key}' must be an integer slot number")
        if slot_num < 1:
            raise EstampoError(f"slicer.slots: slot must be >= 1, got {slot_num}")
        if not isinstance(profile, str) or not profile.strip():
            raise EstampoError(f"slicer.slots[{slot_num}]: profile name must be a non-empty string")
        slots_parsed[slot_num] = profile
    return slots_parsed


def _parse_orca_config(raw: dict) -> OrcaSlicerConfig:
    """Build an OrcaSlicerConfig from a raw TOML dict."""
    return OrcaSlicerConfig(
        printer=raw.get("printer"),
        process=raw.get("process"),
        filaments=raw.get("filaments", []),
        slots=_parse_slots(raw),
        overrides=raw.get("overrides", {}),
        machine_overrides=raw.get("machine_overrides", {}),
        filament_overrides=raw.get("filament_overrides", {}),
    )


def _parse_cura_config(raw: dict) -> CuraSlicerConfig:
    """Build a CuraSlicerConfig from a raw TOML dict."""
    return CuraSlicerConfig(
        printer=raw.get("printer"),
        overrides=raw.get("overrides", {}),
    )


def load_config(path: Path) -> EstampoConfig:
    """Load and validate an estampo.toml file."""
    path = path.resolve()
    if not path.exists():
        raise EstampoError(f"Config file not found: {path}")

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    base_dir = path.parent

    # Plate config
    plate_raw = raw.get("plate", {})
    size = tuple(plate_raw.get("size", [256.0, 256.0]))
    if len(size) != 2 or any(s <= 0 for s in size):
        raise EstampoError(f"plate.size must be two positive numbers, got {size}")
    plate = PlateConfig(size=size, padding=float(plate_raw.get("padding", 5.0)))

    # Slicer config
    slicer_raw = raw.get("slicer", {})
    engine = slicer_raw.get("engine", "orca")
    if engine not in ("orca", "cura"):
        raise EstampoError(f"slicer.engine must be 'orca' or 'cura', got '{engine}'")

    # Engine-namespaced sections: [slicer.orca] and/or [slicer.cura]
    orca_raw = slicer_raw.get("orca")
    cura_raw = slicer_raw.get("cura")

    # Reject legacy flat format (keys directly under [slicer])
    _legacy_keys = {
        "printer",
        "process",
        "filaments",
        "slots",
        "machine_overrides",
        "filament_overrides",
    }
    if _legacy_keys & slicer_raw.keys() and not (
        isinstance(orca_raw, dict) or isinstance(cura_raw, dict)
    ):
        raise EstampoError(
            "Flat [slicer] config format is no longer supported.\n"
            "Move engine-specific settings to [slicer.orca] or [slicer.cura].\n"
            "Run 'estampo init' to generate the new format."
        )

    orca_cfg = _parse_orca_config(orca_raw or {})
    cura_cfg = _parse_cura_config(cura_raw or {})

    # Populate active-engine facade fields from the selected engine's sub-config
    if engine == "orca":
        active_printer = orca_cfg.printer
        active_process = orca_cfg.process
        active_filaments = orca_cfg.filaments
        active_slots = orca_cfg.slots
        active_overrides = orca_cfg.overrides
        active_machine_overrides = orca_cfg.machine_overrides
        active_filament_overrides = orca_cfg.filament_overrides
    else:
        # CuraEngine: printer definition + flat overrides
        active_printer = cura_cfg.printer
        active_process = None
        active_filaments = []
        active_slots = {}
        active_overrides = cura_cfg.overrides
        active_machine_overrides = {}
        active_filament_overrides = {}

    slicer = SlicerConfig(
        engine=engine,
        version=slicer_raw.get("version"),
        bed_type=slicer_raw.get("bed_type"),
        profiles_dir=slicer_raw.get("profiles_dir", "profiles"),
        orca=orca_cfg,
        cura=cura_cfg,
        printer=active_printer,
        process=active_process,
        filaments=active_filaments,
        slots=active_slots,
        overrides=active_overrides,
        machine_overrides=active_machine_overrides,
        filament_overrides=active_filament_overrides,
    )

    # Parts — first pass: parse everything except filament resolution
    parts_raw = raw.get("parts", [])
    if not parts_raw:
        raise EstampoError("At least one [[parts]] entry is required")

    parts = []
    raw_filaments: list[int | str] = []  # preserve raw filament values for resolution
    raw_obj_filaments: list[dict[str, int | str]] = []  # per-part object filament overrides
    for i, p in enumerate(parts_raw):
        if "file" not in p:
            raise EstampoError(f"parts[{i}]: 'file' is required")
        orient = p.get("orient", "flat")
        if orient not in VALID_ORIENTS:
            raise EstampoError(f"parts[{i}]: orient must be one of {VALID_ORIENTS}, got '{orient}'")
        file_path = base_dir / p["file"]
        if not file_path.exists():
            raise EstampoError(f"parts[{i}]: file not found: {file_path}")
        copies = int(p.get("copies", 1))
        if copies < 1:
            raise EstampoError(f"parts[{i}]: copies must be >= 1, got {copies}")
        raw_fil = p.get("filament", 1)
        if isinstance(raw_fil, str):
            if not raw_fil.strip():
                raise EstampoError(f"parts[{i}]: filament name must not be empty")
        else:
            raw_fil = int(raw_fil)
            if raw_fil < 1:
                raise EstampoError(f"parts[{i}]: filament must be >= 1, got {raw_fil}")
        raw_filaments.append(raw_fil)

        # Per-object filament overrides for multi-object 3MF files
        obj_fils_raw: dict[str, int | str] = {}
        for obj_name, obj_fil in p.get("filaments", {}).items():
            if isinstance(obj_fil, str):
                if not obj_fil.strip():
                    raise EstampoError(
                        f"parts[{i}].filaments.{obj_name}: filament name must not be empty"
                    )
            else:
                obj_fil = int(obj_fil)
                if obj_fil < 1:
                    raise EstampoError(
                        f"parts[{i}].filaments.{obj_name}: filament must be >= 1, got {obj_fil}"
                    )
            obj_fils_raw[obj_name] = obj_fil
        raw_obj_filaments.append(obj_fils_raw)

        rotate = p.get("rotate")
        if rotate is not None:
            if not isinstance(rotate, list) or len(rotate) != 3:
                raise EstampoError(f"parts[{i}]: rotate must be [rx, ry, rz], got {rotate}")
            rotate = [float(r) for r in rotate]
        scale = float(p.get("scale", 1.0))
        if scale <= 0:
            raise EstampoError(f"parts[{i}]: scale must be > 0, got {scale}")
        obj_name = p.get("object")
        if obj_name is not None:
            if not isinstance(obj_name, str) or not obj_name.strip():
                raise EstampoError(f"parts[{i}]: object must be a non-empty string")
            if obj_fils_raw:
                raise EstampoError(f"parts[{i}]: cannot use both 'object' and [parts.filaments]")
        sequence = int(p.get("sequence", 1))
        if sequence < 1:
            raise EstampoError(f"parts[{i}]: sequence must be >= 1, got {sequence}")
        parts.append(
            PartConfig(
                file=file_path,
                copies=copies,
                orient=orient,
                rotate=rotate,
                filament=1,  # placeholder, resolved below
                scale=scale,
                object=obj_name,
                sequence=sequence,
            )
        )

    _resolve_filaments(parts, slicer, raw_filaments, raw_obj_filaments)

    # Pipeline config (optional)
    from estampo.pipeline import STAGE_OUTPUTS

    pipeline_raw = raw.get("pipeline", {})
    pipeline_stages = pipeline_raw.get("stages", list(DEFAULT_STAGES))
    if not isinstance(pipeline_stages, list):
        raise EstampoError("pipeline.stages must be a list of stage names")
    for s in pipeline_stages:
        if not isinstance(s, str) or not s.strip():
            raise EstampoError(f"pipeline.stages: each stage must be a non-empty string, got {s!r}")
        if s not in STAGE_OUTPUTS:
            raise EstampoError(
                f"pipeline.stages: unknown stage '{s}'. Valid stages: {sorted(STAGE_OUTPUTS)}"
            )
    pipeline = PipelineConfig(stages=pipeline_stages)

    # Printer config (optional)
    printer = None
    printer_raw = raw.get("printer")
    if printer_raw is not None:
        # Reject secrets in project TOML — they belong in credentials.toml
        for secret_field in ("ip", "access_code", "serial", "mode"):
            if secret_field in printer_raw:
                raise EstampoError(
                    f"printer.{secret_field} should not be in project config. "
                    f"Use 'estampo setup' to configure printers in credentials.toml."
                )
        name = printer_raw.get("name")
        if not name:
            raise EstampoError("printer.name is required — it references credentials.toml")
        printer = PrinterConfig(name=name)

    # Top-level project name (optional)
    project_name: str | None = raw.get("name")
    if project_name is not None:
        if not isinstance(project_name, str) or not project_name.strip():
            raise EstampoError("name must be a non-empty string")
        project_name = project_name.strip()

    # Top-level output_dir (optional, default "estampo_output")
    output_dir: str = raw.get("output_dir", "estampo_output")
    if not isinstance(output_dir, str) or not output_dir.strip():
        raise EstampoError("output_dir must be a non-empty string")
    output_dir = output_dir.strip()

    return EstampoConfig(
        plate=plate,
        slicer=slicer,
        parts=parts,
        base_dir=base_dir,
        name=project_name,
        output_dir=output_dir,
        printer=printer,
        pipeline=pipeline,
    )

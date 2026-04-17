"""Discover, resolve, and pin slicer profiles."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from estampo import EstampoError
from estampo.cura import (  # noqa: F401
    _deep_merge_cura_overrides,
    _squash_cura_def,
    extract_cura_docker_defs,
    load_cura_definition_map,
    pin_cura_definitions,
)

# Re-export engine-specific profile symbols for backward compatibility.
from estampo.orca import (  # noqa: F401
    SYSTEM_DIRS,
    _resolve_profile_data_from_dir,
    _system_dirs,
    extract_docker_profiles,
)

log = logging.getLogger(__name__)

CATEGORIES = ("machine", "process", "filament")


def _is_path(value: str) -> bool:
    """Check if a value looks like a file path rather than a profile name."""
    return "/" in value or "\\" in value


# Engines that use inline settings and have no extractable profile chain.
_INLINE_ENGINES: frozenset[str] = frozenset()


def discover_profiles(engine: str) -> dict[str, dict[str, Path]]:
    """Scan system directories for available profiles.

    Returns {"machine": {"Name": Path, ...}, "process": {...}, "filament": {...}}
    """
    if engine in _INLINE_ENGINES:
        return {cat: {} for cat in CATEGORIES}

    base = SYSTEM_DIRS.get(engine)
    if base is None:
        # CuraEngine has no system install directory — return empty
        if engine == "cura":
            return {cat: {} for cat in CATEGORIES}
        supported = sorted({*SYSTEM_DIRS, "cura"})
        raise ValueError(f"Unknown engine: '{engine}'. Supported: {supported}")

    # Expected JSON "type" field for each category.
    # machine_model profiles (e.g. "Bambu Lab P1S") define the printer
    # but cannot be passed to the slicer — only "machine" profiles
    # (e.g. "Bambu Lab P1S 0.4 nozzle") are valid for slicing.
    _VALID_TYPES = {
        "machine": "machine",
        "process": "process",
        "filament": "filament",
    }

    result: dict[str, dict[str, Path]] = {}
    for category in CATEGORIES:
        cat_dir = base / category
        profiles: dict[str, Path] = {}
        expected_type = _VALID_TYPES[category]
        if cat_dir.is_dir():
            for f in sorted(cat_dir.glob("*.json")):
                name = f.stem
                # Skip internal/template files
                if "template" in name or name.startswith("fdm_"):
                    continue
                # Only include profiles with the correct type
                try:
                    with open(f) as fh:
                        data = json.load(fh)
                    if data.get("type") != expected_type:
                        continue
                except (json.JSONDecodeError, OSError):
                    continue
                profiles[name] = f
        result[category] = profiles

    return result


_BUNDLED_DIR = Path(__file__).parent / "data"


def load_bundled_profiles(engine: str, version: str | None = None) -> dict[str, list[str]]:
    """Load profile names bundled with the package.

    Looks for ``src/estampo/data/profiles.<engine>.<version>.json``.
    Falls back to the highest available version if the requested one is missing.

    Returns a dict of ``{category: [name, ...]}`` or an empty dict if none found.
    """
    data = _load_bundled_manifest(engine, version)
    if not data:
        return {}
    return {cat: _extract_names(data.get(cat, [])) for cat in CATEGORIES}


def _load_bundled_manifest(engine: str, version: str | None = None) -> dict | None:
    """Load the raw bundled manifest JSON for an engine."""
    if version:
        exact = _BUNDLED_DIR / f"profiles.{engine}.{version}.json"
        if exact.exists():
            with open(exact) as f:
                return json.load(f)

    # Fall back to highest bundled version
    candidates = sorted(_BUNDLED_DIR.glob(f"profiles.{engine}.*.json"))
    if candidates:
        with open(candidates[-1]) as f:
            return json.load(f)

    return None


def _extract_names(items: list) -> list[str]:
    """Extract name strings from a manifest list.

    OrcaSlicer manifests have plain strings.  CuraEngine manifests have
    ``{"name": "...", "id": "..."}`` objects.
    """
    names: list[str] = []
    for item in items:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and "name" in item:
            names.append(item["name"])
    return names


def discover_profile_names(
    engine: str,
    version: str | None = None,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
) -> tuple[dict[str, list[str]], str]:
    """Discover profile names with full fallback chain.

    Priority:
    1. System profiles (local OrcaSlicer install)
    2. Pinned profiles in the project repo
    3. Bundled profiles shipped with the package

    Returns ``(names_dict, source)`` where *source* is one of
    ``"system"``, ``"pinned"``, ``"bundled"``, or ``"none"``.
    """
    # 1. System profiles
    try:
        system = discover_profiles(engine)
    except ValueError:
        system = {}
    if any(system.values()):
        return {cat: sorted(system.get(cat, {}).keys()) for cat in CATEGORIES}, "system"

    # 2. Pinned profiles in repo (engine-namespaced path: profiles/<engine>/)
    if project_dir:
        # CuraEngine uses .def.json files in a definitions/ directory
        if engine == "cura":
            defs_dir = project_dir / profiles_dir / "cura" / "definitions"
            if defs_dir.is_dir():
                names = sorted(
                    f.name.removesuffix(".def.json")
                    for f in defs_dir.glob("*.def.json")
                    if f.is_file()
                )
                if names:
                    # Read human names from the definition files
                    display_names: list[str] = []
                    for stem in names:
                        try:
                            with open(defs_dir / f"{stem}.def.json") as fh:
                                d = json.load(fh)
                            display_names.append(d.get("name", stem))
                        except (json.JSONDecodeError, OSError):
                            display_names.append(stem)
                    pinned_cura: dict[str, list[str]] = {
                        "machine": display_names,
                        "process": [],
                        "filament": [],
                    }
                    return pinned_cura, "pinned"

        base = project_dir / profiles_dir / engine
        pinned: dict[str, list[str]] = {}
        for cat in CATEGORIES:
            cat_dir = base / cat
            if cat_dir.is_dir():
                pinned[cat] = sorted(f.stem for f in cat_dir.glob("*.json") if f.is_file())
        if any(pinned.values()):
            return pinned, "pinned"

    # 3. Bundled profiles
    bundled = load_bundled_profiles(engine, version)
    if any(bundled.values()):
        return bundled, "bundled"

    return {cat: [] for cat in CATEGORIES}, "none"


# ---------------------------------------------------------------------------
# Profile resolution
# ---------------------------------------------------------------------------


def resolve_profile(
    name_or_path: str,
    engine: str,
    category: str,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
    docker_profile_dir: Path | None = None,
) -> Path:
    """Resolve a profile name or path to an absolute file path.

    Resolution order:
    1. If it looks like a path, use it directly
    2. Check <project_dir>/<profiles_dir>/<category>/<name>.json
    3. Check Docker-extracted profiles (if provided)
    4. Check slicer system directory
    """
    if _is_path(name_or_path):
        if ".." in Path(name_or_path).parts:
            raise ValueError(f"Profile path must not contain '..': {name_or_path}")
        path = Path(name_or_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Profile path not found: {path}")
        return path

    # Check local pinned profiles (engine-namespaced path: profiles/<engine>/)
    if project_dir:
        local = project_dir / profiles_dir / engine / category / f"{name_or_path}.json"
        if local.exists():
            log.debug("Resolved '%s' from pinned profiles: %s", name_or_path, local)
            return local

    # Check Docker-extracted profiles (version-matched)
    if docker_profile_dir:
        docker = docker_profile_dir / category / f"{name_or_path}.json"
        if docker.exists():
            log.debug("Resolved '%s' from Docker image profiles: %s", name_or_path, docker)
            return docker

    # Check system directory
    sys_base = SYSTEM_DIRS.get(engine)
    if sys_base:
        system = sys_base / category / f"{name_or_path}.json"
        if system.exists():
            log.debug("Resolved '%s' from system profiles: %s", name_or_path, system)
            return system

    raise FileNotFoundError(
        f"Profile '{name_or_path}' not found in category '{category}' "
        f"for engine '{engine}'. Run 'estampo profiles list' to see available profiles."
    )


def resolve_profile_data(
    name_or_path: str,
    engine: str,
    category: str,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
    docker_profile_dir: Path | None = None,
) -> dict:
    """Resolve a profile and flatten its full inheritance chain.

    Returns a merged dict with all inherited values resolved,
    with the 'inherits' key removed so the slicer uses it as-is.
    """
    path = resolve_profile(
        name_or_path, engine, category, project_dir, profiles_dir, docker_profile_dir
    )
    base = SYSTEM_DIRS.get(engine)

    chain = []
    current = path
    seen: set[str] = set()
    while current:
        if str(current) in seen:
            break
        seen.add(str(current))
        with open(current) as f:
            data = json.load(f)
        chain.append(data)
        parent_name = data.get("inherits")
        if not parent_name:
            break
        # Check sibling directory, then Docker-extracted dir, then system dir
        sibling = current.parent / f"{parent_name}.json"
        docker = (
            (docker_profile_dir / category / f"{parent_name}.json") if docker_profile_dir else None
        )
        system = (base / category / f"{parent_name}.json") if base else None
        if sibling.exists():
            current = sibling
        elif docker and docker.exists():
            current = docker
        elif system and system.exists():
            current = system
        else:
            log.warning(
                "Profile '%s' inherits from '%s' but parent not found",
                current.stem,
                parent_name,
            )
            break

    # Merge root-first so leaf values override parents
    merged: dict = {}
    for data in reversed(chain):
        merged.update(data)
    merged.pop("inherits", None)
    return merged


def pinned_profiles_version(
    project_dir: Path,
    profiles_dir: str = "profiles",
    engine: str | None = None,
) -> str | None:
    """Read the slicer version that pinned profiles were created with.

    Checks ``profiles/<engine>/.slicer-version``.

    Returns ``None`` if no marker file exists (pre-marker pinned profiles).
    """
    if engine:
        marker = project_dir / profiles_dir / engine / ".slicer-version"
        if marker.exists():
            return marker.read_text().strip()
    return None


def validate_override_keys(
    overrides: dict[str, object],
    engine: str,
    process: str | None,
    project_dir: Path | None = None,
) -> list[str]:
    """Check that override keys exist in the resolved process profile.

    Returns a list of warning strings for unknown keys, including
    cross-engine detection (e.g. OrcaSlicer key used in CuraEngine config)
    and "did you mean?" suggestions.
    """
    if not overrides:
        return []

    profile_keys: set[str] = set()
    if process:
        try:
            data = resolve_profile_data(process, engine, "process", project_dir)
            profile_keys = set(data.keys())
        except (EstampoError, FileNotFoundError, OSError):
            log.debug("Cannot resolve process profile for override validation", exc_info=True)

    # Load known settings from bundled settings JSON files
    engine_keys = _load_engine_settings(engine)
    other_engine = "cura" if engine == "orca" else "orca"
    other_keys = _load_engine_settings(other_engine)
    cross_map = _cross_engine_map()

    all_valid = profile_keys | engine_keys
    warnings: list[str] = []

    for key in overrides:
        if key in all_valid:
            continue

        # Cross-engine detection: key belongs to the other engine
        if key in other_keys:
            suggestion = cross_map.get(key)
            if suggestion and suggestion in all_valid:
                warnings.append(
                    f"slicer.overrides key '{key}' is an {other_engine} setting "
                    f"— did you mean '{suggestion}'?"
                )
            else:
                warnings.append(
                    f"slicer.overrides key '{key}' is an {other_engine} setting, "
                    f"not a valid {engine} key"
                )
        else:
            # Unknown key — try fuzzy match against engine keys
            hint = _closest_setting(key, all_valid)
            msg = f"slicer.overrides key '{key}' not found in {engine} settings"
            if hint:
                msg += f" — did you mean '{hint}'?"
            warnings.append(msg)

    return warnings


def _load_engine_settings(engine: str) -> set[str]:
    """Load known setting keys from bundled settings JSON."""
    settings_file = Path(__file__).parent / "data" / f"{engine}-settings.json"
    if not settings_file.exists():
        return set()
    try:
        data = json.loads(settings_file.read_text())
        return {s["key"] for s in data.get("settings", [])}
    except (json.JSONDecodeError, KeyError, OSError):
        return set()


def _cross_engine_map() -> dict[str, str]:
    """Bidirectional mapping between OrcaSlicer and CuraEngine setting names."""
    orca_to_cura = {
        "wall_loops": "wall_line_count",
        "top_shell_layers": "top_layers",
        "bottom_shell_layers": "bottom_layers",
        "sparse_infill_density": "infill_sparse_density",
        "sparse_infill_pattern": "infill_pattern",
        "initial_layer_print_height": "layer_height_0",
        "enable_support": "support_enable",
        "support_threshold_angle": "support_angle",
        "nozzle_temperature": "material_print_temperature",
        "bed_temperature": "material_bed_temperature",
        "outer_wall_speed": "speed_wall_0",
        "inner_wall_speed": "speed_wall_x",
        "sparse_infill_speed": "speed_infill",
        "travel_speed": "speed_travel",
        "retraction_length": "retraction_amount",
        "brim_type": "adhesion_type",
        "seam_position": "z_seam_type",
        "fan_min_speed": "cool_fan_speed_min",
        "fan_max_speed": "cool_fan_speed_max",
        "ironing_type": "ironing_enabled",
        "xy_hole_compensation": "hole_xy_offset",
        "xy_contour_compensation": "xy_offset",
    }
    # Build bidirectional map
    cross: dict[str, str] = {}
    cross.update(orca_to_cura)
    cross.update({v: k for k, v in orca_to_cura.items()})
    return cross


def _closest_setting(name: str, candidates: set[str]) -> str | None:
    """Find the closest matching setting key."""
    if not candidates:
        return None
    name_lower = name.lower()
    # Substring match
    for c in sorted(candidates):
        if name_lower in c.lower() or c.lower() in name_lower:
            return c
    # Common word overlap (split on underscores)
    name_parts = set(name_lower.split("_"))
    best = None
    best_score = 0
    for c in candidates:
        c_parts = set(c.lower().split("_"))
        overlap = len(name_parts & c_parts)
        if overlap > best_score:
            best_score = overlap
            best = c
    return best if best_score >= 2 else None


def pin_profiles(
    engine: str,
    printer: str | None,
    process: str | None,
    filaments: list[str],
    project_dir: Path,
    docker_version: str | None = None,
    profiles_dir: str = "profiles",
) -> list[Path]:
    """Flatten and save profiles into <project_dir>/<profiles_dir>/ for reproducibility.

    Profiles are fully resolved (inheritance chain merged, 'inherits' removed)
    so builds are independent of the installed slicer version.

    When a profile is not found locally, falls back to extracting it from
    the Docker image (if ``docker_version`` is provided).

    Returns list of pinned file paths.
    """
    import shutil

    if engine in _INLINE_ENGINES:
        log.info("Engine '%s' uses inline settings — nothing to pin.", engine)
        return []

    # CuraEngine: delegate to definition-specific pinning
    if engine == "cura":
        return pin_cura_definitions(
            printer=printer,
            project_dir=project_dir,
            docker_version=docker_version,
            profiles_dir=profiles_dir,
        )

    pinned: list[Path] = []

    items: list[tuple[str, str]] = []
    if printer:
        items.append(("machine", printer))
    if process:
        items.append(("process", process))
    for f in filaments:
        items.append(("filament", f))

    # When docker_version is specified, extract Docker profiles upfront so they
    # take priority over local system profiles.  This ensures pinned profiles
    # match what the Docker slicer will actually use at slice time.
    docker_dir: Path | None = None
    if docker_version:
        docker_dir = extract_docker_profiles(docker_version)

    # Engine-namespaced base: profiles/<engine>/
    engine_base = project_dir / profiles_dir / engine

    try:
        for category, name in items:
            if _is_path(name):
                log.info("Skipping '%s' (already a path)", name)
                continue

            dest_dir = engine_base / category
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{name}.json"

            try:
                data = resolve_profile_data(
                    name, engine, category, project_dir, profiles_dir, docker_dir
                )
            except FileNotFoundError:
                if not docker_version:
                    raise EstampoError(
                        f"Profile '{name}' not found locally. Set slicer.version in "
                        "your config or install the slicer locally to access profiles."
                    )
                raise

            with open(dest, "w") as fh:
                json.dump(data, fh, indent=4)
            source = "Docker" if docker_dir else "system"
            log.info("Pinned %s → %s (flattened, from %s)", name, dest, source)
            pinned.append(dest)

        # Write a version marker so slice-time can detect stale profiles.
        if docker_version:
            marker = engine_base / ".slicer-version"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(docker_version + "\n")
            log.debug("Wrote slicer version marker: %s", marker)
    finally:
        if docker_dir:
            shutil.rmtree(docker_dir, ignore_errors=True)

    return pinned


# ---------------------------------------------------------------------------
# Profile import (add)
# ---------------------------------------------------------------------------

# Keys commonly found in each profile category (OrcaSlicer and CuraEngine)
_CATEGORY_KEYS: dict[str, set[str]] = {
    "machine": {
        # OrcaSlicer
        "printer_model",
        "machine_start_gcode",
        "printable_area",
        # CuraEngine
        "machine_width",
        "machine_depth",
        "machine_height",
        "machine_heated_bed",
    },
    "process": {"layer_height", "wall_loops", "sparse_infill_density"},
    "filament": {"filament_type", "filament_density", "nozzle_temperature"},
}


def is_cura_definition(data: dict) -> bool:
    """Return True if *data* looks like a CuraEngine ``.def.json`` file."""
    return (
        isinstance(data.get("version"), int)
        and isinstance(data.get("overrides"), dict)
        and "metadata" in data
    )


def detect_category(data: dict) -> str | None:
    """Guess the profile category from its JSON keys."""
    # CuraEngine .def.json files are always machine definitions
    if is_cura_definition(data):
        return "machine"

    scores: dict[str, int] = {}
    keys = set(data.keys())
    for cat, markers in _CATEGORY_KEYS.items():
        scores[cat] = len(keys & markers)
    best = max(scores, key=lambda c: scores[c])
    return best if scores[best] > 0 else None


def add_profile(
    source: str,
    project_dir: Path,
    category: str | None = None,
    name: str | None = None,
    profiles_dir: str = "profiles",
    engine: str = "orca",
) -> Path:
    """Import a profile JSON file into the project's profiles directory.

    Args:
        source: A local file path or URL (http/https).
        project_dir: The project root containing the profiles directory.
        category: Profile category (machine/process/filament).
            Auto-detected from JSON content if not provided.
        name: Profile name (default: filename stem or JSON ``"name"`` field).

    Returns:
        Path to the imported profile file.
    """
    # Load the JSON from source
    if source.startswith(("http://", "https://")):
        try:
            with urlopen(source, timeout=30) as resp:  # noqa: S310
                raw = resp.read()
        except (URLError, OSError) as e:
            raise EstampoError(f"Failed to download profile from {source}: {e}") from e
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise EstampoError(f"Invalid JSON from {source}: {e}") from e
        default_name = Path(source.split("/")[-1]).stem
        if default_name.endswith(".def"):
            default_name = default_name[:-4]
    else:
        path = Path(source)
        if not path.exists():
            raise EstampoError(f"Profile file not found: {source}")
        with open(path) as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise EstampoError(f"Invalid JSON in {source}: {e}") from e
        default_name = path.stem
        # Handle .def.json double extension (e.g. "my_printer.def.json" → "my_printer")
        if default_name.endswith(".def"):
            default_name = default_name[:-4]

    if not isinstance(data, dict):
        raise EstampoError(f"Profile must be a JSON object, got {type(data).__name__}")

    # Determine category
    if not category:
        category = detect_category(data)
        if not category:
            raise EstampoError(
                f"Cannot auto-detect profile category for {source}. "
                "Use --category to specify machine, process, or filament."
            )

    if category not in CATEGORIES:
        raise EstampoError(
            f"Invalid category '{category}'. Must be one of: {', '.join(CATEGORIES)}"
        )

    # Determine name
    profile_name = name or data.get("name") or default_name

    # CuraEngine .def.json files go to profiles/cura/definitions/
    if engine == "cura" and is_cura_definition(data):
        dest_dir = project_dir / profiles_dir / "cura" / "definitions"
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Use the filename stem as ID (e.g. "bambulab_a1")
        def_id = name or default_name
        dest = dest_dir / f"{def_id}.def.json"
    elif engine == "cura":
        dest_dir = project_dir / profiles_dir / engine / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{profile_name}.json"
    else:
        dest_dir = project_dir / profiles_dir / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{profile_name}.json"

    with open(dest, "w") as fh:
        json.dump(data, fh, indent=4)

    # For CuraEngine machine defs, copy referenced extruder definitions
    # from the same source directory.
    if (
        engine == "cura"
        and is_cura_definition(data)
        and not source.startswith(("http://", "https://"))
    ):
        src_dir = Path(source).parent
        trains = data.get("metadata", {}).get("machine_extruder_trains", {})
        for extruder_id in trains.values():
            ext_filename = f"{extruder_id}.def.json"
            ext_src = src_dir / ext_filename
            ext_dest = dest_dir / ext_filename
            if ext_src.exists() and not ext_dest.exists():
                with open(ext_src) as f:
                    ext_data = json.load(f)
                with open(ext_dest, "w") as fh:
                    json.dump(ext_data, fh, indent=4)
                log.info("Added extruder definition → %s", ext_dest)

    # Warn about unresolved inheritance
    if data.get("inherits"):
        parent = data["inherits"]
        # Check for parent in same directory (with .def.json for Cura defs)
        if dest.name.endswith(".def.json"):
            parent_path = dest_dir / f"{parent}.def.json"
        else:
            parent_path = dest_dir / f"{parent}.json"
        if not parent_path.exists():
            log.warning(
                "Profile '%s' inherits from '%s' which is not in %s. "
                "Add the parent profile or use 'estampo profiles pin' to flatten.",
                profile_name,
                parent,
                dest_dir,
            )

    return dest

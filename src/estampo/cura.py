"""CuraEngine slicer backend.

Slices STL files using CuraEngine via Docker, with a printer definition
(inheriting from fdmprinter).  Produces plain G-code.

Uses CuraEngine 5.12.0 built from source, packaged in a minimal Docker
image with bundled printer definitions.  Default printer: Ultimaker 2.
"""

from __future__ import annotations

import importlib.resources
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from estampo import EstampoError
from estampo.constants import DEFAULT_PLATE_SIZE

log = logging.getLogger(__name__)

ENGINE_NAME = "CuraEngine"
ENGINE_KEY = "cura"

DOCKERHUB_REPO = "estampo/estampo"
CURAENGINE_VERSION = "5.12.0"


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------


def _default_binary_path() -> Path:
    """Return the platform-specific default path for CuraEngine."""
    if sys.platform == "darwin":
        return Path("/Applications/UltiMaker Cura.app/Contents/MacOS/CuraEngine")
    elif sys.platform == "win32":
        return Path("C:/Program Files/UltiMaker Cura/CuraEngine.exe")
    return Path("/usr/local/bin/CuraEngine")


def find_binary() -> Path:
    """Locate the CuraEngine executable on this system.

    Raises ``FileNotFoundError`` if not found.
    """
    path = _default_binary_path()
    if path.exists():
        return path

    for name in ("CuraEngine", "curaengine"):
        found = shutil.which(name)
        if found:
            return Path(found)

    raise FileNotFoundError(f"CuraEngine not found at {path} or on PATH. Is it installed?")


# Definitions directory inside the Docker image (fdmprinter.def.json etc.)
_DEFS_DIR = "/opt/cura/definitions"
# Extruder definitions directory inside the Docker image
_EXTRUDERS_DIR = "/opt/cura/extruders"

# Bundled definition files shipped with estampo
_DATA_PKG = "estampo.data"
_DATA_DIR = Path(__file__).parent / "data"

# Bundled machine profile JSONs (nozzle/material overrides per printer)
_BUNDLED_MACHINE_DIR = _DATA_DIR / "cura" / "machine"


def _local_defs_path(staging: Path) -> str:
    """Build the ``-d`` search path for local CuraEngine invocation.

    Includes the staging directory, bundled estampo data, and any system
    paths from ``CURA_ENGINE_SEARCH_PATH`` (set in Docker images).
    """
    parts = [str(staging), str(_DATA_DIR)]
    env_path = os.environ.get("CURA_ENGINE_SEARCH_PATH", "")
    if env_path:
        parts.extend(env_path.split(":"))
    return ":".join(parts)


def _bundled_def_path(name: str) -> Path:
    """Return the filesystem path of a bundled definition file."""
    ref = importlib.resources.files(_DATA_PKG).joinpath(name)
    # importlib.resources may return a traversable; as_posix works for
    # files already on disk (installed via pip / editable).
    return Path(str(ref))


def _printer_is_url(printer: str) -> bool:
    return printer.startswith(("http://", "https://"))


def _printer_is_file(printer: str, project_dir: Path | None) -> Path | None:
    """Return the resolved Path if *printer* points to an existing .def.json file."""
    p = Path(printer)
    if not p.is_absolute() and project_dir:
        p = project_dir / p
    if p.suffix == ".json" and p.exists() and p.is_file():
        return p
    return None


def _fetch_printer_def(
    printer: str,
    project_dir: Path | None,
    staging: Path,
) -> str | None:
    """If *printer* is a URL or file path, put the definition in *staging*.

    Returns the definition filename (e.g. ``bambox_p1s.def.json``), or
    None if *printer* is a plain name/ID that should go through normal resolution.
    """
    import urllib.request

    if _printer_is_url(printer):
        filename = printer.rsplit("/", 1)[-1]
        if not filename.endswith(".def.json"):
            filename += ".def.json"
        dest = staging / filename
        if not dest.exists():
            log.info("Downloading printer definition from %s", printer)
            urllib.request.urlretrieve(printer, dest)  # noqa: S310
        return filename

    file_path = _printer_is_file(printer, project_dir)
    if file_path:
        dest = staging / file_path.name
        shutil.copy2(file_path, dest)
        return file_path.name

    return None


def _resolve_def_name(printer_name: str | None) -> str:
    """Map a human printer name to a definition filename stem.

    Uses the bundled manifest to map e.g. ``"Ultimaker 2"`` →
    ``"ultimaker2"``.  Tries several fallbacks:

    1. Exact match in manifest (``"Ultimaker 2"``).
    2. Already a known definition ID (``"ultimaker2"``).
    2b. Looks like a raw definition ID (``"my_custom_printer"``).
    3. Case-insensitive match against manifest names.
    4. Strip nozzle suffix (``"My Printer 0.4 nozzle"`` → retry).

    Raises :class:`EstampoError` if nothing matches.
    """
    if not printer_name:
        return "ultimaker2"

    def_map = load_cura_definition_map()

    # 1. Exact match
    if printer_name in def_map:
        return def_map[printer_name]

    # 2. Already a definition ID (value in the map)
    ids = set(def_map.values())
    if printer_name in ids:
        return printer_name

    # 2b. Looks like a raw definition ID (no spaces, e.g. "bambox_p1s").
    # Accept it and let _resolve_def_chain find the file in pinned/bundled defs.
    if " " not in printer_name and printer_name.replace("_", "").replace("-", "").isalnum():
        return printer_name

    # 3. Case-insensitive match
    lower_name = printer_name.lower()
    for name, def_id in def_map.items():
        if name.lower() == lower_name:
            return def_id

    # 4. Strip nozzle suffix pattern like " 0.4 nozzle", " 0.6mm nozzle"
    stripped = re.sub(r"\s+\d+\.?\d*\s*(mm\s+)?nozzle$", "", printer_name, flags=re.IGNORECASE)
    if stripped != printer_name:
        # Retry with stripped name
        if stripped in def_map:
            return def_map[stripped]
        for name, def_id in def_map.items():
            if name.lower() == stripped.lower():
                return def_id

    raise EstampoError(
        f"CuraEngine printer '{printer_name}' not found in the definition manifest. "
        f"Available printers: {', '.join(sorted(def_map.keys()))}. "
        f"Run 'estampo init' to pick a valid printer or check your TOML config."
    )


def _resolve_def_chain(
    def_id: str,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
) -> list[Path]:
    """Resolve a printer definition and its full inheritance chain.

    Returns a list of Paths from leaf (printer) to root, e.g.
    ``[ultimaker2.def.json]``.

    Search order per definition:
    1. Pinned (squashed) in ``profiles/cura/definitions/``
    2. Bundled with estampo in ``src/estampo/data/``
    """
    chain: list[Path] = []
    seen: set[str] = set()
    current_id: str | None = def_id

    while current_id and current_id not in seen:
        seen.add(current_id)
        filename = f"{current_id}.def.json"

        # Search: pinned → bundled
        path: Path | None = None
        if project_dir:
            pinned = project_dir / profiles_dir / "cura" / "definitions" / filename
            if pinned.exists():
                path = pinned
        if path is None:
            bundled = _DATA_DIR / filename
            if bundled.exists():
                path = bundled

        if path is None:
            # Definition not found locally — Docker has built-in defs, so
            # this is only fatal for local (non-Docker) slicing.  Callers
            # that need the file locally will check and raise on their own.
            log.debug(
                "CuraEngine definition '%s' not found locally "
                "(checked pinned + bundled). Docker will provide it.",
                filename,
            )
            break

        chain.append(path)

        # Check for inheritance
        try:
            with open(path) as f:
                data = json.load(f)
            parent = data.get("inherits")
            if parent and isinstance(parent, str):
                current_id = parent
            else:
                break
        except (json.JSONDecodeError, OSError):
            break

    return chain


def _copy_extruder_defs(
    machine_def_path: Path,
    staging: Path,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
) -> None:
    """Copy extruder definition files referenced by a machine definition."""
    try:
        with open(machine_def_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    trains = data.get("metadata", {}).get("machine_extruder_trains", {})
    for extruder_id in trains.values():
        filename = f"{extruder_id}.def.json"
        if (staging / filename).exists():
            continue
        # Search: pinned → bundled
        if project_dir:
            pinned = project_dir / profiles_dir / "cura" / "definitions" / filename
            if pinned.exists():
                shutil.copy2(pinned, staging / filename)
                continue
        bundled = _DATA_DIR / filename
        if bundled.exists():
            shutil.copy2(bundled, staging / filename)


def resolve_cura_bed_size(
    printer_name: str,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
) -> tuple[float, float]:
    """Return (width, depth) for a CuraEngine printer definition.

    Walks the definition chain to find machine_width and machine_depth.
    Falls back to (256, 256) if not found.

    *printer_name* may be a definition name/ID, a local file path, or a URL.
    """
    # URL or local file: read just that file for bed dimensions.
    _is_url = printer_name and _printer_is_url(printer_name)
    _is_file = printer_name and _printer_is_file(printer_name, project_dir)
    if _is_url or _is_file:
        import tempfile
        import urllib.request

        if _printer_is_url(printer_name):
            with tempfile.NamedTemporaryFile(suffix=".def.json", delete=False) as tmp:
                urllib.request.urlretrieve(printer_name, tmp.name)  # noqa: S310
                tmp_path = Path(tmp.name)
            chain = [tmp_path]
        else:
            chain = [_printer_is_file(printer_name, project_dir)]  # type: ignore[list-item]
    else:
        def_id = _resolve_def_name(printer_name)
        chain = _resolve_def_chain(def_id, project_dir, profiles_dir)

    # Search from leaf to root for machine_width/depth
    width: float | None = None
    depth: float | None = None
    for path in chain:
        try:
            with open(path) as f:
                data = json.load(f)
            overrides = data.get("overrides", {})
            if width is None:
                w = overrides.get("machine_width", {})
                if isinstance(w, dict) and "value" in w:
                    width = float(w["value"])
            if depth is None:
                d = overrides.get("machine_depth", {})
                if isinstance(d, dict) and "value" in d:
                    depth = float(d["value"])
            if width is not None and depth is not None:
                break
        except (json.JSONDecodeError, OSError):
            continue

    return (width or DEFAULT_PLATE_SIZE[0], depth or DEFAULT_PLATE_SIZE[1])


def cura_docker_image(version: str | None = None) -> str:
    """Return the Docker image name for a given CuraEngine version."""
    if version:
        return f"{DOCKERHUB_REPO}:cura-{version}"
    return f"{DOCKERHUB_REPO}:cura-{CURAENGINE_VERSION}"


docker_image = cura_docker_image


# ---------------------------------------------------------------------------
# Bundled manifest and definition map
# ---------------------------------------------------------------------------


def load_cura_definition_map(version: str | None = None) -> dict[str, str]:
    """Load a mapping of CuraEngine definition names to IDs.

    Returns ``{"Ultimaker 2": "ultimaker2", ...}``.
    """
    from estampo.profiles import _load_bundled_manifest

    data = _load_bundled_manifest("cura", version)
    if not data:
        return {}
    result: dict[str, str] = {}
    for item in data.get("machine", []):
        if isinstance(item, dict) and "name" in item and "id" in item:
            result[item["name"]] = item["id"]
    return result


# ---------------------------------------------------------------------------
# CuraEngine definition pinning (inheritance squashing)
# ---------------------------------------------------------------------------


def _deep_merge_cura_overrides(base: dict, child: dict) -> dict:
    """Deep-merge CuraEngine overrides dicts.

    Each key maps to a sub-dict like ``{"value": X, "default_value": Y}``.
    Child values override parent values at the per-setting sub-dict level.
    """
    merged = dict(base)
    for key, val in child.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = {**merged[key], **val}
        else:
            merged[key] = val
    return merged


def extract_cura_docker_defs(
    version: str | None = None,
    image: str | None = None,
) -> Path:
    """Extract CuraEngine definitions from a Docker image to a temp directory.

    Extracts both machine definitions (``/opt/cura/definitions``) and extruder
    definitions (``/opt/cura/extruders``) into a single flat directory.

    Returns a Path to a temporary directory containing ``*.def.json`` files.
    The caller is responsible for cleanup.
    """
    import tempfile

    from estampo.docker import copy_from_container, ensure_image, stopped_container

    if not image:
        image = cura_docker_image(version)

    if not ensure_image(image):
        raise EstampoError(f"Docker image {image} is not available and could not be pulled.")

    from estampo import ui

    tmp_dir = Path(tempfile.mkdtemp(prefix="estampo_cura_defs_"))

    with ui.status("Extracting CuraEngine definitions from Docker image"):
        with stopped_container(image) as container_id:
            for container_path in (_DEFS_DIR, _EXTRUDERS_DIR):
                cp = copy_from_container(container_id, f"{container_path}/.", tmp_dir, timeout=60)
                if cp.returncode != 0:
                    raise EstampoError(
                        f"Failed to copy {container_path} from Docker: {cp.stderr.strip()}"
                    )

    return tmp_dir


def _squash_cura_def(def_id: str, defs_dir: Path) -> dict:
    """Walk the inheritance chain for a CuraEngine definition and squash it.

    Reads ``*.def.json`` files from *defs_dir*, follows ``inherits`` links,
    and deep-merges overrides from root to leaf.

    Root definitions like ``fdmprinter`` provide the full settings schema in
    a ``settings`` tree (not ``overrides``).  Since we only merge
    ``overrides``, we must stop before including root definitions and
    preserve ``inherits`` so CuraEngine resolves the base at runtime via
    its ``-d`` search path.
    """
    # Root definitions that provide the full settings schema.  These must
    # NOT be squashed — their ``settings`` tree is too large and not
    # representable as ``overrides``.  CuraEngine resolves them at runtime.
    _ROOT_DEFS = {"fdmprinter", "fdmextruder"}

    chain: list[dict] = []
    current_id: str | None = def_id
    seen: set[str] = set()
    unresolved_parent: str | None = None

    while current_id and current_id not in seen:
        seen.add(current_id)

        # Stop before root definitions — they provide the base schema
        if current_id in _ROOT_DEFS and current_id != def_id:
            unresolved_parent = current_id
            break

        path = defs_dir / f"{current_id}.def.json"
        if not path.exists():
            # Parent not available locally — CuraEngine resolves it at runtime
            unresolved_parent = current_id
            break
        with open(path) as f:
            data = json.load(f)
        chain.append(data)
        parent = data.get("inherits")
        current_id = parent if isinstance(parent, str) else None

    if not chain:
        raise EstampoError(f"CuraEngine definition '{def_id}' not found in {defs_dir}")

    # Merge root-first so leaf overrides take precedence
    merged_overrides: dict = {}
    merged_metadata: dict = {}
    for data in reversed(chain):
        merged_overrides = _deep_merge_cura_overrides(merged_overrides, data.get("overrides", {}))
        merged_metadata.update(data.get("metadata", {}))

    # Build squashed result from the leaf definition
    leaf = chain[0]
    squashed: dict = {
        "version": leaf.get("version", 2),
        "name": leaf.get("name", def_id),
        "metadata": merged_metadata,
        "overrides": merged_overrides,
    }
    if unresolved_parent:
        squashed["inherits"] = unresolved_parent
    return squashed


def pin_cura_definitions(
    printer: str | None,
    project_dir: Path,
    docker_version: str | None = None,
    profiles_dir: str = "profiles",
) -> list[Path]:
    """Pin (squash) a CuraEngine printer definition for reproducible builds.

    Extracts definitions from the Docker image, walks the inheritance chain,
    deep-merges overrides, and writes a standalone ``.def.json`` file.

    Returns list of pinned file paths.
    """
    if not printer:
        log.info("No CuraEngine printer specified — nothing to pin.")
        return []

    # If the printer is a local file path that already exists, it was placed
    # there by 'profiles add' — treat it as already pinned, nothing to squash.
    existing = _printer_is_file(printer, project_dir)
    if existing:
        log.info("Printer definition is a local file — already pinned: %s", existing)
        return [existing]

    def_id = _resolve_def_name(printer)

    bundled_def = _DATA_DIR / f"{def_id}.def.json"
    defs_dir: Path | None = None
    cleanup_dir: Path | None = None

    try:
        if bundled_def.exists():
            # Use bundled defs directory
            defs_dir = _DATA_DIR
        elif docker_version:
            # Extract from Docker
            defs_dir = extract_cura_docker_defs(docker_version)
            cleanup_dir = defs_dir
        else:
            raise EstampoError(
                f"CuraEngine definition '{def_id}' not found in bundled data. "
                "Set slicer.version to extract from the Docker image."
            )

        squashed = _squash_cura_def(def_id, defs_dir)

        # Write to profiles/cura/definitions/
        dest_dir = project_dir / profiles_dir / "cura" / "definitions"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{def_id}.def.json"

        with open(dest, "w") as fh:
            json.dump(squashed, fh, indent=4)
        log.info("Pinned CuraEngine definition %s → %s (squashed)", printer, dest)

        # Pin extruder definitions referenced by the machine def
        pinned = [dest]
        trains = squashed.get("metadata", {}).get("machine_extruder_trains", {})
        for extruder_id in trains.values():
            ext_filename = f"{extruder_id}.def.json"
            ext_src = defs_dir / ext_filename
            ext_dest = dest_dir / ext_filename
            if ext_src.exists() and not ext_dest.exists():
                shutil.copy2(ext_src, ext_dest)
                log.info("Pinned extruder definition → %s", ext_dest)
                pinned.append(ext_dest)

        # Write version marker
        if docker_version:
            marker = project_dir / profiles_dir / "cura" / ".slicer-version"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(docker_version + "\n")

        return pinned
    finally:
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def list_cura_machine_profiles(
    project_dir: Path | None = None, profiles_dir: str = "profiles"
) -> list[str]:
    """Return available CuraEngine machine profile names (without .json extension).

    Searches project profiles directory first, then bundled profiles.
    Names from both sources are merged and deduplicated.
    """
    names: dict[str, None] = {}
    # Project-local profiles take priority (listed first)
    if project_dir:
        local_dir = project_dir / profiles_dir / "cura" / "machine"
        if local_dir.is_dir():
            for p in sorted(local_dir.glob("*.json")):
                names[p.stem] = None
    # Bundled fallback
    if _BUNDLED_MACHINE_DIR.is_dir():
        for p in sorted(_BUNDLED_MACHINE_DIR.glob("*.json")):
            names[p.stem] = None
    return list(names)


def load_cura_machine_profile(
    name: str,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
) -> dict[str, object]:
    """Load a CuraEngine machine profile JSON by name.

    Searches project profiles directory first, then bundled profiles.
    Raises FileNotFoundError if not found.
    """
    candidates: list[Path] = []
    if project_dir:
        candidates.append(project_dir / profiles_dir / "cura" / "machine" / f"{name}.json")
    candidates.append(_BUNDLED_MACHINE_DIR / f"{name}.json")

    for path in candidates:
        if path.exists():
            log.debug("Loading CuraEngine machine profile from %s", path)
            return json.loads(path.read_text())

    searched = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        f"CuraEngine machine profile '{name}' not found.\n"
        f"Searched: {searched}\n"
        f"Add a JSON file to your project's {profiles_dir}/cura/machine/ directory."
    )


# Default print/bed temperatures by filament type string.
# Used to populate per-extruder profile settings when a filaments list is
# provided.  Values are (print_temp_°C, bed_temp_°C).
_FILAMENT_TEMPS: dict[str, tuple[int, int]] = {
    "PLA": (220, 55),
    "PLA-CF": (220, 55),
    "PETG": (240, 70),
    "PETG-CF": (260, 70),
    "ABS": (250, 100),
    "ASA": (255, 100),
    "TPU": (230, 30),
    "PA": (270, 80),
    "PA-CF": (280, 80),
    "PC": (270, 100),
}


@dataclass
class CuraProfile:
    """Slicer profile for CuraEngine.

    Machine geometry and start/end G-code come from the printer definition
    file (default: ultimaker2).  This profile controls process settings
    (layer height, speeds, temperatures, infill) passed as ``-s`` overrides.
    Nozzle and material dimensions can be overridden via a machine
    profile JSON (see ``load_cura_machine_profile``).
    """

    # Nozzle / material
    nozzle_diameter: float = 0.4
    material_diameter: float = 1.75
    material_print_temperature: int = 220
    material_bed_temperature: int = 55

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

    # Bed / filament
    bed_type: str = "Textured PEI Plate"
    filament_type: str = "PLA"

    # Additional -s overrides (Cura setting key names)
    overrides: dict[str, str] = field(default_factory=dict)

    # Per-extruder overrides (index 0 = extruder 0).  Each dict contains
    # CuraEngine setting key/value pairs that are appended after the global
    # settings in that extruder's ``-g -eN`` block.  If absent or shorter
    # than the extruder count, global settings apply for remaining extruders.
    per_extruder: list[dict[str, object]] = field(default_factory=list)


def _settings_dict(profile: CuraProfile) -> dict[str, object]:
    """Build the flat CuraEngine settings dict from a profile.

    Machine settings (bed size, heated bed, start/end gcode) are handled
    by the printer definition — only process/material settings here.
    """
    # CuraEngine computes infill_line_distance from infill_sparse_density
    # via a ``value`` expression in fdmprinter.def.json, but ``value``
    # overrides ``-s`` flags. Set infill_line_distance directly so our
    # density setting actually takes effect.
    infill_line_width = profile.nozzle_diameter  # default assumption
    density = profile.infill_sparse_density
    if density > 0:
        infill_line_distance = round(infill_line_width * 100 / density, 4)
    else:
        infill_line_distance = 0

    pairs: dict[str, object] = {
        "layer_height": profile.layer_height,
        "layer_height_0": profile.layer_height_0,
        "material_print_temperature": profile.material_print_temperature,
        "material_print_temperature_layer_0": profile.material_print_temperature,
        "material_bed_temperature": profile.material_bed_temperature,
        "material_bed_temperature_layer_0": profile.material_bed_temperature,
        "material_diameter": profile.material_diameter,
        "infill_sparse_density": density,
        "infill_line_distance": infill_line_distance,
        "wall_line_count": profile.wall_line_count,
        "top_layers": profile.top_layers,
        "bottom_layers": profile.bottom_layers,
        "speed_print": profile.speed_print,
        "speed_travel": profile.speed_travel,
        "speed_wall_0": profile.speed_wall_0,
        "speed_infill": profile.speed_infill,
        "material_print_temp_prepend": "false",
        "material_bed_temp_prepend": "false",
        "adhesion_type": "none",
        # CuraEngine 5.12 requires these explicitly (not resolved from def)
        "roofing_layer_count": 0,
        "flooring_layer_count": 0,
        "machine_nozzle_size": profile.nozzle_diameter,
        "machine_buildplate_type": profile.bed_type.lower().replace(" ", "_"),
        "material_type": profile.filament_type,
    }
    pairs.update(profile.overrides)
    return pairs


def _settings_flags(profile: CuraProfile) -> list[str]:
    """Build -s key=value flags from profile."""
    flags: list[str] = []
    for k, v in _settings_dict(profile).items():
        flags.extend(["-s", f"{k}={v}"])
    return flags


def _extruder_settings_list(profile: CuraProfile, ext_idx: int) -> list[str]:
    """Build ``-s key=value`` args list for one extruder's ``-g -eN`` block.

    Suitable for passing directly to ``subprocess.run`` (no shell quoting).
    """
    flags = _settings_flags(profile)
    if ext_idx < len(profile.per_extruder):
        for k, v in profile.per_extruder[ext_idx].items():
            flags.extend(["-s", f"{k}={v}"])
    return flags


def _extruder_settings_str(profile: CuraProfile, ext_idx: int) -> str:
    """Build the ``-s`` flags string for one extruder's ``-g -eN`` block.

    Starts from the global ``_settings_flags(profile)`` output and appends
    any per-extruder overrides from ``profile.per_extruder[ext_idx]``.
    If *ext_idx* is out of range the global settings are returned unchanged.
    """
    return " ".join(f'"{s}"' for s in _extruder_settings_list(profile, ext_idx))


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


def _place_on_bed(
    stl_path: Path,
    staging_dir: Path,
    bed_width: float = DEFAULT_PLATE_SIZE[0],
    bed_depth: float = DEFAULT_PLATE_SIZE[1],
) -> Path:
    """Copy STL into staging, ensuring the mesh sits on the bed (Z>=0)
    and is centered on the build plate.

    CuraEngine only slices geometry above Z=0.  With
    ``machine_center_is_zero = false`` (common default), the bed origin is at
    the corner, so the center of the bed is (width/2, depth/2).  This
    function:
    1. Shifts Z so the lowest vertex is at Z=0.
    2. Centers the mesh at (bed_width/2, bed_depth/2) so the print sits
       in the middle of the build plate.
    """
    import trimesh

    mesh: trimesh.Trimesh = trimesh.load(str(stl_path), force="mesh")  # type: ignore[assignment]

    # Center mesh on build plate (bed origin is at corner, not center)
    x_center = float((mesh.bounds[0][0] + mesh.bounds[1][0]) / 2)
    y_center = float((mesh.bounds[0][1] + mesh.bounds[1][1]) / 2)
    target_x = bed_width / 2
    target_y = bed_depth / 2
    dx = target_x - x_center
    dy = target_y - y_center
    if abs(dx) > 0.01 or abs(dy) > 0.01:
        mesh.vertices[:, 0] += dx  # type: ignore[attr-defined]
        mesh.vertices[:, 1] += dy  # type: ignore[attr-defined]
        log.info("Centered mesh on bed (shifted by %.2f, %.2f)", dx, dy)

    # Place on bed (Z >= 0)
    z_min = float(mesh.bounds[0][2])
    if z_min < 0:
        mesh.vertices[:, 2] -= z_min
        log.info("Shifted mesh up by %.2fmm to place on bed", -z_min)

    out = staging_dir / stl_path.name
    mesh.export(str(out), file_type="stl")
    return out


def _write_cura_settings(output_dir: Path, profile: CuraProfile) -> Path:
    """Write CuraEngine settings to JSON for downstream command stages.

    External tools (e.g. ``cura-p1s resolve``) use this file to resolve
    template variables in G-code produced by CuraEngine.
    """
    settings_path = output_dir / "cura_settings.json"
    settings_path.write_text(json.dumps(_settings_dict(profile), indent=2) + "\n")
    log.info("Wrote CuraEngine settings: %s", settings_path)
    return settings_path


def _prepare_cura_staging(
    printer: str | None,
    project_dir: Path | None,
    profiles_dir: str,
    output_dir: Path,
) -> tuple[Path, str]:
    """Set up the staging directory with printer definition files.

    Returns:
        ``(staging, machine_def)`` — the staging directory and the filename
        to pass to CuraEngine's ``-j`` flag.
    """
    staging = output_dir / ".cura-staging"
    staging.mkdir(exist_ok=True)

    # URL / file-path shortcut: copy the definition directly to staging.
    if printer:
        direct_def = _fetch_printer_def(printer, project_dir, staging)
        if direct_def:
            _copy_extruder_defs(staging / direct_def, staging, project_dir, profiles_dir)
            return staging, direct_def

    # Name / ID resolution: search pinned → estampo bundled → bambox package.
    def_id = _resolve_def_name(printer)
    def_chain = _resolve_def_chain(def_id, project_dir, profiles_dir)
    if def_chain:
        machine_def = def_chain[0].name
        for def_path in def_chain:
            shutil.copy2(def_path, staging / def_path.name)
        _copy_extruder_defs(def_chain[0], staging, project_dir, profiles_dir)
    else:
        machine_def = f"{def_id}.def.json"

    return staging, machine_def


def _check_local_def(staging: Path, machine_def: str, printer: str | None) -> None:
    """Raise if the machine definition is missing from staging (local mode only).

    Docker has built-in definitions, but local CuraEngine needs the file
    on disk.  Gives the user actionable guidance.
    """
    if (staging / machine_def).exists():
        return
    def_id = machine_def.removesuffix(".def.json")
    raise EstampoError(
        f"CuraEngine printer definition '{machine_def}' not found locally.\n"
        "\n"
        "This definition exists in the Docker image but is not bundled in\n"
        "the estampo pip package.  To fix this, either:\n"
        "\n"
        f"  1. Pin the definition:  estampo profiles pin\n"
        f"     (extracts '{def_id}' from the Docker image into profiles/)\n"
        "\n"
        "  2. Run via Docker (remove --local flag) — Docker has all\n"
        "     built-in CuraEngine definitions.\n"
        "\n"
        f"  3. Install the definition package:  pip install cura-p1s\n"
        f"     (if available for your printer)"
    )


def _strip_cura_banner(text: str) -> str:
    """Strip the CuraEngine GPL license banner from output text.

    CuraEngine prints a multi-line license notice to stderr on every run.
    It wastes space in error messages and pushes the actual diagnostic off
    screen.  Strip everything up to and including the blank line after the
    ``<http...>`` URL.
    """
    marker = "<http://www.gnu.org/licenses/>."
    idx = text.find(marker)
    if idx == -1:
        return text
    # Skip past the marker line and any trailing blank lines
    rest = text[idx + len(marker) :].lstrip("\n")
    return rest


def _run_docker_slice(
    inner_cmd: str,
    image: str,
    output_dir: Path,
    staging: Path,
    output_stem: str,
    profile: CuraProfile,
) -> Path:
    """Run CuraEngine via Docker, validate output, and post-process G-code.

    Cleans up *staging* regardless of success or failure.

    Returns:
        *output_dir* on success.
    """
    import os
    import sys

    cmd = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
    ]
    # Windows doesn't have getuid/getgid; Docker Desktop handles UID remapping there.
    if sys.platform != "win32":
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
    cmd += [
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

    shutil.rmtree(staging, ignore_errors=True)

    if result.returncode != 0:
        combined = (result.stdout + "\n" + result.stderr).strip()
        log.error("CuraEngine output:\n%s", combined)
        raise EstampoError(
            f"CuraEngine failed (exit {result.returncode}):\n{_strip_cura_banner(combined)[:500]}"
        )

    output_gcode = output_dir / f"{output_stem}.gcode"
    if not output_gcode.exists() or output_gcode.stat().st_size < 100:
        combined = (result.stdout + "\n" + result.stderr).strip()
        raise EstampoError(f"CuraEngine produced no output:\n{_strip_cura_banner(combined)[:500]}")

    _patch_gcode_header(output_gcode, result.stderr)
    _write_cura_settings(output_dir, profile)

    log.info("CuraEngine output: %s (%d bytes)", output_gcode, output_gcode.stat().st_size)
    return output_dir


def _run_local_slice(
    cura_args: list[str],
    output_dir: Path,
    staging: Path,
    output_stem: str,
    profile: CuraProfile,
) -> Path:
    """Run CuraEngine locally (without Docker), validate output, and post-process G-code.

    Cleans up *staging* regardless of success or failure.

    Returns:
        *output_dir* on success.
    """
    from estampo.slicer import find_slicer

    cura_bin = find_slicer("cura")
    cmd = [str(cura_bin), "slice"] + cura_args

    from estampo import ui

    log.info("Slicing locally (%s)", cura_bin)
    with ui.status("Slicing (CuraEngine)"):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    shutil.rmtree(staging, ignore_errors=True)

    if result.returncode != 0:
        combined = (result.stdout + "\n" + result.stderr).strip()
        log.error("CuraEngine output:\n%s", combined)
        raise EstampoError(
            f"CuraEngine failed (exit {result.returncode}):\n{_strip_cura_banner(combined)[:500]}"
        )

    output_gcode = output_dir / f"{output_stem}.gcode"
    if not output_gcode.exists() or output_gcode.stat().st_size < 100:
        combined = (result.stdout + "\n" + result.stderr).strip()
        raise EstampoError(f"CuraEngine produced no output:\n{_strip_cura_banner(combined)[:500]}")

    _patch_gcode_header(output_gcode, result.stderr)
    _write_cura_settings(output_dir, profile)

    log.info("CuraEngine output: %s (%d bytes)", output_gcode, output_gcode.stat().st_size)
    return output_dir


def slice_stl(
    stl_path: Path,
    output_dir: Path,
    profile: CuraProfile | None = None,
    image: str | None = None,
    printer: str | None = None,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
    local: bool = False,
) -> Path:
    """Slice a single STL file with CuraEngine and return the output directory.

    Uses Docker with the estampo/estampo:cura-X.Y.Z image.  The machine
    definition (resolved from *printer* name) provides machine geometry
    and start/end G-code; process settings come from the CuraProfile.

    Args:
        stl_path: Path to the input STL file.
        output_dir: Directory for output G-code.
        profile: Slicer profile. Defaults to P1S / PLA / 0.2mm.
        image: Docker image override. Defaults to estampo/estampo:cura-5.12.0.
        printer: Printer definition name (e.g. ``"Ultimaker 2"``).
        project_dir: Project root for pinned profile lookup.
        profiles_dir: Profiles directory name within the project.

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

    staging, machine_def = _prepare_cura_staging(printer, project_dir, profiles_dir, output_dir)

    # Get bed dimensions for mesh centering
    bed_w, bed_d = resolve_cura_bed_size(printer or "", project_dir, profiles_dir)

    # Place mesh on the build plate (Z>=0, centered) before slicing.
    staged_stl = _place_on_bed(stl_path, staging, bed_width=bed_w, bed_depth=bed_d)

    settings = _settings_flags(profile)

    if local:
        _check_local_def(staging, machine_def, printer)
        defs_path = _local_defs_path(staging)
        cura_args = [
            "-d",
            defs_path,
            "-j",
            str(staging / machine_def),
            "-o",
            str(output_dir / (stl_path.stem + ".gcode")),
            *settings,
            "-g",
            "-e0",
            *settings,
            "-l",
            str(staged_stl),
        ]
        return _run_local_slice(cura_args, output_dir, staging, stl_path.stem, profile)

    # Container paths (output_dir mounted at /work/output)
    c_staging = "/work/output/.cura-staging"
    c_stl = f"{c_staging}/{staged_stl.name}"
    c_output = "/work/output/" + stl_path.stem + ".gcode"

    # Build the CuraEngine command.
    # -d adds search paths for definition file resolution (inherits chain).
    # -j loads the machine definition (geometry + start/end gcode).
    # -g starts a mesh group, -e0 sets extruder 0 context for per-extruder
    # settings (material_diameter etc.) that CuraEngine requires.
    settings_str = " ".join(f'"{s}"' for s in settings)
    inner_cmd = (
        f"CuraEngine slice "
        f"-d {c_staging}:{_DEFS_DIR}:/opt/cura/extruders "
        f"-j {c_staging}/{machine_def} "
        f"-o {c_output} "
        f"{settings_str} "
        f"-g -e0 {settings_str} "
        f"-l {c_stl}"
    )

    return _run_docker_slice(inner_cmd, image, output_dir, staging, stl_path.stem, profile)


def slice_stl_multi(
    stl_meshes: list[tuple[int, Path]],
    output_dir: Path,
    profile: CuraProfile | None = None,
    image: str | None = None,
    printer: str | None = None,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
    local: bool = False,
) -> Path:
    """Slice multiple pre-positioned STL files with per-mesh extruder assignments.

    Each entry in *stl_meshes* is ``(extruder_idx, stl_path)`` where
    *extruder_idx* is 0-based.  The STLs must already be positioned correctly
    relative to each other and to the build plate (no centering is applied).

    CuraEngine receives one ``-g -eN -l mesh.stl`` group per entry, in order.
    Global settings from *profile* apply to all groups; ``profile.per_extruder``
    provides additional per-extruder overrides (filament type, temperatures).

    Returns:
        The output directory containing ``plate.gcode``.
    """
    if not stl_meshes:
        raise ValueError("stl_meshes must not be empty")
    if profile is None:
        profile = CuraProfile()
    if image is None:
        image = cura_docker_image()

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    staging, machine_def = _prepare_cura_staging(printer, project_dir, profiles_dir, output_dir)

    # Copy each STL into staging so it's accessible from one location.
    for _ext_idx, stl_path in stl_meshes:
        dest = staging / stl_path.name
        if not dest.exists():
            shutil.copy2(stl_path, dest)

    if local:
        _check_local_def(staging, machine_def, printer)
        cura_args: list[str] = [
            "-d",
            _local_defs_path(staging),
            "-j",
            str(staging / machine_def),
            "-o",
            str(output_dir / "plate.gcode"),
            *_settings_flags(profile),
        ]
        for ext_idx, stl_path in stl_meshes:
            cura_args.extend(["-g", f"-e{ext_idx}"])
            cura_args.extend(_extruder_settings_list(profile, ext_idx))
            cura_args.extend(["-l", str(staging / stl_path.name)])
        return _run_local_slice(cura_args, output_dir, staging, "plate", profile)

    c_staging = "/work/output/.cura-staging"
    c_output = "/work/output/plate.gcode"

    global_settings_str = " ".join(f'"{s}"' for s in _settings_flags(profile))

    mesh_groups = ""
    for ext_idx, stl_path in stl_meshes:
        c_stl = f"{c_staging}/{stl_path.name}"
        ext_str = _extruder_settings_str(profile, ext_idx)
        mesh_groups += f" -g -e{ext_idx} {ext_str} -l {c_stl}"

    inner_cmd = (
        f"CuraEngine slice "
        f"-d {c_staging}:{_DEFS_DIR}:/opt/cura/extruders "
        f"-j {c_staging}/{machine_def} "
        f"-o {c_output} "
        f"{global_settings_str}"
        f"{mesh_groups}"
    )

    return _run_docker_slice(inner_cmd, image, output_dir, staging, "plate", profile)


def _coerce(value: object, target_type: type) -> object:
    """Coerce *value* to *target_type*, stripping common unit suffixes first."""
    if isinstance(value, target_type):
        return value
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    return target_type(value)  # type: ignore[call-arg]


def cura_profile_from_config(
    overrides: dict[str, object] | None = None,
    bed_type: str | None = None,
    filament_type: str | None = None,
    filaments: list[str] | None = None,
    printer: str | None = None,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
) -> CuraProfile:
    """Build a CuraProfile from a machine profile JSON and config overrides.

    The machine profile JSON defines machine geometry and nozzle dimensions.
    Config overrides (process settings) are applied on top.

    If *filaments* is provided (a list of filament type strings, one per
    extruder slot), ``profile.per_extruder`` is populated with per-slot
    temperature and material_type overrides derived from ``_FILAMENT_TEMPS``.

    Maps estampo-style override keys (which may use OrcaSlicer names) to
    CuraEngine equivalents where possible.
    """
    profile = CuraProfile()

    # Load machine profile JSON if available (nozzle/material overrides).
    # Falls back to CuraProfile defaults when no machine profile exists —
    # the .def.json definition is sufficient for slicing.
    machine_name = printer or "Ultimaker 2"
    try:
        machine_data = load_cura_machine_profile(machine_name, project_dir, profiles_dir)
        for key, value in machine_data.items():
            if hasattr(profile, key):
                field_type = type(getattr(profile, key))
                value = _coerce(value, field_type)
                setattr(profile, key, value)
    except FileNotFoundError:
        log.debug("No machine profile for '%s', using defaults", machine_name)

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
                    field_type = type(getattr(profile, attr))
                    value = _coerce(value, field_type)
                    setattr(profile, attr, value)
            elif hasattr(profile, key):
                # Native CuraEngine key that matches a CuraProfile attribute
                setattr(profile, key, value)
            else:
                # Pass through as raw CuraEngine -s override
                cura_overrides[key] = str(value)

        if cura_overrides:
            profile.overrides = cura_overrides

    if filaments:
        per_ext: list[dict[str, object]] = []
        for ft in filaments:
            ext_overrides: dict[str, object] = {"material_type": ft}
            if ft in _FILAMENT_TEMPS:
                print_temp, bed_temp = _FILAMENT_TEMPS[ft]
                ext_overrides["material_print_temperature"] = print_temp
                ext_overrides["material_print_temperature_layer_0"] = print_temp
                ext_overrides["material_bed_temperature"] = bed_temp
                ext_overrides["material_bed_temperature_layer_0"] = bed_temp
            per_ext.append(ext_overrides)
        profile.per_extruder = per_ext

    return profile

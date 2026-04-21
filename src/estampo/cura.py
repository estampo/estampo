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
    1. Pinned (verbatim) in ``profiles/cura/definitions/``
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


def _resolve_def_chain_for_printer(
    printer_name: str,
    project_dir: Path | None,
    profiles_dir: str,
) -> list[Path]:
    """Resolve the definition chain for a printer name, path, or URL."""
    _is_url = printer_name and _printer_is_url(printer_name)
    _is_file = printer_name and _printer_is_file(printer_name, project_dir)
    if _is_url or _is_file:
        import tempfile
        import urllib.request

        if _printer_is_url(printer_name):
            with tempfile.NamedTemporaryFile(suffix=".def.json", delete=False) as tmp:
                urllib.request.urlretrieve(printer_name, tmp.name)  # noqa: S310
                tmp_path = Path(tmp.name)
            return [tmp_path]
        return [_printer_is_file(printer_name, project_dir)]  # type: ignore[list-item]

    def_id = _resolve_def_name(printer_name)
    return _resolve_def_chain(def_id, project_dir, profiles_dir)


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
    dims = resolve_cura_machine_dims(printer_name, project_dir, profiles_dir)
    return (dims["machine_width"], dims["machine_depth"])


def resolve_cura_machine_dims(
    printer_name: str,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
) -> dict[str, float]:
    """Return machine dimensions for a CuraEngine printer definition.

    Walks the definition chain to find machine_width, machine_depth, and
    machine_height.  Falls back to defaults if not found.

    *printer_name* may be a definition name/ID, a local file path, or a URL.
    """
    chain = _resolve_def_chain_for_printer(printer_name, project_dir, profiles_dir)

    found: dict[str, float] = {}
    dim_keys = ("machine_width", "machine_depth", "machine_height")
    for path in chain:
        try:
            with open(path) as f:
                data = json.load(f)
            overrides = data.get("overrides", {})
            for key in dim_keys:
                if key not in found:
                    entry = overrides.get(key, {})
                    if isinstance(entry, dict):
                        val = entry.get("value") or entry.get("default_value")
                        if val is not None:
                            found[key] = float(val)
            if len(found) == len(dim_keys):
                break
        except (json.JSONDecodeError, OSError):
            continue

    return {
        "machine_width": found.get("machine_width", DEFAULT_PLATE_SIZE[0]),
        "machine_depth": found.get("machine_depth", DEFAULT_PLATE_SIZE[1]),
        "machine_height": found.get("machine_height", 250.0),
    }


def resolve_cura_center_is_zero(
    printer_name: str,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
) -> bool:
    """Return True if the printer's build plate origin is at the bed center.

    Walks the definition chain for ``machine_center_is_zero``.  Falls back
    to CuraEngine's own default (``False`` — origin at front-left corner)
    when the setting is not declared in the chain.
    """
    chain = _resolve_def_chain_for_printer(printer_name, project_dir, profiles_dir)
    for path in chain:
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        entry = data.get("overrides", {}).get("machine_center_is_zero")
        if isinstance(entry, dict):
            val = entry.get("default_value")
            if val is None:
                val = entry.get("value")
            if val is not None:
                return bool(val)
    return False


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
# CuraEngine definition pinning
# ---------------------------------------------------------------------------


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


def _copy_cura_def_chain(def_id: str, defs_dirs: Path | list[Path]) -> list[Path]:
    """Walk the inheritance chain for a CuraEngine definition verbatim.

    Reads ``*.def.json`` files from *defs_dirs* (single dir or list of
    candidate dirs searched in order, first match wins), follows
    ``inherits`` links, and returns the chain as a list of source
    ``Path`` objects — leaf first, nearest non-root ancestor last.

    Root definitions (``fdmprinter``, ``fdmextruder``) are not included:
    estampo ships these in ``src/estampo/data/`` and CuraEngine resolves
    them at runtime via its ``-d`` search path.  Ancestors that are
    missing from *defs_dirs* are treated the same way (callers relying
    on Docker-extracted defs are responsible for pre-populating the
    search path).

    Raises :class:`EstampoError` if the leaf definition itself cannot be
    found — there is nothing to pin otherwise.
    """
    _ROOT_DEFS = {"fdmprinter", "fdmextruder"}

    dirs = [defs_dirs] if isinstance(defs_dirs, Path) else list(defs_dirs)

    def _find(name: str) -> Path | None:
        for d in dirs:
            candidate = d / f"{name}.def.json"
            if candidate.exists():
                return candidate
        return None

    chain: list[Path] = []
    current_id: str | None = def_id
    seen: set[str] = set()

    while current_id and current_id not in seen:
        seen.add(current_id)

        # Stop before root definitions — estampo ships these separately
        if current_id in _ROOT_DEFS and current_id != def_id:
            break

        path = _find(current_id)
        if path is None:
            # Ancestor unavailable locally — CuraEngine resolves at runtime
            break
        chain.append(path)

        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            break
        parent = data.get("inherits")
        current_id = parent if isinstance(parent, str) else None

    if not chain:
        searched = ", ".join(str(d) for d in dirs)
        raise EstampoError(f"CuraEngine definition '{def_id}' not found in {searched}")

    return chain


def pin_cura_definitions(
    printer: str | None,
    project_dir: Path,
    docker_version: str | None = None,
    profiles_dir: str = "profiles",
) -> list[Path]:
    """Pin a CuraEngine printer definition for reproducible builds.

    Walks the inheritance chain (extracting from the Docker image if
    needed) and copies each ancestor ``.def.json`` file verbatim into
    ``profiles/cura/definitions/``.  CuraEngine resolves inheritance at
    slice time; the root defs (``fdmprinter``, ``fdmextruder``) ship
    with estampo in ``src/estampo/data/`` and are not copied per printer.

    Returns list of pinned file paths.
    """
    if not printer:
        log.info("No CuraEngine printer specified — nothing to pin.")
        return []

    # If the printer is a local file path that already exists, it was placed
    # there by 'profiles add' — treat it as already pinned, nothing to do.
    existing = _printer_is_file(printer, project_dir)
    if existing:
        log.info("Printer definition is a local file — already pinned: %s", existing)
        return [existing]

    def_id = _resolve_def_name(printer)

    # Build an ordered list of candidate directories to resolve the def chain.
    # Project profiles dir first (user-added via 'profiles add'), then bundled
    # data, then Docker-extracted defs.  Docker extraction is skipped when the
    # full chain already resolves from project or bundled sources.
    project_defs_dir = project_dir / profiles_dir / "cura" / "definitions"
    search_dirs: list[Path] = []
    if project_defs_dir.is_dir():
        search_dirs.append(project_defs_dir)
    if _DATA_DIR.is_dir():
        search_dirs.append(_DATA_DIR)

    cleanup_dir: Path | None = None

    def _needs_docker() -> bool:
        """True if the leaf or any non-root ancestor is missing from search_dirs."""
        _ROOT = {"fdmprinter", "fdmextruder"}
        current: str | None = def_id
        seen: set[str] = set()
        while current and current not in seen and current not in _ROOT:
            seen.add(current)
            path = next(
                (
                    d / f"{current}.def.json"
                    for d in search_dirs
                    if (d / f"{current}.def.json").exists()
                ),
                None,
            )
            if path is None:
                return True
            with open(path) as f:
                data = json.load(f)
            parent = data.get("inherits")
            current = parent if isinstance(parent, str) else None
        return False

    try:
        if _needs_docker():
            if not docker_version:
                raise EstampoError(
                    f"CuraEngine definition '{def_id}' (or an ancestor) not found "
                    f"in project profiles or bundled data. Set slicer.version to "
                    f"extract from the Docker image."
                )
            docker_defs_dir = extract_cura_docker_defs(docker_version)
            cleanup_dir = docker_defs_dir
            search_dirs.append(docker_defs_dir)

        chain = _copy_cura_def_chain(def_id, search_dirs)

        # Copy each def file verbatim into profiles/cura/definitions/
        dest_dir = project_defs_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        pinned: list[Path] = []
        for src in chain:
            dest = dest_dir / src.name
            if src.resolve() == dest.resolve():
                # Already pinned (source is the destination) — keep in list
                pinned.append(dest)
                continue
            shutil.copy2(src, dest)
            pinned.append(dest)
            log.info("Pinned CuraEngine definition → %s (verbatim)", dest)

        # Pin extruder definitions referenced by the leaf machine def
        leaf_path = chain[0]
        try:
            with open(leaf_path) as fh:
                leaf_data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            leaf_data = {}
        trains = leaf_data.get("metadata", {}).get("machine_extruder_trains", {})
        for extruder_id in trains.values():
            ext_filename = f"{extruder_id}.def.json"
            ext_dest = dest_dir / ext_filename
            if ext_dest.exists():
                if ext_dest not in pinned:
                    pinned.append(ext_dest)
                continue
            for d in search_dirs:
                ext_src = d / ext_filename
                if ext_src.exists():
                    shutil.copy2(ext_src, ext_dest)
                    log.info("Pinned extruder definition → %s", ext_dest)
                    pinned.append(ext_dest)
                    break

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


CuraOverrides = dict[str, str | int | float | bool]
"""CuraEngine setting overrides: raw engine-native key/value pairs.

TOML ``[slicer.cura.overrides]`` is parsed as this dict verbatim — no key
translation, no type coercion.  Values are emitted as ``-s key=value`` to
CuraEngine, which resolves remaining settings from the pinned def chain.
"""

CuraPerExtruder = list[dict[str, str | int | float | bool]]
"""Per-extruder override lists, one dict per extruder slot (0-indexed)."""


def _settings_dict(overrides: CuraOverrides) -> dict[str, object]:
    """Build the flat CuraEngine settings dict from raw TOML overrides.

    User overrides pass through verbatim.  A minimal baseline of
    CuraEngine 5.12 quirks (roofing/flooring layer counts, prepend flags)
    is applied first; all other defaults come from the pinned def chain.
    """
    pairs: dict[str, object] = {
        "material_print_temp_prepend": "false",
        "material_bed_temp_prepend": "false",
        # CuraEngine 5.12 requires these explicitly (not resolved from def)
        "roofing_layer_count": 0,
        "flooring_layer_count": 0,
    }
    pairs.update(overrides)
    return pairs


def _settings_flags(overrides: CuraOverrides) -> list[str]:
    """Build -s key=value flags from raw overrides."""
    flags: list[str] = []
    for k, v in _settings_dict(overrides).items():
        flags.extend(["-s", f"{k}={v}"])
    return flags


def _machine_dims_flags(machine_dims: dict[str, float]) -> list[str]:
    """Build -s flags for machine bed dimensions.

    Pinned definitions commonly declare bed size with ``value`` only and
    no ``default_value``.  CuraEngine logs "has no [default_]value!" for
    these fields and silently falls back to the fdmprinter defaults
    (100×100).  Slicer-side mesh placement reads the ``value`` directly,
    so the mesh gets centred for the real bed and ends up off the bed
    CuraEngine thinks it has — which silently drops brim/skirt (see #586).

    Passing the dims as ``-s`` flags keeps CuraEngine in sync with mesh
    placement regardless of how the def declares them.
    """
    flags: list[str] = []
    for key in ("machine_width", "machine_depth", "machine_height"):
        if key in machine_dims:
            flags.extend(["-s", f"{key}={machine_dims[key]}"])
    return flags


def _extruder_settings_list(
    overrides: CuraOverrides,
    per_extruder: CuraPerExtruder,
    ext_idx: int,
) -> list[str]:
    """Build ``-s key=value`` args list for one extruder's ``-g -eN`` block.

    Suitable for passing directly to ``subprocess.run`` (no shell quoting).
    """
    flags = _settings_flags(overrides)
    if ext_idx < len(per_extruder):
        for k, v in per_extruder[ext_idx].items():
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


def _write_cura_settings(
    output_dir: Path,
    overrides: CuraOverrides,
    machine_dims: dict[str, float] | None = None,
    per_extruder: CuraPerExtruder | None = None,
) -> Path:
    """Write CuraEngine settings to JSON for downstream command stages.

    External tools (e.g. ``cura-p1s resolve``) use this file to resolve
    template variables in G-code produced by CuraEngine.

    *machine_dims* adds machine geometry (width, depth, height) so that
    template variables like ``{machine_height}`` can be resolved.

    *per_extruder* — extruder-0 values are merged in so that start-gcode
    template variables like ``{material_bed_temperature_layer_0}`` and
    ``{material_print_temperature_layer_0}`` resolve to the first
    extruder's filament values (start gcode runs before any tool change).
    """
    settings = _settings_dict(overrides)
    if machine_dims:
        settings.update(machine_dims)
    if per_extruder:
        settings.update(per_extruder[0])
    settings_path = output_dir / "cura_settings.json"
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
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


_CURA_WARNING_RE = re.compile(r"\[WARNING\]\s+(.*?)\s*$", re.IGNORECASE)
_CURA_NO_DEFAULT_VALUE_RE = re.compile(r"JSON setting '([^']+)' has no \[default_\]value!")


def _surface_cura_warnings(stderr: str) -> None:
    """Surface CuraEngine stderr warnings after a zero-exit run.

    CuraEngine writes warnings to stderr for silently-dropped settings,
    unknown keys, and other miscompilation risks even when the slice
    succeeds.  Without surfacing, bugs like #586/#587 stay invisible.

    Any ``JSON setting 'X' has no [default_]value!`` lines are logged at
    WARNING with the list of affected keys — these signal printer-profile
    overrides reverting to fdmprinter defaults.  A total count of all
    warnings is also logged so users know something happened, and each
    raw warning is logged at DEBUG so ``-v`` surfaces them inline.
    """
    warnings: list[str] = []
    dropped: list[str] = []
    for line in stderr.splitlines():
        m = _CURA_WARNING_RE.search(line)
        if not m:
            continue
        msg = m.group(1).strip()
        warnings.append(msg)
        dv = _CURA_NO_DEFAULT_VALUE_RE.search(msg)
        if dv:
            dropped.append(dv.group(1))

    if not warnings:
        return

    if dropped:
        unique = sorted(set(dropped))
        log.warning(
            "CuraEngine silently dropped %d printer-profile setting(s), "
            "reverting to fdmprinter defaults: %s "
            "(pinned definition is missing 'default_value' entries — see #587).",
            len(unique),
            ", ".join(unique),
        )

    log.warning(
        "CuraEngine emitted %d warning(s) — run with -v to see them.",
        len(warnings),
    )

    for msg in warnings:
        log.debug("CuraEngine: %s", msg)


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
    cura_args: list[str],
    image: str,
    output_dir: Path,
    staging: Path,
    output_stem: str,
    overrides: CuraOverrides,
    machine_dims: dict[str, float] | None = None,
    per_extruder: CuraPerExtruder | None = None,
) -> Path:
    """Run CuraEngine via Docker, validate output, and post-process G-code.

    Cleans up *staging* regardless of success or failure.

    Returns:
        *output_dir* on success.
    """
    import os
    import sys

    # argv-only invocation: each flag/value is a separate argument, so shell
    # metacharacters in TOML override values and mesh filenames are inert.
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
        "CuraEngine",
        image,
        "slice",
        *cura_args,
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

    _surface_cura_warnings(result.stderr)
    _patch_gcode_header(output_gcode, result.stderr)
    _write_cura_settings(output_dir, overrides, machine_dims, per_extruder)

    log.info("CuraEngine output: %s (%d bytes)", output_gcode, output_gcode.stat().st_size)
    return output_dir


def _run_local_slice(
    cura_args: list[str],
    output_dir: Path,
    staging: Path,
    output_stem: str,
    overrides: CuraOverrides,
    machine_dims: dict[str, float] | None = None,
    per_extruder: CuraPerExtruder | None = None,
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

    _surface_cura_warnings(result.stderr)
    _patch_gcode_header(output_gcode, result.stderr)
    _write_cura_settings(output_dir, overrides, machine_dims, per_extruder)

    log.info("CuraEngine output: %s (%d bytes)", output_gcode, output_gcode.stat().st_size)
    return output_dir


def slice_stl_multi(
    stl_meshes: list[tuple[int, Path]],
    output_dir: Path,
    overrides: CuraOverrides | None = None,
    per_extruder: CuraPerExtruder | None = None,
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
    Global *overrides* apply to all groups; *per_extruder* provides additional
    per-slot overrides (filament type, temperatures).

    Returns:
        The output directory containing ``plate.gcode``.
    """
    if not stl_meshes:
        raise ValueError("stl_meshes must not be empty")
    if overrides is None:
        overrides = {}
    if per_extruder is None:
        per_extruder = []
    if image is None:
        image = cura_docker_image()

    _warn_unknown_cura_settings(overrides, per_extruder)

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    staging, machine_def = _prepare_cura_staging(printer, project_dir, profiles_dir, output_dir)

    # Get machine dimensions for settings JSON
    machine_dims = resolve_cura_machine_dims(printer or "", project_dir, profiles_dir)

    # Copy each STL into staging so it's accessible from one location.
    for _ext_idx, stl_path in stl_meshes:
        dest = staging / stl_path.name
        if not dest.exists():
            shutil.copy2(stl_path, dest)

    global_flags = _settings_flags(overrides) + _machine_dims_flags(machine_dims)

    if local:
        _check_local_def(staging, machine_def, printer)
        cura_args: list[str] = [
            "-d",
            _local_defs_path(staging),
            "-j",
            str(staging / machine_def),
            "-o",
            str(output_dir / "plate.gcode"),
            *global_flags,
        ]
        for ext_idx, stl_path in stl_meshes:
            cura_args.extend(["-g", f"-e{ext_idx}"])
            cura_args.extend(_extruder_settings_list(overrides, per_extruder, ext_idx))
            cura_args.extend(["-l", str(staging / stl_path.name)])
        return _run_local_slice(
            cura_args, output_dir, staging, "plate", overrides, machine_dims, per_extruder
        )

    c_staging = "/work/output/.cura-staging"
    c_output = "/work/output/plate.gcode"

    cura_args = [
        "-d",
        f"{c_staging}:{_DEFS_DIR}:/opt/cura/extruders",
        "-j",
        f"{c_staging}/{machine_def}",
        "-o",
        c_output,
        *global_flags,
    ]
    for ext_idx, stl_path in stl_meshes:
        cura_args.extend(["-g", f"-e{ext_idx}"])
        cura_args.extend(_extruder_settings_list(overrides, per_extruder, ext_idx))
        cura_args.extend(["-l", f"{c_staging}/{stl_path.name}"])

    return _run_docker_slice(
        cura_args, image, output_dir, staging, "plate", overrides, machine_dims, per_extruder
    )


def build_cura_config(
    overrides: dict[str, object] | None = None,
    bed_type: str | None = None,
    filament_type: str | None = None,
    filaments: list[str] | None = None,
    printer: str | None = None,
    project_dir: Path | None = None,
    profiles_dir: str = "profiles",
) -> tuple[CuraOverrides, CuraPerExtruder]:
    """Build ``(overrides, per_extruder)`` for a CuraEngine slice.

    TOML ``[slicer.cura.overrides]`` is passed through verbatim — no key
    translation, no type coercion.  Any machine profile JSON
    (``load_cura_machine_profile``) is merged first so TOML overrides win.
    *bed_type* and *filament_type* seed ``machine_buildplate_type`` and
    ``material_type`` if the user did not set them.  *filaments* populates
    ``per_extruder`` with material_type and temperature hints per slot.

    The *overrides* parameter is typed as ``dict[str, object]`` because TOML
    parsing yields mixed types; non-scalar values are skipped.
    """
    result: CuraOverrides = {}

    machine_name = printer or "Ultimaker 2"
    try:
        machine_data = load_cura_machine_profile(machine_name, project_dir, profiles_dir)
        for key, value in machine_data.items():
            if isinstance(value, (str, int, float, bool)):
                result[key] = value
    except FileNotFoundError:
        log.debug("No machine profile for '%s', using def-chain defaults", machine_name)

    if bed_type and "machine_buildplate_type" not in result:
        result["machine_buildplate_type"] = bed_type.lower().replace(" ", "_")

    if filament_type and "material_type" not in result:
        result["material_type"] = filament_type

    if overrides:
        for key, value in overrides.items():
            if isinstance(value, (str, int, float, bool)):
                result[key] = value

    per_ext: CuraPerExtruder = []
    if filaments:
        for ft in filaments:
            ext_overrides: dict[str, str | int | float | bool] = {"material_type": ft}
            if ft in _FILAMENT_TEMPS:
                print_temp, bed_temp = _FILAMENT_TEMPS[ft]
                ext_overrides["material_print_temperature"] = print_temp
                ext_overrides["material_print_temperature_layer_0"] = print_temp
                ext_overrides["material_bed_temperature"] = bed_temp
                ext_overrides["material_bed_temperature_layer_0"] = bed_temp
            per_ext.append(ext_overrides)

    return result, per_ext


def validate_cura_settings(overrides: CuraOverrides) -> list[str]:
    """Return warnings for unknown CuraEngine override keys.

    Delegates to :func:`estampo.profiles.validate_override_keys`, which
    validates against the bundled ``cura-settings.json`` schema (derived
    from ``fdmprinter.def.json``) and surfaces "did you mean" hints for
    typos and cross-engine key use (e.g. OrcaSlicer's ``wall_loops``).
    """
    if not overrides:
        return []
    from estampo.profiles import validate_override_keys

    return validate_override_keys(
        dict(overrides),
        engine="cura",
        process=None,
        project_dir=None,
    )


def _warn_unknown_cura_settings(
    overrides: CuraOverrides,
    per_extruder: CuraPerExtruder,
) -> None:
    """Log warnings for unknown CuraEngine keys in *overrides* / *per_extruder*."""
    combined: CuraOverrides = dict(overrides)
    for ext in per_extruder:
        combined.update(ext)
    for warning in validate_cura_settings(combined):
        log.warning("%s", warning)

#!/usr/bin/env python3
"""Extract slicer profile names from estampo Docker images.

Supports both OrcaSlicer and CuraEngine profile extraction.

Usage:
    python scripts/extract_profiles.py 2.3.1
    python scripts/extract_profiles.py 2.3.1 --image estampo/estampo:orca-2.3.1
    python scripts/extract_profiles.py 2.3.1 2.2.0   # multiple versions
    python scripts/extract_profiles.py --engine cura 5.12.0
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent / "src" / "estampo" / "data"

# ---------------------------------------------------------------------------
# OrcaSlicer extraction
# ---------------------------------------------------------------------------

ORCA_PROFILE_ROOT = "/opt/orca-slicer/resources/profiles/BBL"
ORCA_CATEGORIES = ("machine", "process", "filament")


def extract_orca(version: str, image: str) -> dict:
    """Pull profile names and compat metadata from the Docker image.

    Machine entries are plain strings. Process and filament entries are
    ``{"name": ..., "compatible_printers": [...], ...}`` dicts so callers
    can filter by printer without re-reading the slicer profile files.
    """
    from estampo.orca import _resolve_profile_data_from_dir

    print(f"Extracting OrcaSlicer profiles from {image} ...", flush=True)

    container_id = None
    tmp_dir = Path(tempfile.mkdtemp(prefix="orca_profiles_"))
    try:
        result = subprocess.run(
            ["docker", "create", "--platform", "linux/amd64", image, "true"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"  error creating container: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        container_id = result.stdout.strip()

        cp_result = subprocess.run(
            ["docker", "cp", f"{container_id}:{ORCA_PROFILE_ROOT}/.", str(tmp_dir)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if cp_result.returncode != 0:
            print(f"  error copying profiles: {cp_result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
    finally:
        if container_id:
            subprocess.run(
                ["docker", "rm", "-f", container_id],
                capture_output=True,
                timeout=15,
            )

    try:
        profiles: dict[str, list] = {cat: [] for cat in ORCA_CATEGORIES}

        for category in ORCA_CATEGORIES:
            cat_dir = tmp_dir / category
            if not cat_dir.is_dir():
                continue
            for f in sorted(cat_dir.glob("*.json")):
                name = f.stem
                if "template" in name.lower() or name.startswith("fdm_"):
                    continue
                if category == "machine":
                    profiles[category].append(name)
                    continue

                # process / filament: resolve inheritance to capture the
                # effective compatible_printers list (leaf profiles often
                # leave it to the base).
                try:
                    data = _resolve_profile_data_from_dir(name, category, tmp_dir)
                except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
                    print(f"  skip {category}/{name}: {e}", file=sys.stderr)
                    continue
                if data.get("type") != category:
                    continue
                entry: dict = {"name": name}
                compat = data.get("compatible_printers")
                if isinstance(compat, list):
                    entry["compatible_printers"] = [str(p) for p in compat]
                condition = data.get("compatible_printers_condition")
                if isinstance(condition, str) and condition:
                    entry["compatible_printers_condition"] = condition
                profiles[category].append(entry)

        profiles["machine"] = sorted(profiles["machine"])
        for cat in ("process", "filament"):
            profiles[cat].sort(key=lambda e: e["name"])
        for cat in ORCA_CATEGORIES:
            print(f"  {cat}: {len(profiles[cat])} profiles")
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"engine": "orca", "version": version, **profiles}


# ---------------------------------------------------------------------------
# CuraEngine extraction
# ---------------------------------------------------------------------------

CURA_DEFS_DIR = "/opt/cura/definitions"
BUNDLED_DATA_DIR = Path(__file__).parent.parent / "src" / "estampo" / "data"


def extract_cura(version: str, image: str) -> dict:
    """Pull printer definition names from the CuraEngine Docker image.

    Extracts all visible ``.def.json`` files from the Docker image and merges
    in estampo's custom Bambu Lab definitions (which are not in the upstream
    Cura AppImage).
    """
    print(f"Extracting CuraEngine definitions from {image} ...", flush=True)

    # Create a stopped container and copy definitions out
    container_id = None
    tmp_dir = Path(tempfile.mkdtemp(prefix="cura_defs_"))
    try:
        result = subprocess.run(
            ["docker", "create", "--platform", "linux/amd64", image, "true"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"  error creating container: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        container_id = result.stdout.strip()

        cp_result = subprocess.run(
            ["docker", "cp", f"{container_id}:{CURA_DEFS_DIR}/.", str(tmp_dir)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if cp_result.returncode != 0:
            print(f"  error copying defs: {cp_result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
    finally:
        if container_id:
            subprocess.run(
                ["docker", "rm", "-f", container_id],
                capture_output=True,
                timeout=15,
            )

    # Read Docker definitions
    definitions = _read_visible_defs(tmp_dir)

    # Merge in estampo's custom Bambu Lab definitions
    bundled_defs = _read_visible_defs(BUNDLED_DATA_DIR)
    for def_entry in bundled_defs:
        # Add if not already present (by id)
        existing_ids = {d["id"] for d in definitions}
        if def_entry["id"] not in existing_ids:
            definitions.append(def_entry)

    definitions.sort(key=lambda d: d["name"])
    print(f"  machine: {len(definitions)} printer definitions")

    # Clean up
    import shutil

    shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "engine": "cura",
        "version": version,
        "machine": definitions,
        "process": [],
        "filament": [],
    }


def _read_visible_defs(defs_dir: Path) -> list[dict[str, str]]:
    """Read visible printer definitions from a directory of .def.json files."""
    definitions: list[dict[str, str]] = []
    for f in sorted(defs_dir.glob("*.def.json")):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        # Skip non-printer definitions and invisible base definitions
        metadata = data.get("metadata", {})
        if metadata.get("visible") is False:
            continue
        # Skip fdmprinter/fdmextruder (root definitions, not real printers)
        name = data.get("name", f.stem)
        if name in ("FDM Printer Base Description", "FDM Extruder Base Description"):
            continue
        # Skip extruder definitions
        if "extruder" in f.stem and "machine" not in f.stem:
            continue

        def_id = f.stem
        if def_id.endswith(".def"):
            def_id = def_id[:-4]

        definitions.append({"name": name, "id": def_id})

    return definitions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("versions", nargs="+", help="Slicer version(s) to extract")
    parser.add_argument(
        "--engine",
        choices=["orca", "cura"],
        default="orca",
        help="Slicer engine (default: orca)",
    )
    parser.add_argument(
        "--image",
        help="Docker image to use (overrides default). Only valid when a single version is given.",
    )
    args = parser.parse_args()

    if args.image and len(args.versions) > 1:
        parser.error("--image can only be used with a single version")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for version in args.versions:
        if args.engine == "orca":
            from estampo.slicer import docker_image

            image = args.image or docker_image(version)
            data = extract_orca(version, image)
        else:
            from estampo.cura import cura_docker_image

            image = args.image or cura_docker_image(version)
            data = extract_cura(version, image)

        out = OUT_DIR / f"profiles.{args.engine}.{version}.json"
        out.write_text(json.dumps(data, indent=2) + "\n")
        print(f"  Written to {out}\n")


if __name__ == "__main__":
    main()

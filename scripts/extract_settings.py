#!/usr/bin/env python3
"""Extract full slicer settings references from estampo Docker images.

Generates JSON reference files listing every available setting for each
slicer engine, with descriptions, types, defaults, and example values.
These files help AI assistants and humans map 3D printing concepts to
the correct estampo.toml override keys.

Usage:
    python scripts/extract_settings.py
    python scripts/extract_settings.py --orca-version 2.3.1 --cura-version 5.12.0
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
import tempfile
from pathlib import Path

DOCS_DIR = Path(__file__).parent.parent / "docs"

# ---------------------------------------------------------------------------
# CuraEngine extraction
# ---------------------------------------------------------------------------

CURA_DEF_PATH = "/opt/cura/definitions/fdmprinter.def.json"


def _extract_cura_settings(node: dict, category: str = "") -> list[dict]:
    """Recursively extract settings from nested CuraEngine definition."""
    results: list[dict] = []
    for key, val in node.items():
        if not isinstance(val, dict):
            continue
        cat = category
        if val.get("type") == "category":
            cat = val.get("label", key)
        if "type" in val and val["type"] != "category":
            entry: dict = {
                "key": key,
                "label": val.get("label", key),
                "description": val.get("description", "").strip(),
                "type": val["type"],
                "category": cat,
            }
            if "default_value" in val:
                dv = val["default_value"]
                if isinstance(dv, str) and len(dv) > 200:
                    dv = "(gcode template)"
                entry["default"] = dv
            if "unit" in val:
                entry["unit"] = val["unit"]
            if "options" in val:
                entry["options"] = val["options"]
            if "minimum_value" in val:
                entry["min"] = val["minimum_value"]
            if "maximum_value" in val:
                entry["max"] = val["maximum_value"]
            results.append(entry)
        if "children" in val:
            results.extend(_extract_cura_settings(val["children"], cat))
    return results


def extract_cura(version: str, image: str | None = None) -> Path:
    """Extract CuraEngine settings from Docker image."""
    if image is None:
        image = f"ghcr.io/estampo/estampo:cura-{version}"

    print(f"Extracting CuraEngine settings from {image}...")
    cid = subprocess.check_output(
        ["docker", "create", "--name", "cura-settings-extract", image, "true"],
        text=True,
    ).strip()
    try:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name
        subprocess.check_call(
            ["docker", "cp", f"{cid}:{CURA_DEF_PATH}", tmp_path]
        )
    finally:
        subprocess.check_call(["docker", "rm", cid], stdout=subprocess.DEVNULL)

    with open(tmp_path) as f:
        data = json.load(f)

    all_settings = _extract_cura_settings(data.get("settings", {}))

    output = {
        "engine": "cura",
        "version": version,
        "source": "fdmprinter.def.json (base definition for all CuraEngine printers)",
        "note": (
            "These are the settings available in [slicer.cura.overrides]. "
            "Use the 'key' field as the override key."
        ),
        "settings_count": len(all_settings),
        "settings": all_settings,
    }

    out_path = DOCS_DIR / "cura-settings.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"  Wrote {len(all_settings)} settings to {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# OrcaSlicer extraction
# ---------------------------------------------------------------------------

ORCA_PROFILE_ROOT = "/opt/orca-slicer/resources/profiles/BBL"
SKIP_KEYS = {
    "type", "name", "from", "inherits", "instantiation",
    "is_custom_defined", "version", "setting_id",
}


def _extract_orca_category(base_dir: str, category: str) -> list[dict]:
    """Extract unique settings from all profiles in a category."""
    files = glob.glob(f"{base_dir}/{category}/*.json")
    all_keys: dict[str, dict] = {}

    for pf in files:
        try:
            with open(pf) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        for key, val in data.items():
            if key in SKIP_KEYS:
                continue
            if key not in all_keys:
                all_keys[key] = {
                    "key": key,
                    "category": category,
                    "example_values": [],
                    "profiles_count": 0,
                }
            all_keys[key]["profiles_count"] += 1
            examples = all_keys[key]["example_values"]
            if isinstance(val, str) and len(val) > 200:
                continue
            str_val = str(val) if not isinstance(val, (list, dict)) else json.dumps(val)
            if str_val not in [str(e) for e in examples] and len(examples) < 3:
                examples.append(val)

    return list(all_keys.values())


def extract_orca(version: str, image: str | None = None) -> Path:
    """Extract OrcaSlicer settings from Docker image."""
    if image is None:
        image = f"ghcr.io/estampo/estampo:orca-{version}"

    print(f"Extracting OrcaSlicer settings from {image}...")
    cid = subprocess.check_output(
        ["docker", "create", "--name", "orca-settings-extract", image, "true"],
        text=True,
    ).strip()
    try:
        tmp_dir = tempfile.mkdtemp()
        subprocess.check_call(
            ["docker", "cp", f"{cid}:{ORCA_PROFILE_ROOT}", tmp_dir]
        )
    finally:
        subprocess.check_call(["docker", "rm", cid], stdout=subprocess.DEVNULL)

    base = f"{tmp_dir}/BBL"
    process = _extract_orca_category(base, "process")
    machine = _extract_orca_category(base, "machine")
    filament = _extract_orca_category(base, "filament")
    all_settings = process + machine + filament

    output = {
        "engine": "orca",
        "version": version,
        "source": "OrcaSlicer BBL profiles extracted from Docker image",
        "note": (
            "Process settings go in [slicer.orca.overrides], "
            "machine settings in [slicer.orca.machine_overrides], "
            "filament settings in [slicer.orca.filament_overrides]. "
            "Use the 'key' field as the override key."
        ),
        "settings_count": len(all_settings),
        "process_count": len(process),
        "machine_count": len(machine),
        "filament_count": len(filament),
        "settings": all_settings,
    }

    out_path = DOCS_DIR / "orca-settings.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"  Wrote {len(all_settings)} settings to {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract slicer settings references from Docker images"
    )
    parser.add_argument("--orca-version", default="2.3.1")
    parser.add_argument("--cura-version", default="5.12.0")
    parser.add_argument("--orca-image", default=None)
    parser.add_argument("--cura-image", default=None)
    parser.add_argument(
        "--engine",
        choices=["orca", "cura", "both"],
        default="both",
        help="Which engine(s) to extract",
    )
    args = parser.parse_args()

    if args.engine in ("orca", "both"):
        extract_orca(args.orca_version, args.orca_image)
    if args.engine in ("cura", "both"):
        extract_cura(args.cura_version, args.cura_image)

    print("Done.")


if __name__ == "__main__":
    main()

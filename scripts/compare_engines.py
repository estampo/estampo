#!/usr/bin/env python3
"""Compare OrcaSlicer vs CuraEngine G-code for a P1S slice.

Slices a test STL with both engines using matched settings, then compares
the resulting G-code: filament usage, print time, layer count, temperatures,
and G-code structure.

Requires Docker (both engine images must be available).

Usage:
    python scripts/compare_engines.py [STL_FILE]

If no STL is given, uses the bundled 10mm test cube.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure project root is on sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from estampo.cura import CuraProfile, cura_docker_image, slice_stl
from estampo.gcode import analyze_gcode, parse_gcode_metadata
from estampo.slicer import slice_plate

# ---------------------------------------------------------------------------
# Shared slice settings (matched across engines as closely as possible)
# ---------------------------------------------------------------------------

ORCA_VERSION = "2.3.2"
CURA_VERSION = "5.12.0"

OVERRIDES = {
    "layer_height": 0.20,
    "wall_loops": 3,
    "sparse_infill_density": "25%",
    "top_shell_layers": 5,
    "bottom_shell_layers": 4,
}


def _find_gcode(output_dir: Path) -> Path | None:
    """Find the first .gcode file in an output directory."""
    for f in output_dir.rglob("*.gcode"):
        if f.stat().st_size > 100:
            return f
    return None


def _gcode_temps(gcode_path: Path) -> dict[str, set[int]]:
    """Extract temperature commands from G-code."""
    text = gcode_path.read_text()
    temps: dict[str, set[int]] = {"nozzle": set(), "bed": set()}
    for line in text.splitlines():
        if m := re.match(r"M104\s+S(\d+)", line):
            temps["nozzle"].add(int(m.group(1)))
        elif m := re.match(r"M109\s+S(\d+)", line):
            temps["nozzle"].add(int(m.group(1)))
        elif m := re.match(r"M140\s+S(\d+)", line):
            temps["bed"].add(int(m.group(1)))
        elif m := re.match(r"M190\s+S(\d+)", line):
            temps["bed"].add(int(m.group(1)))
    # Remove 0 (off commands)
    temps["nozzle"].discard(0)
    temps["bed"].discard(0)
    return temps


def _gcode_structure(gcode_path: Path) -> dict[str, bool]:
    """Check for key G-code structural elements."""
    text = gcode_path.read_text()
    lines = text.splitlines()
    first_50 = "\n".join(lines[:50])
    last_50 = "\n".join(lines[-50:])

    return {
        "has_home": any("G28" in ln for ln in lines[:100]),
        "has_bed_level": any("G29" in ln for ln in lines[:200]),
        "has_relative_e": any("M83" in ln for ln in lines[:200]),
        "has_absolute_e": any("M82" in ln for ln in lines[:200]),
        "has_start_gcode": "start" in first_50.lower() or "G28" in first_50,
        "has_end_gcode": "end" in last_50.lower() or "M400" in last_50,
        "has_retraction": any(re.match(r"G1\s.*E-", ln) for ln in lines),
        "has_z_hop": any(re.match(r"G1\s+Z\d", ln) for ln in lines[:500]),
        "total_lines": len(lines),
        "total_moves": sum(1 for ln in lines if ln.startswith("G1 ")),
    }


def _stl_to_3mf(stl_path: Path, output_dir: Path) -> Path:
    """Package an STL into a 3MF that OrcaSlicer can load.

    Uses estampo's own plate builder which produces 3MFs with the
    metadata structure OrcaSlicer expects (plain trimesh 3MF export
    is not sufficient).
    """
    import trimesh

    from estampo.arrange import Placement
    from estampo.plate import build_plate, export_plate

    mesh = trimesh.load(str(stl_path), force="mesh")
    # Center on plate, touching the bed
    mesh.vertices -= mesh.bounds[0]
    placement = Placement(mesh=mesh, name=stl_path.stem, x=128.0, y=128.0)
    scene = build_plate([placement], plate_size=(256.0, 256.0))
    out = output_dir / (stl_path.stem + ".3mf")
    export_plate(scene, out)
    return out


def _slice_orca(stl_path: Path, output_base: Path) -> Path:
    """Slice with OrcaSlicer via Docker."""
    output_dir = output_base / "orca"
    output_dir.mkdir(parents=True, exist_ok=True)

    # OrcaSlicer CLI requires 3MF input — package the STL properly
    input_3mf = _stl_to_3mf(stl_path, output_dir)

    result = slice_plate(
        input_3mf,
        engine="orca",
        output_dir=output_dir,
        printer="Bambu Lab P1S 0.4 nozzle",
        process="0.20mm Standard @BBL X1C",
        filaments=["Generic PETG-CF @BBL X1C"],
        overrides=OVERRIDES,
        bed_type="Textured PEI Plate",
        docker_version=ORCA_VERSION,
    )
    return result


def _slice_cura(stl_path: Path, output_base: Path) -> Path:
    """Slice with CuraEngine via Docker."""
    output_dir = output_base / "cura"
    output_dir.mkdir(parents=True, exist_ok=True)

    profile = CuraProfile(
        layer_height=0.20,
        wall_line_count=3,
        infill_sparse_density=25,
        top_layers=5,
        bottom_layers=4,
        material_print_temperature=260,
        material_bed_temperature=70,
        bed_type="Textured PEI Plate",
        filament_type="PETG-CF",
    )
    image = cura_docker_image(CURA_VERSION)
    return slice_stl(stl_path, output_dir, profile, image=image)


def _pct_diff(a: float, b: float) -> str:
    """Format percentage difference between two values."""
    if a == 0 and b == 0:
        return "same"
    if a == 0 or b == 0:
        return "N/A"
    diff = abs(a - b) / ((a + b) / 2) * 100
    return f"{diff:.1f}%"


def _print_comparison(
    orca_gcode: Path,
    cura_gcode: Path,
) -> None:
    """Print a side-by-side comparison of G-code from both engines."""
    orca_meta = parse_gcode_metadata(orca_gcode)
    cura_meta = parse_gcode_metadata(cura_gcode)

    orca_info = analyze_gcode(orca_gcode)
    cura_info = analyze_gcode(cura_gcode)

    orca_temps = _gcode_temps(orca_gcode)
    cura_temps = _gcode_temps(cura_gcode)

    orca_struct = _gcode_structure(orca_gcode)
    cura_struct = _gcode_structure(cura_gcode)

    w = 22  # column width

    def row(label: str, orca_val: str, cura_val: str, note: str = "") -> str:
        note_str = f"  ({note})" if note else ""
        return f"  {label:<24} {orca_val:>{w}} {cura_val:>{w}}{note_str}"

    print("\n" + "=" * 76)
    print("  OrcaSlicer vs CuraEngine — G-code Comparison")
    print("=" * 76)

    # Files
    print(f"\n  OrcaSlicer: {orca_gcode}")
    print(f"  CuraEngine: {cura_gcode}")

    # --- Metrics ---
    print(f"\n{'  METRIC':<26} {'ORCA':>{w}} {'CURA':>{w}}")
    print("  " + "-" * (24 + w * 2 + 2))

    # Filament
    og = orca_meta.get("filament_g", 0)
    cg = cura_meta.get("filament_g", 0)
    print(row("Filament (g)", f"{og:.2f}", f"{cg:.2f}", _pct_diff(float(og), float(cg))))

    ocm3 = orca_meta.get("filament_cm3", 0)
    ccm3 = cura_meta.get("filament_cm3", 0)
    print(row("Filament (cm³)", f"{ocm3:.2f}", f"{ccm3:.2f}", _pct_diff(float(ocm3), float(ccm3))))

    # Time
    ot = orca_meta.get("print_time", "?")
    ct = cura_meta.get("print_time", "?")
    ots = orca_meta.get("print_time_secs", 0)
    cts = cura_meta.get("print_time_secs", 0)
    time_note = _pct_diff(float(ots), float(cts)) if ots and cts else ""
    print(row("Print time", str(ot), str(ct), time_note))

    # Layers
    print(row("Layer count", str(orca_info.layer_count), str(cura_info.layer_count)))

    # Temperatures
    o_nozzle = sorted(orca_temps["nozzle"])
    c_nozzle = sorted(cura_temps["nozzle"])
    o_nozzle_s = str(o_nozzle) if o_nozzle else "?"
    c_nozzle_s = str(c_nozzle) if c_nozzle else "?"
    print(row("Nozzle temps (°C)", o_nozzle_s, c_nozzle_s))

    o_bed = sorted(orca_temps["bed"])
    c_bed = sorted(cura_temps["bed"])
    print(row("Bed temps (°C)", str(o_bed) if o_bed else "?", str(c_bed) if c_bed else "?"))

    # --- Structure ---
    print(f"\n{'  STRUCTURE':<26} {'ORCA':>{w}} {'CURA':>{w}}")
    print("  " + "-" * (24 + w * 2 + 2))

    print(row("Total lines", str(orca_struct["total_lines"]), str(cura_struct["total_lines"])))
    print(row("G1 move commands", str(orca_struct["total_moves"]), str(cura_struct["total_moves"])))

    bool_checks = [
        ("Home (G28)", "has_home"),
        ("Bed level (G29)", "has_bed_level"),
        ("Relative E (M83)", "has_relative_e"),
        ("Absolute E (M82)", "has_absolute_e"),
        ("Start G-code", "has_start_gcode"),
        ("End G-code", "has_end_gcode"),
        ("Retraction", "has_retraction"),
    ]
    for label, key in bool_checks:
        ov = "✓" if orca_struct[key] else "✗"
        cv = "✓" if cura_struct[key] else "✗"
        print(row(label, ov, cv))

    # --- Verdict ---
    print("\n" + "  " + "-" * 72)
    issues = []
    if float(cg) == 0:
        issues.append("CuraEngine reported zero filament usage")
    elif float(og) > 0 and abs(float(cg) - float(og)) / float(og) > 0.5:
        issues.append(f"Filament usage differs by {_pct_diff(float(og), float(cg))}")
    if cura_info.layer_count == 0:
        issues.append("CuraEngine produced zero layers")
    if not cura_struct["has_start_gcode"]:
        issues.append("CuraEngine G-code missing start sequence")
    if not cura_struct["has_end_gcode"]:
        issues.append("CuraEngine G-code missing end sequence")
    if not cura_struct["has_retraction"]:
        issues.append("CuraEngine G-code has no retractions")

    if issues:
        print("  VERDICT: Issues found")
        for issue in issues:
            print(f"    ⚠  {issue}")
    else:
        print("  VERDICT: CuraEngine output looks reasonable")
        print("    Both engines produced valid G-code with comparable metrics.")

    print("=" * 76 + "\n")


def main() -> None:
    import tempfile

    # Determine STL input
    if len(sys.argv) > 1:
        stl_path = Path(sys.argv[1]).resolve()
        if not stl_path.exists():
            print(f"Error: file not found: {stl_path}", file=sys.stderr)
            sys.exit(1)
    else:
        stl_path = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "cube_10mm.stl"
        if not stl_path.exists():
            print(f"Error: test fixture not found: {stl_path}", file=sys.stderr)
            sys.exit(1)

    print(f"Input: {stl_path.name}")
    print(f"Engines: OrcaSlicer {ORCA_VERSION} vs CuraEngine {CURA_VERSION}")
    print("Settings: 0.20mm layers, 3 walls, 25% infill, PETG-CF, P1S")

    output_base = Path(tempfile.mkdtemp(prefix="estampo_compare_"))
    print(f"Output: {output_base}\n")

    # Slice with both engines
    print("Slicing with OrcaSlicer...")
    try:
        orca_dir = _slice_orca(stl_path, output_base)
        orca_gcode = _find_gcode(orca_dir)
        if not orca_gcode:
            print("  ERROR: No gcode output from OrcaSlicer", file=sys.stderr)
            sys.exit(1)
        print(f"  → {orca_gcode.name} ({orca_gcode.stat().st_size:,} bytes)")
    except Exception as e:
        print(f"  ERROR: OrcaSlicer failed: {e}", file=sys.stderr)
        sys.exit(1)

    print("Slicing with CuraEngine...")
    try:
        cura_dir = _slice_cura(stl_path, output_base)
        cura_gcode = _find_gcode(cura_dir)
        if not cura_gcode:
            print("  ERROR: No gcode output from CuraEngine", file=sys.stderr)
            sys.exit(1)
        print(f"  → {cura_gcode.name} ({cura_gcode.stat().st_size:,} bytes)")
    except Exception as e:
        print(f"  ERROR: CuraEngine failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Compare
    _print_comparison(orca_gcode, cura_gcode)


if __name__ == "__main__":
    main()

"""Shared gcode metadata parsing utilities."""

from __future__ import annotations

import math
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from estampo import require_file

# Number of lines to scan from the start/end of gcode for metadata
GCODE_HEADER_LINES = 300
GCODE_TAIL_LINES = 50

# Filament constants (1.75mm diameter, PLA/PETG average density)
_DIAMETER_CM = 0.175
_DENSITY_G_CM3 = 1.24

# Regex for extracting E values from G1 moves (absolute extrusion)
_E_VALUE_RE = re.compile(r"E([\d.]+)")


def _max_e_value(lines: list[str]) -> float:
    """Compute total filament extruded in mm from G-code E moves.

    Handles both absolute (M82) and relative (M83) extrusion modes.
    For absolute mode, tracks the running max E, accumulating across G92 resets.
    For relative mode, sums all positive E values (ignores retracts).
    """
    total = 0.0
    max_e = 0.0
    relative = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("M83"):
            relative = True
        elif stripped.startswith("M82"):
            relative = False
        elif stripped.startswith("G92"):
            if not relative and (m := _E_VALUE_RE.search(stripped)):
                # Absolute mode E reset — accumulate what we had and restart
                total += max_e
                max_e = float(m.group(1))
        elif stripped.startswith("G1"):
            if m := _E_VALUE_RE.search(stripped):
                e = float(m.group(1))
                if relative:
                    if e > 0:
                        total += e
                else:
                    if e > max_e:
                        max_e = e
    if not relative:
        total += max_e
    return total


def _format_seconds(secs: int) -> str:
    """Format seconds as a human-readable time string like '1h 7m 32s'."""
    parts = []
    if secs >= 3600:
        parts.append(f"{secs // 3600}h")
        secs %= 3600
    if secs >= 60:
        parts.append(f"{secs // 60}m")
        secs %= 60
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def parse_gcode_metadata(gcode_path: Path) -> dict[str, str | float | int]:
    """Extract print time and filament stats from gcode comments.

    Scans header (first GCODE_HEADER_LINES lines) for print time, and tail
    (last GCODE_TAIL_LINES lines) for filament usage. Handles both
    OrcaSlicer/BambuStudio and CuraEngine formats.

    Returns dict with keys like 'print_time', 'print_time_secs',
    'filament_g', and/or 'filament_cm3'.
    """
    lines = gcode_path.read_text().splitlines()
    stats: dict[str, str | float | int] = {}

    # Scan header for print time and CuraEngine metadata
    for line in lines[:GCODE_HEADER_LINES]:
        # OrcaSlicer / BambuStudio formats
        if m := re.search(r"total estimated time:\s*(.+?)(?:;|$)", line):
            stats["print_time"] = m.group(1).strip()
        elif m := re.match(r";\s*estimated printing time.*?=\s*(.+)", line):
            stats["print_time"] = m.group(1).strip()
        # CuraEngine: ;TIME:1234 (seconds)
        elif m := re.match(r";TIME:(\d+)", line):
            secs = int(m.group(1))
            stats["print_time"] = _format_seconds(secs)
            stats["print_time_secs"] = secs
        # CuraEngine: ;Filament used: 1.23456m
        elif m := re.match(r";Filament used:\s*([\d.]+)m", line):
            meters = float(m.group(1))
            cm3 = meters * 100 * math.pi * (_DIAMETER_CM / 2) ** 2
            stats["filament_cm3"] = round(cm3, 2)
            stats["filament_g"] = round(cm3 * _DENSITY_G_CM3, 2)

    # CuraEngine: prefer the last ;TIME_ELAPSED cumulative value over the
    # header ;TIME: placeholder (which can be a bogus default like 6666).
    last_elapsed: float | None = None
    for line in lines:
        if m := re.match(r";TIME_ELAPSED:([\d.]+)", line):
            last_elapsed = float(m.group(1))
    if last_elapsed is not None:
        secs = round(last_elapsed)
        stats["print_time"] = _format_seconds(secs)
        stats["print_time_secs"] = secs

    # Scan tail for OrcaSlicer filament stats (CuraEngine puts them in header).
    # OrcaSlicer emits one line per slot (including 0.00 for unused slots)
    # and sometimes a separate total line.
    # Prefer explicit "total" lines; fall back to summing per-slot lines.
    filament_g_slots: list[float] = []
    filament_g_total: float | None = None
    filament_cm3_slots: list[float] = []
    filament_cm3_total: float | None = None
    for line in lines[-GCODE_TAIL_LINES:]:
        if m := re.match(r";\s*total filament used \[g\]\s*=\s*([\d.]+)", line):
            filament_g_total = float(m.group(1))
        elif m := re.match(r";\s*filament used \[g\]\s*=\s*(.+)", line):
            filament_g_slots.extend(float(v) for v in m.group(1).split(","))
        elif m := re.match(r";\s*total filament used \[cm3\]\s*=\s*([\d.]+)", line):
            filament_cm3_total = float(m.group(1))
        elif m := re.match(r";\s*filament used \[cm3\]\s*=\s*(.+)", line):
            filament_cm3_slots.extend(float(v) for v in m.group(1).split(","))
    # Only override CuraEngine stats if OrcaSlicer stats were found
    g = filament_g_total if filament_g_total is not None else sum(filament_g_slots)
    cm3 = filament_cm3_total if filament_cm3_total is not None else sum(filament_cm3_slots)
    if g > 0:
        stats["filament_g"] = g
    if cm3 > 0:
        stats["filament_cm3"] = cm3

    # Fallback: if no filament stats found (or zero), compute from E moves.
    # This covers CuraEngine's placeholder-header bug and any other slicer
    # that doesn't embed filament stats in the G-code.
    if not stats.get("filament_g"):
        e_mm = _max_e_value(lines)
        if e_mm > 0:
            e_cm3 = (e_mm / 10) * math.pi * (_DIAMETER_CM / 2) ** 2
            stats["filament_cm3"] = round(e_cm3, 2)
            stats["filament_g"] = round(e_cm3 * _DENSITY_G_CM3, 2)

    # Convert time string like "1h 7m 32s" to seconds (if not already set)
    if "print_time" in stats and "print_time_secs" not in stats:
        t = str(stats["print_time"])
        secs = 0
        if hm := re.search(r"(\d+)h", t):
            secs += int(hm.group(1)) * 3600
        if mm := re.search(r"(\d+)m", t):
            secs += int(mm.group(1)) * 60
        if sm := re.search(r"(\d+)s", t):
            secs += int(sm.group(1))
        if secs > 0:
            stats["print_time_secs"] = secs

    return stats


@dataclass
class LayerSpan:
    """A contiguous range of layers using the same extruder."""

    start_layer: int
    end_layer: int
    extruder: int  # 0-indexed
    start_z: float
    end_z: float


@dataclass
class GcodeInfo:
    """Parsed gcode analysis result."""

    filament_types: list[str] = field(default_factory=list)  # per-slot filament types
    layer_count: int = 0
    spans: list[LayerSpan] = field(default_factory=list)
    filament_changes: int = 0
    filament_usage_g: list[float] = field(default_factory=list)  # per-slot grams
    print_time: str = ""


def read_gcode(path: Path) -> str:
    """Read gcode from a .gcode file or from inside a .gcode.3mf zip."""
    path = Path(path)
    require_file(path, "Gcode file")

    if path.suffix == ".3mf" or path.name.endswith(".gcode.3mf"):
        with zipfile.ZipFile(path, "r") as zf:
            gcode_names = [n for n in zf.namelist() if n.endswith(".gcode")]
            if not gcode_names:
                raise ValueError(f"No .gcode file found inside {path}")
            return zf.read(gcode_names[0]).decode("utf-8", errors="replace")

    return path.read_text()


def analyze_gcode(path: Path) -> GcodeInfo:
    """Analyze gcode for extruder usage per layer.

    Parses layer boundaries, tool changes (T{n}), filament types, and
    per-slot usage from OrcaSlicer/BambuStudio and CuraEngine gcode.

    OrcaSlicer uses ``; CHANGE_LAYER`` / ``; Z_HEIGHT:`` markers.
    CuraEngine uses ``;LAYER:N`` / ``G0 ... Z{height}`` patterns.
    """
    text = read_gcode(path)
    lines = text.splitlines()
    info = GcodeInfo()

    # Parse filament types and print time from header
    for line in lines[:GCODE_HEADER_LINES]:
        # OrcaSlicer
        if m := re.match(r";\s*filament_type\s*=\s*(.+)", line):
            info.filament_types = [t.strip() for t in m.group(1).split(";")]
        elif m := re.search(r"total estimated time:\s*(.+?)(?:;|$)", line):
            info.print_time = m.group(1).strip()
        elif m := re.match(r";\s*estimated printing time.*?=\s*(.+)", line):
            info.print_time = m.group(1).strip()
        # CuraEngine (header value — may be overridden by TIME_ELAPSED below)
        elif m := re.match(r";TIME:(\d+)", line):
            info.print_time = _format_seconds(int(m.group(1)))
        elif m := re.match(r";MATERIAL:(\d+)", line):
            # CuraEngine material index (single extruder)
            pass  # filament type not encoded here
        elif m := re.match(r";Filament used:\s*([\d.]+)m", line):
            meters = float(m.group(1))
            cm3 = meters * 100 * math.pi * (_DIAMETER_CM / 2) ** 2
            info.filament_usage_g = [round(cm3 * _DENSITY_G_CM3, 2)]

    # Parse per-slot filament usage from tail (OrcaSlicer)
    for line in lines[-GCODE_TAIL_LINES:]:
        if m := re.match(r";\s*filament used \[g\]\s*=\s*(.+)", line):
            info.filament_usage_g = [float(v.strip()) for v in m.group(1).split(",")]

    # Fallback: compute from E moves if no filament usage found (or zero)
    if not info.filament_usage_g or all(v == 0 for v in info.filament_usage_g):
        e_mm = _max_e_value(lines)
        if e_mm > 0:
            e_cm3 = (e_mm / 10) * math.pi * (_DIAMETER_CM / 2) ** 2
            info.filament_usage_g = [round(e_cm3 * _DENSITY_G_CM3, 2)]

    # Walk gcode for layers and tool changes.
    # OrcaSlicer: Z_HEIGHT appears immediately after CHANGE_LAYER.
    # CuraEngine: ;LAYER:N marks layer boundaries, Z from G0/G1 moves.
    current_layer = 0
    current_z = 0.0
    current_extruder = 0  # 0-indexed
    layer_z: dict[int, float] = {}  # layer number → z height

    # (layer, extruder) pairs recording each tool change point
    tool_events: list[tuple[int, int]] = []  # (layer_at_change, new_extruder)
    last_elapsed: float | None = None

    for line in lines:
        # OrcaSlicer layer marker
        if line.startswith("; CHANGE_LAYER"):
            current_layer += 1
        elif m := re.match(r"; Z_HEIGHT:\s*([\d.]+)", line):
            current_z = float(m.group(1))
            layer_z[current_layer] = current_z
        # CuraEngine layer marker: ;LAYER:0, ;LAYER:1, etc.
        elif m := re.match(r";LAYER:(\d+)", line):
            current_layer = int(m.group(1)) + 1  # normalize to 1-indexed
            layer_z[current_layer] = current_z
        # CuraEngine cumulative time elapsed
        elif m := re.match(r";TIME_ELAPSED:([\d.]+)", line):
            last_elapsed = float(m.group(1))
        # CuraEngine Z moves (G0/G1 with Z parameter)
        elif m := re.match(r"G[01]\s.*Z([\d.]+)", line):
            current_z = float(m.group(1))
            if current_layer in layer_z:
                layer_z[current_layer] = current_z
        elif m := re.match(r"T(\d+)$", line):
            tool = int(m.group(1))
            # Skip special tool numbers (T1000 = initial load, T255 = unload)
            if tool >= 255:
                continue
            if current_layer == 0:
                # Pre-print tool select — set initial extruder, not a change
                current_extruder = tool
            elif tool != current_extruder:
                if not tool_events:
                    # Record initial extruder span starting at layer 1
                    tool_events.append((1, current_extruder))
                tool_events.append((current_layer, tool))
                info.filament_changes += 1
                current_extruder = tool

    # Prefer TIME_ELAPSED over the header ;TIME: placeholder
    if last_elapsed is not None:
        info.print_time = _format_seconds(round(last_elapsed))

    # If no tool events recorded, the initial extruder was used throughout
    if not tool_events and current_layer > 0:
        tool_events.append((1, current_extruder))

    # Build spans from tool events
    for i, (start_layer, extruder) in enumerate(tool_events):
        if i + 1 < len(tool_events):
            end_layer = tool_events[i + 1][0]
        else:
            end_layer = current_layer
        info.spans.append(
            LayerSpan(
                start_layer=start_layer,
                end_layer=end_layer,
                extruder=extruder,
                start_z=layer_z.get(start_layer, 0.0),
                end_z=layer_z.get(end_layer, current_z),
            )
        )

    info.layer_count = current_layer
    return info

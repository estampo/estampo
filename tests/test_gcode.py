"""Tests for shared gcode metadata parsing."""

import zipfile

from estampo.gcode import analyze_gcode, parse_gcode_metadata


def test_parse_print_time(tmp_path):
    gcode = tmp_path / "test.gcode"
    gcode.write_text("; total estimated time: 1h 7m 32s\nG28\n")
    stats = parse_gcode_metadata(gcode)
    assert stats["print_time"] == "1h 7m 32s"
    assert stats["print_time_secs"] == 3600 + 7 * 60 + 32


def test_parse_filament_weight(tmp_path):
    # Filament stats appear in the last 50 lines
    lines = ["G1 X0\n"] * 10
    lines.append("; total filament used [g] = 12.34\n")
    lines.append("; total filament used [cm3] = 9.87\n")
    gcode = tmp_path / "test.gcode"
    gcode.write_text("".join(lines))
    stats = parse_gcode_metadata(gcode)
    assert stats["filament_g"] == 12.34
    assert stats["filament_cm3"] == 9.87


def test_parse_empty_gcode(tmp_path):
    gcode = tmp_path / "empty.gcode"
    gcode.write_text("G28\nG1 X0\n")
    stats = parse_gcode_metadata(gcode)
    assert "print_time" not in stats
    assert "filament_g" not in stats


def test_parse_alternative_time_format(tmp_path):
    gcode = tmp_path / "test.gcode"
    gcode.write_text("; estimated printing time (normal mode) = 2h 30m 0s\nG28\n")
    stats = parse_gcode_metadata(gcode)
    assert stats["print_time"] == "2h 30m 0s"
    assert stats["print_time_secs"] == 2 * 3600 + 30 * 60


def test_parse_minutes_only(tmp_path):
    gcode = tmp_path / "test.gcode"
    gcode.write_text("; total estimated time: 45m 10s\nG28\n")
    stats = parse_gcode_metadata(gcode)
    assert stats["print_time_secs"] == 45 * 60 + 10


# --- CuraEngine format ---


def test_parse_cura_time(tmp_path):
    gcode = tmp_path / "test.gcode"
    gcode.write_text(";Generated with Cura_SteamEngine 5.12.0\n;TIME:4052\nG28\n")
    stats = parse_gcode_metadata(gcode)
    assert stats["print_time_secs"] == 4052
    assert stats["print_time"] == "1h 7m 32s"


def test_parse_cura_time_elapsed_overrides_header(tmp_path):
    """TIME_ELAPSED is preferred over the header ;TIME: placeholder."""
    gcode = tmp_path / "test.gcode"
    gcode.write_text(
        ";Generated with Cura_SteamEngine 5.12.0\n"
        ";TIME:6666\n"
        "G28\n"
        ";LAYER:0\n"
        "G1 X10 Y10 E1\n"
        ";TIME_ELAPSED:100.5\n"
        ";LAYER:1\n"
        "G1 X20 Y20 E2\n"
        ";TIME_ELAPSED:223.86\n"
    )
    stats = parse_gcode_metadata(gcode)
    assert stats["print_time_secs"] == 224
    assert stats["print_time"] == "3m 44s"


def test_parse_cura_filament(tmp_path):
    gcode = tmp_path / "test.gcode"
    gcode.write_text(";Generated with Cura_SteamEngine 5.12.0\n;Filament used: 1.23456m\nG28\n")
    stats = parse_gcode_metadata(gcode)
    assert stats["filament_cm3"] > 0
    assert stats["filament_g"] > 0


def test_analyze_cura_layers(tmp_path):
    """CuraEngine uses ;LAYER:N markers."""
    lines = [
        ";Generated with Cura_SteamEngine 5.12.0",
        ";TIME:600",
        ";Filament used: 0.5m",
        "G28",
        ";LAYER_COUNT:3",
        ";LAYER:0",
        "G0 Z0.2",
        "G1 X10 Y10 E1",
        ";LAYER:1",
        "G0 Z0.4",
        "G1 X20 Y20 E2",
        ";LAYER:2",
        "G0 Z0.6",
        "G1 X30 Y30 E3",
    ]
    gcode = tmp_path / "test.gcode"
    gcode.write_text("\n".join(lines))
    info = analyze_gcode(gcode)
    assert info.layer_count == 3
    assert info.print_time == "10m"
    assert len(info.spans) == 1
    assert info.spans[0].extruder == 0


def test_e_value_fallback_when_header_reports_zero(tmp_path):
    """When header says ;Filament used: 0m, fall back to E-value calculation."""
    lines = [
        ";FLAVOR:Marlin",
        ";TIME:1000",
        ";Filament used: 0m",
        ";Generated with Cura_SteamEngine 5.12.0",
        "M82 ;absolute extrusion mode",
        "G92 E0",
        "G1 X10 Y10 E5.0 F1000",
        "G1 X20 Y20 E10.0",
        "G1 X30 Y30 E15.0",
    ]
    gcode = tmp_path / "test.gcode"
    gcode.write_text("\n".join(lines))
    stats = parse_gcode_metadata(gcode)
    # Should have computed filament from E values, not from the 0m header
    assert stats["filament_g"] > 0
    assert stats["filament_cm3"] > 0


def test_e_value_fallback_analyze_gcode(tmp_path):
    """analyze_gcode also falls back to E values for zero filament header."""
    lines = [
        ";Generated with Cura_SteamEngine 5.12.0",
        ";TIME:600",
        ";Filament used: 0m",
        ";LAYER_COUNT:2",
        ";LAYER:0",
        "G0 Z0.2",
        "M82",
        "G92 E0",
        "G1 X10 Y10 E5.0 F1000",
        ";LAYER:1",
        "G0 Z0.4",
        "G1 X20 Y20 E10.0",
    ]
    gcode = tmp_path / "test.gcode"
    gcode.write_text("\n".join(lines))
    info = analyze_gcode(gcode)
    assert info.filament_usage_g
    assert info.filament_usage_g[0] > 0


def test_e_value_tracks_g92_resets(tmp_path):
    """E-value fallback correctly handles G92 E0 resets."""
    lines = [
        ";Filament used: 0m",
        "M82",
        "G92 E0",
        "G1 X10 E100.0",
        "G92 E0",  # reset — 100mm accumulated
        "G1 X20 E50.0",
    ]
    gcode = tmp_path / "test.gcode"
    gcode.write_text("\n".join(lines))
    stats = parse_gcode_metadata(gcode)
    # Total E = 100 + 50 = 150mm
    assert stats["filament_g"] > 0


# --- analyze_gcode ---


def _make_gcode(layers, tool_changes=None, filament_types=None, initial_tool=None):
    """Build a synthetic gcode string.

    layers: number of layers
    tool_changes: dict of layer_number → new_tool (0-indexed)
    filament_types: list of filament type strings
    initial_tool: tool number set before layer 1
    """
    lines = []
    if filament_types:
        lines.append(f"; filament_type = {';'.join(filament_types)}")
    lines.append("; total estimated time: 10m 0s")
    # Initial tool select (before any layers)
    lines.append("T1000")  # initial load
    if initial_tool is not None:
        lines.append(f"T{initial_tool}")
    for layer in range(1, layers + 1):
        z = layer * 0.2
        lines.append("; CHANGE_LAYER")
        lines.append(f"; Z_HEIGHT: {z}")
        lines.append("; LAYER_HEIGHT: 0.2")
        if tool_changes and layer in tool_changes:
            lines.append(f"T{tool_changes[layer]}")
        lines.append(f"G1 X10 Y10 Z{z} E1")
    lines.append("T255")  # unload
    return "\n".join(lines)


def test_analyze_single_extruder(tmp_path):
    """Single extruder, no changes."""
    gcode = tmp_path / "test.gcode"
    gcode.write_text(_make_gcode(50, initial_tool=0))
    info = analyze_gcode(gcode)
    assert info.layer_count == 50
    assert info.filament_changes == 0
    assert len(info.spans) == 1
    assert info.spans[0].extruder == 0
    assert info.spans[0].start_layer == 1
    assert info.spans[0].end_layer == 50


def test_analyze_tool_change(tmp_path):
    """Extruder change at layer 5."""
    gcode = tmp_path / "test.gcode"
    gcode.write_text(
        _make_gcode(
            20,
            initial_tool=1,
            tool_changes={5: 2},
            filament_types=["ABS", "PLA", "PETG-CF"],
        )
    )
    info = analyze_gcode(gcode)
    assert info.layer_count == 20
    assert info.filament_changes == 1
    assert len(info.spans) == 2
    # First span: extruder 1 (PLA), layers 1-5
    assert info.spans[0].extruder == 1
    assert info.spans[0].start_layer == 1
    assert info.spans[0].end_layer == 5
    assert abs(info.spans[0].start_z - 0.2) < 0.01
    # Second span: extruder 2 (PETG-CF), layers 5-20
    assert info.spans[1].extruder == 2
    assert info.spans[1].start_layer == 5
    assert info.spans[1].end_layer == 20
    assert info.filament_types == ["ABS", "PLA", "PETG-CF"]


def test_analyze_multiple_changes(tmp_path):
    """Multiple extruder changes."""
    gcode = tmp_path / "test.gcode"
    gcode.write_text(_make_gcode(30, initial_tool=0, tool_changes={4: 1, 10: 0}))
    info = analyze_gcode(gcode)
    assert info.filament_changes == 2
    assert len(info.spans) == 3
    assert info.spans[0].extruder == 0
    assert info.spans[1].extruder == 1
    assert info.spans[2].extruder == 0


def test_analyze_gcode_3mf(tmp_path):
    """Reads gcode from inside a .gcode.3mf zip."""
    gcode_text = _make_gcode(10, initial_tool=0)
    path = tmp_path / "plate.gcode.3mf"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Metadata/plate_1.gcode", gcode_text)
    info = analyze_gcode(path)
    assert info.layer_count == 10
    assert len(info.spans) == 1


def test_analyze_print_time(tmp_path):
    """Print time is parsed."""
    gcode = tmp_path / "test.gcode"
    gcode.write_text(_make_gcode(5, initial_tool=0))
    info = analyze_gcode(gcode)
    assert info.print_time == "10m 0s"

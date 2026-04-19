"""Tests for CuraEngine slicer backend."""

from unittest.mock import MagicMock, patch

import pytest

from estampo import EstampoError
from estampo.cura import (
    _FILAMENT_TEMPS,
    _check_local_def,
    _copy_cura_def_chain,
    _extruder_settings_str,
    _fetch_printer_def,
    _machine_dims_flags,
    _patch_gcode_header,
    _place_on_bed,
    _resolve_def_chain,
    _resolve_def_name,
    _settings_dict,
    _settings_flags,
    _surface_cura_warnings,
    _write_cura_settings,
    build_cura_config,
    cura_docker_image,
    pin_cura_definitions,
    resolve_cura_center_is_zero,
    resolve_cura_machine_dims,
    slice_stl,
    slice_stl_multi,
    validate_cura_settings,
)

# --- _resolve_def_name ---


def test_resolve_def_name_exact_match():
    """Exact manifest name maps to definition ID."""
    assert _resolve_def_name("Ultimaker 2") == "ultimaker2"


def test_resolve_def_name_none_returns_default():
    """None falls back to ultimaker2."""
    assert _resolve_def_name(None) == "ultimaker2"


def test_resolve_def_name_already_id():
    """If the name is already a definition ID, return it as-is."""
    assert _resolve_def_name("ultimaker2") == "ultimaker2"


def test_resolve_def_name_case_insensitive():
    """Case-insensitive matching against manifest names."""
    assert _resolve_def_name("ultimaker 2") == "ultimaker2"


def test_resolve_def_name_strips_nozzle_suffix():
    """Machine profile names with nozzle suffix resolve correctly."""
    assert _resolve_def_name("Ultimaker 2 0.4 nozzle") == "ultimaker2"


def test_resolve_def_name_strips_nozzle_mm_suffix():
    """Nozzle suffix with mm unit resolves correctly."""
    assert _resolve_def_name("Ultimaker 2 0.6mm nozzle") == "ultimaker2"


def test_resolve_def_name_unknown_raises():
    """Unknown printer name raises EstampoError."""
    with pytest.raises(EstampoError, match="not found in the definition manifest"):
        _resolve_def_name("Totally Unknown Printer XYZ")


# --- _resolve_def_chain ---


def test_resolve_def_chain_missing_returns_empty(tmp_path):
    """Missing definition returns empty chain instead of raising."""
    chain = _resolve_def_chain("nonexistent_printer", project_dir=tmp_path)
    assert chain == []


def test_resolve_def_chain_finds_pinned(tmp_path):
    """Pinned definition is found and returned."""
    import json

    defs_dir = tmp_path / "profiles" / "cura" / "definitions"
    defs_dir.mkdir(parents=True)
    (defs_dir / "my_printer.def.json").write_text(
        json.dumps({"name": "My Printer", "overrides": {}})
    )
    chain = _resolve_def_chain("my_printer", project_dir=tmp_path)
    assert len(chain) == 1
    assert chain[0].name == "my_printer.def.json"


# --- _check_local_def ---


def test_check_local_def_raises_when_missing(tmp_path):
    """Raises EstampoError with guidance when def file missing from staging."""
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(EstampoError, match="not found locally"):
        _check_local_def(staging, "bambox_p1s.def.json", "bambox_p1s")


def test_check_local_def_passes_when_present(tmp_path):
    """No error when def file exists in staging."""
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "bambox_p1s.def.json").write_text("{}")
    _check_local_def(staging, "bambox_p1s.def.json", "bambox_p1s")  # no raise


# --- _copy_cura_def_chain (ADR-008) ---


def _write_def(path, **fields):
    import json

    path.write_text(json.dumps(fields))


def test_copy_cura_def_chain_stops_at_fdmprinter(tmp_path):
    """Root defs (fdmprinter/fdmextruder) are not included in the chain."""
    _write_def(
        tmp_path / "fdmprinter.def.json",
        name="FDM Base",
        version=2,
        settings={"machine_width": {"default_value": 200}},
    )
    _write_def(
        tmp_path / "my_printer.def.json",
        name="My Printer",
        version=2,
        inherits="fdmprinter",
        overrides={"machine_width": {"value": 300}},
    )
    chain = _copy_cura_def_chain("my_printer", tmp_path)
    names = [p.name for p in chain]
    assert names == ["my_printer.def.json"]
    assert "fdmprinter.def.json" not in names


def test_copy_cura_def_chain_includes_intermediate(tmp_path):
    """Intermediate ancestors are included; fdmprinter is not."""
    _write_def(tmp_path / "fdmprinter.def.json", name="FDM Base", version=2, settings={})
    _write_def(
        tmp_path / "base_printer.def.json",
        name="Base Printer",
        version=2,
        inherits="fdmprinter",
        overrides={"speed_print": {"value": 60}},
    )
    _write_def(
        tmp_path / "my_printer.def.json",
        name="My Printer",
        version=2,
        inherits="base_printer",
        overrides={"machine_width": {"value": 300}},
    )
    chain = _copy_cura_def_chain("my_printer", tmp_path)
    names = [p.name for p in chain]
    # Leaf first, nearest non-root ancestor last; fdmprinter excluded
    assert names == ["my_printer.def.json", "base_printer.def.json"]


def test_copy_cura_def_chain_stops_at_fdmextruder(tmp_path):
    """fdmextruder is treated as a root definition and excluded from the chain."""
    _write_def(tmp_path / "fdmextruder.def.json", name="FDM Extruder", version=2, settings={})
    _write_def(
        tmp_path / "my_extruder.def.json",
        name="My Extruder",
        version=2,
        inherits="fdmextruder",
        overrides={"material_diameter": {"default_value": 1.75}},
    )
    chain = _copy_cura_def_chain("my_extruder", tmp_path)
    assert [p.name for p in chain] == ["my_extruder.def.json"]


def test_copy_cura_def_chain_missing_leaf_raises(tmp_path):
    """Raises when the leaf definition itself cannot be located."""
    with pytest.raises(EstampoError, match="not found in"):
        _copy_cura_def_chain("nonexistent", tmp_path)


def test_copy_cura_def_chain_missing_ancestor_stops_without_raising(tmp_path):
    """A missing non-root ancestor truncates the chain; leaf is still returned."""
    _write_def(
        tmp_path / "my_printer.def.json",
        name="My Printer",
        version=2,
        inherits="missing_base",
        overrides={"machine_width": {"value": 300}},
    )
    chain = _copy_cura_def_chain("my_printer", tmp_path)
    assert [p.name for p in chain] == ["my_printer.def.json"]


# --- pin_cura_definitions (ADR-008 verbatim copy) ---


def test_pin_cura_definitions_copies_chain_verbatim(tmp_path, monkeypatch):
    """Each ancestor def is copied byte-for-byte into profiles/cura/definitions/."""
    import json

    source_dir = tmp_path / "bundled"
    source_dir.mkdir()
    monkeypatch.setattr("estampo.cura._DATA_DIR", source_dir)

    # A realistic-ish chain: leaf → mid → fdmprinter (the root is bundled)
    fdmprinter = {
        "name": "FDM Base",
        "version": 2,
        "settings": {"machine_width": {"default_value": 200}},
    }
    mid = {
        "name": "Base Printer",
        "version": 2,
        "inherits": "fdmprinter",
        "overrides": {
            "speed_print": {"value": 60},
            "acceleration_infill": {"value": "acceleration_print"},
        },
    }
    leaf = {
        "name": "My Printer",
        "version": 2,
        "inherits": "base_printer",
        "metadata": {"visible": True},
        "overrides": {
            "machine_width": {"default_value": 256, "value": 256},
            "adhesion_type": {"value": "'brim'"},
        },
    }
    (source_dir / "fdmprinter.def.json").write_text(json.dumps(fdmprinter, indent=4))
    (source_dir / "base_printer.def.json").write_text(json.dumps(mid, indent=4))
    (source_dir / "my_printer.def.json").write_text(json.dumps(leaf, indent=4))

    project_dir = tmp_path / "project"
    pinned = pin_cura_definitions("my_printer", project_dir)

    dest_dir = project_dir / "profiles" / "cura" / "definitions"
    # Leaf + intermediate are pinned; fdmprinter is NOT (estampo ships it)
    assert (dest_dir / "my_printer.def.json") in pinned
    assert (dest_dir / "base_printer.def.json") in pinned
    assert not (dest_dir / "fdmprinter.def.json").exists()

    # Byte-for-byte equality — no transformation of value/default_value/inherits
    assert (dest_dir / "my_printer.def.json").read_bytes() == (
        source_dir / "my_printer.def.json"
    ).read_bytes()
    assert (dest_dir / "base_printer.def.json").read_bytes() == (
        source_dir / "base_printer.def.json"
    ).read_bytes()

    # Inheritance metadata and expression values are preserved verbatim
    pinned_leaf = json.loads((dest_dir / "my_printer.def.json").read_text())
    assert pinned_leaf["inherits"] == "base_printer"
    assert pinned_leaf["overrides"]["adhesion_type"] == {"value": "'brim'"}
    pinned_mid = json.loads((dest_dir / "base_printer.def.json").read_text())
    assert pinned_mid["inherits"] == "fdmprinter"
    assert pinned_mid["overrides"]["acceleration_infill"] == {"value": "acceleration_print"}


def test_pin_cura_definitions_returns_existing_local_file(tmp_path):
    """When the printer is already a local file path, no pinning is performed."""
    project_dir = tmp_path / "project"
    profiles_dir = project_dir / "profiles" / "cura" / "definitions"
    profiles_dir.mkdir(parents=True)
    existing = profiles_dir / "custom_printer.def.json"
    existing.write_text('{"name": "Custom", "version": 2}')

    pinned = pin_cura_definitions(str(existing), project_dir)
    assert pinned == [existing]


# --- cura_docker_image ---


def test_cura_docker_image_default():
    assert cura_docker_image() == "estampo/estampo:cura-5.12.0"


def test_cura_docker_image_versioned():
    assert cura_docker_image("5.12.0") == "estampo/estampo:cura-5.12.0"


def test_cura_docker_image_custom_version():
    assert cura_docker_image("5.13.0") == "estampo/estampo:cura-5.13.0"


# --- build_cura_config (raw TOML passthrough) ---


def test_build_cura_config_empty():
    """No overrides → empty dict and no per-extruder entries."""
    overrides, per_extruder = build_cura_config()
    assert overrides == {}
    assert per_extruder == []


def test_build_cura_config_bed_type_seeds_buildplate():
    """bed_type populates machine_buildplate_type with normalized casing."""
    overrides, _ = build_cura_config(bed_type="Engineering Plate")
    assert overrides["machine_buildplate_type"] == "engineering_plate"


def test_build_cura_config_filament_type_seeds_material():
    """filament_type populates material_type."""
    overrides, _ = build_cura_config(filament_type="PLA")
    assert overrides["material_type"] == "PLA"


def test_build_cura_config_raw_passthrough_preserves_types():
    """TOML overrides pass through verbatim — ints, floats, bools, strings untouched."""
    overrides = {
        "layer_height": 0.12,
        "wall_line_count": 5,
        "support_enable": True,
        "infill_pattern": "gyroid",
    }
    result, _ = build_cura_config(overrides=overrides)
    assert result["layer_height"] == 0.12
    assert isinstance(result["layer_height"], float)
    assert result["wall_line_count"] == 5
    assert isinstance(result["wall_line_count"], int)
    assert result["support_enable"] is True
    assert result["infill_pattern"] == "gyroid"


def test_build_cura_config_no_orca_key_translation():
    """Post-ADR-008: OrcaSlicer key names are NOT translated to CuraEngine names."""
    overrides = {
        "wall_loops": 5,
        "sparse_infill_density": 30,
        "nozzle_temperature": 250,
    }
    result, _ = build_cura_config(overrides=overrides)
    assert result["wall_loops"] == 5
    assert result["sparse_infill_density"] == 30
    assert result["nozzle_temperature"] == 250
    assert "wall_line_count" not in result
    assert "infill_sparse_density" not in result
    assert "material_print_temperature" not in result


def test_build_cura_config_user_override_wins_over_seed():
    """User overrides take precedence over derived bed_type/filament_type seeds."""
    overrides = {"machine_buildplate_type": "custom"}
    result, _ = build_cura_config(
        overrides=overrides, bed_type="Engineering Plate", filament_type="PLA"
    )
    assert result["machine_buildplate_type"] == "custom"
    assert result["material_type"] == "PLA"


# --- _settings_flags ---


def test_settings_flags_empty_overrides_emits_baseline():
    """Empty overrides still emit the CuraEngine 5.12 quirk baseline."""
    flags = _settings_flags({})
    assert len(flags) % 2 == 0
    values = flags[1::2]
    value_dict = dict(v.split("=", 1) for v in values)
    assert value_dict["roofing_layer_count"] == "0"
    assert value_dict["flooring_layer_count"] == "0"
    assert value_dict["material_print_temp_prepend"] == "false"
    assert value_dict["material_bed_temp_prepend"] == "false"


def test_settings_flags_no_hardcoded_adhesion_type():
    """ADR-008: estampo no longer forces adhesion_type=none."""
    flags = _settings_flags({})
    values = flags[1::2]
    keys = {v.split("=", 1)[0] for v in values}
    assert "adhesion_type" not in keys


def test_settings_flags_no_manual_infill_line_distance():
    """ADR-008: CuraEngine computes infill_line_distance from density/width."""
    flags = _settings_flags({"infill_sparse_density": 25})
    values = flags[1::2]
    keys = {v.split("=", 1)[0] for v in values}
    assert "infill_line_distance" not in keys


def test_settings_flags_adhesion_type_brim_passes_through():
    """Regression (#586): user-set adhesion_type reaches the -s args."""
    flags = _settings_flags({"adhesion_type": "brim"})
    pairs = dict(v.split("=", 1) for v in flags[1::2])
    assert pairs["adhesion_type"] == "brim"


def test_settings_flags_no_machine_settings():
    """Machine settings (bed size, etc.) are NOT in flags — they come from the definition."""
    flags = _settings_flags({})
    values = flags[1::2]
    keys = {v.split("=", 1)[0] for v in values}
    assert "machine_width" not in keys
    assert "machine_depth" not in keys
    assert "machine_height" not in keys
    assert "machine_heated_bed" not in keys


def test_settings_flags_custom_overrides():
    """Overrides are appended to the flags."""
    flags = _settings_flags({"support_enable": "true", "retraction_amount": "0.8"})
    values = flags[1::2]
    value_dict = dict(v.split("=", 1) for v in values)
    assert value_dict["support_enable"] == "true"
    assert value_dict["retraction_amount"] == "0.8"


def test_settings_flags_preserves_numeric_types():
    """int/float overrides are stringified via normal __str__ — not stringified at build time."""
    flags = _settings_flags({"layer_height": 0.12, "wall_line_count": 5, "support_enable": True})
    pairs = dict(v.split("=", 1) for v in flags[1::2])
    assert pairs["layer_height"] == "0.12"
    assert pairs["wall_line_count"] == "5"
    assert pairs["support_enable"] == "True"


# --- validate_cura_settings ---


def test_validate_cura_settings_known_keys_no_warnings():
    """Valid CuraEngine keys produce no warnings."""
    overrides = {
        "layer_height": 0.12,
        "wall_line_count": 5,
        "infill_sparse_density": 30,
        "adhesion_type": "brim",
    }
    warnings = validate_cura_settings(overrides)
    assert warnings == []


def test_validate_cura_settings_orca_key_warns_with_suggestion():
    """OrcaSlicer key 'wall_loops' warns with a 'wall_line_count' suggestion."""
    warnings = validate_cura_settings({"wall_loops": 5})
    assert len(warnings) == 1
    assert "wall_loops" in warnings[0]
    assert "wall_line_count" in warnings[0]


def test_validate_cura_settings_unknown_key_warns():
    """Wholly unknown keys produce an 'invalid override' warning."""
    warnings = validate_cura_settings({"totally_made_up_setting": 1})
    assert len(warnings) == 1
    assert "totally_made_up_setting" in warnings[0]


def test_validate_cura_settings_empty_input_empty_output():
    """Empty overrides → no warnings."""
    assert validate_cura_settings({}) == []


# --- bundled definition files ---


def test_bundled_def_path_returns_path():
    """_bundled_def_path returns a Path inside data/."""
    from estampo.cura import _bundled_def_path

    path = _bundled_def_path("some_printer.def.json")
    assert path.name == "some_printer.def.json"
    assert "data" in str(path)


# --- _surface_cura_warnings (#590) ---


def test_surface_cura_warnings_flags_dropped_settings(caplog):
    """``has no [default_]value!`` warnings produce a strong dropped-settings log."""
    import logging

    stderr = (
        "[2026-04-19 06:00:00.000] [1] [tid] [warning] "
        "JSON setting 'machine_width' has no [default_]value!\n"
        "[2026-04-19 06:00:00.001] [1] [tid] [warning] "
        "JSON setting 'adhesion_type' has no [default_]value!\n"
    )
    with caplog.at_level(logging.WARNING, logger="estampo.cura"):
        _surface_cura_warnings(stderr)

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "silently dropped 2 printer-profile setting(s)" in text
    # Sorted & unique
    assert "adhesion_type, machine_width" in text
    assert "emitted 2 warning(s)" in text


def test_surface_cura_warnings_deduplicates_dropped_keys(caplog):
    """Repeated warnings for the same setting collapse to one dropped key."""
    import logging

    stderr = (
        "[warning] JSON setting 'machine_width' has no [default_]value!\n"
        "[warning] JSON setting 'machine_width' has no [default_]value!\n"
    )
    with caplog.at_level(logging.WARNING, logger="estampo.cura"):
        _surface_cura_warnings(stderr)

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "silently dropped 1 printer-profile setting(s)" in text
    assert "machine_width" in text


def test_surface_cura_warnings_generic_summary(caplog):
    """Non-dropped warnings still produce a generic count summary."""
    import logging

    stderr = "[warning] Unknown setting 'something_weird'\n[warning] Mesh has non-manifold edges\n"
    with caplog.at_level(logging.WARNING, logger="estampo.cura"):
        _surface_cura_warnings(stderr)

    text = "\n".join(r.getMessage() for r in caplog.records)
    # No dropped-setting message
    assert "silently dropped" not in text
    assert "emitted 2 warning(s)" in text


def test_surface_cura_warnings_silent_when_no_warnings(caplog):
    """Stderr with no ``[warning]`` lines produces no log output."""
    import logging

    stderr = "[info] Slicing started\nSome random license banner text\n"
    with caplog.at_level(logging.DEBUG, logger="estampo.cura"):
        _surface_cura_warnings(stderr)

    assert caplog.records == []


def test_surface_cura_warnings_debug_surfaces_each_line(caplog):
    """Every warning is logged at DEBUG so ``-v`` shows them inline."""
    import logging

    stderr = (
        "[warning] JSON setting 'machine_width' has no [default_]value!\n"
        "[warning] Something else weird\n"
    )
    with caplog.at_level(logging.DEBUG, logger="estampo.cura"):
        _surface_cura_warnings(stderr)

    debug_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("machine_width" in m for m in debug_msgs)
    assert any("Something else weird" in m for m in debug_msgs)


def test_machine_dims_flags_emits_s_flags():
    """All three bed dims are emitted as -s flags."""
    flags = _machine_dims_flags(
        {"machine_width": 256.0, "machine_depth": 200.0, "machine_height": 250.0}
    )
    assert flags == [
        "-s",
        "machine_width=256.0",
        "-s",
        "machine_depth=200.0",
        "-s",
        "machine_height=250.0",
    ]


def test_machine_dims_flags_skips_missing_keys():
    """Missing dim keys are omitted from the flag list."""
    flags = _machine_dims_flags({"machine_width": 256.0})
    assert flags == ["-s", "machine_width=256.0"]


# --- slice_stl Docker execution ---


def test_slice_stl_docker_command(tmp_path):
    """Verify Docker command is built correctly."""
    import json

    import trimesh

    mesh = trimesh.creation.box(extents=[10, 10, 10])
    stl = tmp_path / "model.stl"
    mesh.export(str(stl))
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # Create a fake gcode output file so the size check passes
    gcode_out = output_dir / "model.gcode"
    gcode_out.write_text("G28\n" * 100)

    # Create a minimal printer definition so _prepare_cura_staging resolves
    defs_dir = tmp_path / "profiles" / "cura" / "definitions"
    defs_dir.mkdir(parents=True)
    (defs_dir / "test_printer.def.json").write_text(
        json.dumps(
            {
                "name": "Test Printer",
                "inherits": "fdmprinter",
                "overrides": {
                    "machine_width": {"default_value": 256},
                    "machine_depth": {"default_value": 256},
                    "machine_height": {"default_value": 256},
                    "machine_start_gcode": {"default_value": "G28"},
                    "machine_end_gcode": {"default_value": "M84"},
                },
            }
        )
    )

    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("estampo.cura.subprocess.run", return_value=mock_result) as mock_run,
        patch("estampo.ui.status"),
    ):
        slice_stl(
            stl,
            output_dir,
            overrides={},
            image="estampo/estampo:cura-5.12.0",
            printer="test_printer",
            project_dir=tmp_path,
        )

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "docker"
    assert "run" in cmd
    assert "--entrypoint" in cmd
    assert "/bin/bash" in cmd
    assert "estampo/estampo:cura-5.12.0" in cmd
    assert "--platform" in cmd
    assert "linux/amd64" in cmd
    # Volume mount for output directory
    vol_idx = cmd.index("-v") + 1
    assert ":/work/output" in cmd[vol_idx]
    # Inner command uses the test definition
    inner_cmd = cmd[-1]
    assert "test_printer.def.json" in inner_cmd
    assert "-g -e0" in inner_cmd
    # #586: machine dims must be passed as -s flags so CuraEngine's bed size
    # agrees with _place_on_bed; otherwise brim/skirt is silently dropped.
    assert "machine_width=256" in inner_cmd
    assert "machine_depth=256" in inner_cmd


def test_slice_stl_docker_failure(tmp_path):
    """Docker failure raises EstampoError."""
    import trimesh

    mesh = trimesh.creation.box(extents=[10, 10, 10])
    stl = tmp_path / "model.stl"
    mesh.export(str(stl))
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    mock_result = MagicMock(returncode=1, stdout="", stderr="CuraEngine error")

    with (
        patch("estampo.cura.subprocess.run", return_value=mock_result),
        patch("estampo.ui.status"),
        pytest.raises(EstampoError, match="CuraEngine failed"),
    ):
        slice_stl(stl, output_dir, overrides={}, image="estampo/estampo:cura-5.12.0")


def test_slice_stl_no_output(tmp_path):
    """Success but empty/missing gcode file raises EstampoError."""
    import trimesh

    mesh = trimesh.creation.box(extents=[10, 10, 10])
    stl = tmp_path / "model.stl"
    mesh.export(str(stl))
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("estampo.cura.subprocess.run", return_value=mock_result),
        patch("estampo.ui.status"),
        pytest.raises(EstampoError, match="produced no output"),
    ):
        slice_stl(stl, output_dir, overrides={}, image="estampo/estampo:cura-5.12.0")


# --- slice_plate cura dispatch ---


def test_slice_plate_cura_dispatch(tmp_path):
    """slice_plate with engine='cura' dispatches to cura.slice_stl."""
    import trimesh

    from estampo.slicer import slice_plate

    # Create a valid 3MF from a simple mesh
    input_3mf = tmp_path / "plate.3mf"
    mesh = trimesh.creation.box(extents=[10, 10, 10])
    scene = trimesh.Scene(mesh)
    scene.export(str(input_3mf))

    output_dir = tmp_path / "output"

    with patch("estampo.cura.slice_stl", return_value=output_dir) as mock_slice:
        result = slice_plate(
            input_3mf,
            engine="cura",
            output_dir=output_dir,
            overrides={"layer_height": 0.12},
            bed_type="Textured PEI Plate",
            filaments=["PLA"],
            docker_version="5.12.0",
        )

    assert result == output_dir
    mock_slice.assert_called_once()
    call_kwargs = mock_slice.call_args.kwargs
    overrides_arg = call_kwargs["overrides"]
    assert overrides_arg["layer_height"] == 0.12
    assert overrides_arg["material_type"] == "PLA"
    assert call_kwargs["image"] == "estampo/estampo:cura-5.12.0"


# --- slice_stl_multi ---


def test_slice_stl_multi_docker_command(tmp_path):
    """slice_stl_multi builds one -g -eN -l group per mesh."""
    import trimesh

    stl_a = tmp_path / "part_0.stl"
    stl_b = tmp_path / "part_1.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(str(stl_a))
    trimesh.creation.box(extents=[5, 5, 5]).export(str(stl_b))

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "plate.gcode").write_text("G28\n" * 100)

    mock_result = MagicMock(returncode=0, stdout="", stderr="")
    with (
        patch("estampo.cura.subprocess.run", return_value=mock_result) as mock_run,
        patch("estampo.ui.status"),
    ):
        slice_stl_multi(
            [(0, stl_a), (1, stl_b)],
            output_dir,
            overrides={},
            image="estampo/estampo:cura-5.12.0",
        )

    inner_cmd = mock_run.call_args[0][0][-1]
    assert "-g -e0" in inner_cmd
    assert "-g -e1" in inner_cmd
    assert "part_0.stl" in inner_cmd
    assert "part_1.stl" in inner_cmd
    # Order must be preserved
    assert inner_cmd.index("-e0") < inner_cmd.index("-e1")


def test_slice_stl_multi_empty_raises(tmp_path):
    """slice_stl_multi with an empty list raises ValueError."""
    with pytest.raises(ValueError, match="must not be empty"):
        slice_stl_multi([], tmp_path / "output", overrides={})


def test_slice_plate_cura_multi_dispatch(tmp_path):
    """slice_plate with multi-filament ids dispatches to slice_stl_multi."""
    import trimesh

    from estampo.slicer import slice_plate

    # Two-geometry scene — separate box and sphere positioned apart
    mesh_a = trimesh.creation.box(extents=[10, 10, 10])
    mesh_b = trimesh.creation.box(extents=[5, 5, 5])
    mesh_b.vertices += [30, 0, 0]
    scene = trimesh.Scene()
    scene.add_geometry(mesh_a, geom_name="body")
    scene.add_geometry(mesh_b, geom_name="cap")
    input_3mf = tmp_path / "plate.3mf"
    scene.export(str(input_3mf))

    output_dir = tmp_path / "output"

    with (
        patch("estampo.cura.slice_stl_multi", return_value=output_dir) as mock_multi,
        patch("estampo.cura.slice_stl") as mock_single,
    ):
        result = slice_plate(
            input_3mf,
            engine="cura",
            output_dir=output_dir,
            filament_ids=[1, 2],
            docker_version="5.12.0",
        )

    assert result == output_dir
    mock_multi.assert_called_once()
    mock_single.assert_not_called()

    # Verify extruder indices are 0-based (filament_ids [1,2] → extruders [0,1])
    stl_meshes_arg = mock_multi.call_args[0][0]
    assert [ext for ext, _ in stl_meshes_arg] == [0, 1]


# --- per-extruder profiles (Stage 2) ---


def test_extruder_settings_str_no_per_extruder():
    """Without per_extruder data, _extruder_settings_str returns global settings."""
    overrides = {"material_print_temperature": 230}
    s = _extruder_settings_str(overrides, [], 0)
    assert "material_print_temperature=230" in s
    # Same for extruder 1 (no per_extruder entry)
    assert _extruder_settings_str(overrides, [], 1) == s


def test_extruder_settings_str_with_per_extruder():
    """Per-extruder overrides are appended after the global settings."""
    overrides = {"material_print_temperature": 260}
    per_extruder = [
        {"material_print_temperature": 220, "material_type": "PLA"},
        {"material_print_temperature": 240, "material_type": "PETG"},
    ]
    s0 = _extruder_settings_str(overrides, per_extruder, 0)
    s1 = _extruder_settings_str(overrides, per_extruder, 1)

    assert "material_print_temperature=220" in s0
    assert "material_type=PLA" in s0
    assert "material_print_temperature=240" in s1
    assert "material_type=PETG" in s1

    # Per-extruder value comes AFTER the global one (CuraEngine uses last wins)
    assert s0.index("material_print_temperature=220") > s0.index("material_print_temperature=260")


def test_build_cura_config_per_extruder_from_filaments():
    """build_cura_config populates per_extruder from the filaments list."""
    _, per_extruder = build_cura_config(filaments=["PLA", "PETG-CF"])

    assert len(per_extruder) == 2
    assert per_extruder[0]["material_type"] == "PLA"
    assert per_extruder[1]["material_type"] == "PETG-CF"
    assert per_extruder[0]["material_print_temperature"] == _FILAMENT_TEMPS["PLA"][0]
    assert per_extruder[1]["material_print_temperature"] == _FILAMENT_TEMPS["PETG-CF"][0]


def test_build_cura_config_unknown_filament_no_temps():
    """Unknown filament type gets material_type only — no temperature guess."""
    _, per_extruder = build_cura_config(filaments=["SuperCustom"])
    assert per_extruder[0]["material_type"] == "SuperCustom"
    assert "material_print_temperature" not in per_extruder[0]


def test_slice_stl_multi_per_extruder_in_command(tmp_path):
    """slice_stl_multi emits per-extruder -s overrides in each -g block."""
    import trimesh

    stl_a = tmp_path / "part_0.stl"
    stl_b = tmp_path / "part_1.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(str(stl_a))
    trimesh.creation.box(extents=[5, 5, 5]).export(str(stl_b))

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "plate.gcode").write_text("G28\n" * 100)

    per_extruder = [
        {"material_type": "PLA", "material_print_temperature": 220},
        {"material_type": "PETG-CF", "material_print_temperature": 260},
    ]
    mock_result = MagicMock(returncode=0, stdout="", stderr="")
    with (
        patch("estampo.cura.subprocess.run", return_value=mock_result) as mock_run,
        patch("estampo.ui.status"),
    ):
        slice_stl_multi(
            [(0, stl_a), (1, stl_b)],
            output_dir,
            overrides={},
            per_extruder=per_extruder,
            image="estampo/estampo:cura-5.12.0",
        )

    inner_cmd = mock_run.call_args[0][0][-1]
    # Extruder 0 block must contain PLA overrides
    e0_start = inner_cmd.index("-g -e0")
    e1_start = inner_cmd.index("-g -e1")
    e0_block = inner_cmd[e0_start:e1_start]
    e1_block = inner_cmd[e1_start:]
    assert "material_type=PLA" in e0_block
    assert "material_print_temperature=220" in e0_block
    assert "material_type=PETG-CF" in e1_block
    assert "material_print_temperature=260" in e1_block


def test_slice_plate_cura_single_filament_uses_slice_stl(tmp_path):
    """slice_plate with a single filament slot falls back to slice_stl."""
    import trimesh

    from estampo.slicer import slice_plate

    input_3mf = tmp_path / "plate.3mf"
    scene = trimesh.Scene(trimesh.creation.box(extents=[10, 10, 10]))
    scene.export(str(input_3mf))

    output_dir = tmp_path / "output"

    with (
        patch("estampo.cura.slice_stl", return_value=output_dir) as mock_single,
        patch("estampo.cura.slice_stl_multi") as mock_multi,
    ):
        slice_plate(
            input_3mf,
            engine="cura",
            output_dir=output_dir,
            filament_ids=[1, 1],  # same slot — should not use multi path
            docker_version="5.12.0",
        )

    mock_single.assert_called_once()
    mock_multi.assert_not_called()


# --- _patch_gcode_header ---


def test_patch_gcode_header_replaces_placeholder(tmp_path):
    """Placeholder header (TIME:6666, 0m) is replaced with real values from stderr."""
    gcode = tmp_path / "test.gcode"
    gcode.write_text(
        ";FLAVOR:Marlin\n"
        ";TIME:6666\n"
        ";Filament used: 0m\n"
        ";Layer height: 0.2\n"
        ";MINX:2.14748e+06\n;MINY:2.14748e+06\n;MINZ:2.14748e+06\n"
        ";MAXX:-2.14748e+06\n;MAXY:-2.14748e+06\n;MAXZ:-2.14748e+06\n"
        ";TARGET_MACHINE.NAME:Unknown\n"
        "\n;Generated with Cura_SteamEngine 5.12.0\nG28\n"
    )
    stderr = (
        "[info] Gcode header after slicing: ;FLAVOR:Marlin\n"
        ";TIME:1519\n"
        ";Filament used: 0.714216m\n"
        ";Layer height: 0.2\n"
        ";MINX:128.2\n;MINY:128.2\n;MINZ:0.3\n"
        ";MAXX:147.8\n;MAXY:147.8\n;MAXZ:19.9\n"
        ";TARGET_MACHINE.NAME:Unknown\n"
    )
    _patch_gcode_header(gcode, stderr)
    text = gcode.read_text()
    assert ";TIME:1519" in text
    assert ";Filament used: 0.714216m" in text
    assert ";MINX:128.2" in text
    assert ";TIME:6666" not in text
    assert ";Filament used: 0m" not in text


def test_patch_gcode_header_no_match(tmp_path):
    """If stderr doesn't contain the expected header, file is unchanged."""
    gcode = tmp_path / "test.gcode"
    original = ";FLAVOR:Marlin\n;TIME:6666\n;Filament used: 0m\n;TARGET_MACHINE.NAME:X\nG28\n"
    gcode.write_text(original)
    _patch_gcode_header(gcode, "some random stderr output")
    assert gcode.read_text() == original


# --- _place_on_bed ---


def test_place_on_bed_shifts_negative_z(tmp_path):
    """Mesh centered at origin (Z from -5 to +5) is shifted to Z≥0."""
    import trimesh

    mesh = trimesh.creation.box(extents=[10, 10, 10])
    assert mesh.bounds[0][2] == pytest.approx(-5.0)

    stl = tmp_path / "centered.stl"
    mesh.export(str(stl))

    staging = tmp_path / "staging"
    staging.mkdir()
    result = _place_on_bed(stl, staging)

    placed = trimesh.load(str(result), force="mesh")
    assert placed.bounds[0][2] == pytest.approx(0.0)
    assert placed.bounds[1][2] == pytest.approx(10.0)


def test_place_on_bed_already_on_bed(tmp_path):
    """Mesh already on the bed (Z≥0) is not shifted."""
    import trimesh

    mesh = trimesh.creation.box(extents=[10, 10, 10])
    mesh.vertices[:, 2] += 5  # shift so Z goes from 0 to 10

    stl = tmp_path / "on_bed.stl"
    mesh.export(str(stl))

    staging = tmp_path / "staging"
    staging.mkdir()
    result = _place_on_bed(stl, staging)

    placed = trimesh.load(str(result), force="mesh")
    assert placed.bounds[0][2] == pytest.approx(0.0)
    assert placed.bounds[1][2] == pytest.approx(10.0)


def test_place_on_bed_corner_origin_centers_on_bed(tmp_path):
    """center_is_zero=False → mesh centered at (bed_width/2, bed_depth/2)."""
    import trimesh

    mesh = trimesh.creation.box(extents=[10, 10, 10])  # centered at origin
    stl = tmp_path / "part.stl"
    mesh.export(str(stl))

    staging = tmp_path / "staging"
    staging.mkdir()
    result = _place_on_bed(stl, staging, bed_width=200, bed_depth=200, center_is_zero=False)

    placed = trimesh.load(str(result), force="mesh")
    assert ((placed.bounds[0][0] + placed.bounds[1][0]) / 2) == pytest.approx(100.0)
    assert ((placed.bounds[0][1] + placed.bounds[1][1]) / 2) == pytest.approx(100.0)


def test_place_on_bed_center_origin_keeps_mesh_at_zero(tmp_path):
    """center_is_zero=True → mesh centered at (0, 0)."""
    import trimesh

    mesh = trimesh.creation.box(extents=[10, 10, 10])
    mesh.vertices[:, 0] += 50  # shift off-center so we can verify re-centering
    mesh.vertices[:, 1] += 30

    stl = tmp_path / "part.stl"
    mesh.export(str(stl))

    staging = tmp_path / "staging"
    staging.mkdir()
    result = _place_on_bed(stl, staging, bed_width=200, bed_depth=200, center_is_zero=True)

    placed = trimesh.load(str(result), force="mesh")
    assert ((placed.bounds[0][0] + placed.bounds[1][0]) / 2) == pytest.approx(0.0)
    assert ((placed.bounds[0][1] + placed.bounds[1][1]) / 2) == pytest.approx(0.0)


# --- resolve_cura_center_is_zero ---


def test_resolve_center_is_zero_true_from_def(tmp_path):
    """Reads machine_center_is_zero=True from the def chain."""
    import json

    defs = tmp_path / "profiles" / "cura" / "definitions"
    defs.mkdir(parents=True)
    (defs / "delta.def.json").write_text(
        json.dumps({"overrides": {"machine_center_is_zero": {"default_value": True}}})
    )

    assert resolve_cura_center_is_zero("delta", project_dir=tmp_path) is True


def test_resolve_center_is_zero_false_default(tmp_path):
    """Missing setting defaults to False (CuraEngine's default)."""
    import json

    defs = tmp_path / "profiles" / "cura" / "definitions"
    defs.mkdir(parents=True)
    (defs / "cartesian.def.json").write_text(json.dumps({"overrides": {}}))

    assert resolve_cura_center_is_zero("cartesian", project_dir=tmp_path) is False


# --- _write_cura_settings / _settings_dict ---


def test_settings_dict_overrides_passthrough():
    """_settings_dict passes user overrides through verbatim, on top of the baseline."""
    overrides = {
        "machine_nozzle_size": 0.4,
        "machine_buildplate_type": "textured_pei_plate",
        "material_type": "PLA",
        "material_print_temperature_layer_0": 260,
        "material_bed_temperature_layer_0": 70,
    }
    d = _settings_dict(overrides)
    assert d["machine_nozzle_size"] == 0.4
    assert d["machine_buildplate_type"] == "textured_pei_plate"
    assert d["material_type"] == "PLA"
    assert d["material_print_temperature_layer_0"] == 260
    assert d["material_bed_temperature_layer_0"] == 70
    # Baseline preserved alongside user overrides
    assert d["roofing_layer_count"] == 0


def test_write_cura_settings(tmp_path):
    """_write_cura_settings writes valid JSON with all overrides plus baseline."""
    import json

    overrides = {
        "material_print_temperature": 260,
        "material_bed_temperature_layer_0": 70,
        "material_type": "PETG",
        "machine_buildplate_type": "textured_pei_plate",
    }
    path = _write_cura_settings(tmp_path, overrides)
    assert path == tmp_path / "cura_settings.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["material_print_temperature"] == 260
    assert data["material_bed_temperature_layer_0"] == 70
    assert data["material_type"] == "PETG"
    assert data["machine_buildplate_type"] == "textured_pei_plate"


def test_write_cura_settings_includes_overrides(tmp_path):
    """User overrides are included in the settings JSON."""
    import json

    overrides = {"infill_pattern": "gyroid", "wall_line_count": 4}
    path = _write_cura_settings(tmp_path, overrides)
    data = json.loads(path.read_text())
    assert data["infill_pattern"] == "gyroid"
    assert data["wall_line_count"] == 4


def test_write_cura_settings_includes_machine_dims(tmp_path):
    """Machine dimensions are included in the settings JSON for template resolution."""
    import json

    dims = {"machine_width": 256.0, "machine_depth": 256.0, "machine_height": 250.0}
    path = _write_cura_settings(tmp_path, {}, machine_dims=dims)
    data = json.loads(path.read_text())
    assert data["machine_width"] == 256.0
    assert data["machine_depth"] == 256.0
    assert data["machine_height"] == 250.0


# --- resolve_cura_machine_dims ---


def test_resolve_machine_dims_from_definition(tmp_path):
    """Machine dimensions are extracted from the printer definition chain."""
    import json

    defs_dir = tmp_path / "profiles" / "cura" / "definitions"
    defs_dir.mkdir(parents=True)
    (defs_dir / "test_printer.def.json").write_text(
        json.dumps(
            {
                "name": "Test Printer",
                "inherits": "fdmprinter",
                "overrides": {
                    "machine_width": {"value": 300},
                    "machine_depth": {"value": 300},
                    "machine_height": {"value": 400},
                },
            }
        )
    )
    dims = resolve_cura_machine_dims("test_printer", project_dir=tmp_path)
    assert dims["machine_width"] == 300.0
    assert dims["machine_depth"] == 300.0
    assert dims["machine_height"] == 400.0


# --- _fetch_printer_def (URL / file path) ---


def test_fetch_printer_def_returns_none_for_plain_name(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    result = _fetch_printer_def("bambox_p1s", project_dir=None, staging=staging)
    assert result is None


def test_fetch_printer_def_copies_local_file(tmp_path):
    # Create a fake .def.json file
    def_file = tmp_path / "my_printer.def.json"
    def_file.write_text('{"version": 1}')
    staging = tmp_path / "staging"
    staging.mkdir()

    result = _fetch_printer_def(str(def_file), project_dir=None, staging=staging)

    assert result == "my_printer.def.json"
    assert (staging / "my_printer.def.json").exists()


def test_fetch_printer_def_resolves_relative_to_project_dir(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    def_file = project_dir / "my_printer.def.json"
    def_file.write_text('{"version": 1}')
    staging = tmp_path / "staging"
    staging.mkdir()

    result = _fetch_printer_def("my_printer.def.json", project_dir=project_dir, staging=staging)

    assert result == "my_printer.def.json"
    assert (staging / "my_printer.def.json").exists()


def test_fetch_printer_def_url_downloads_file(tmp_path):
    import urllib.request

    staging = tmp_path / "staging"
    staging.mkdir()
    fake_content = b'{"version": 1}'

    with patch.object(urllib.request, "urlretrieve") as mock_dl:

        def _fake_retrieve(url, dest):
            dest.write_bytes(fake_content)

        mock_dl.side_effect = _fake_retrieve
        result = _fetch_printer_def(
            "https://example.com/my_printer.def.json",
            project_dir=None,
            staging=staging,
        )

    assert result == "my_printer.def.json"
    assert (staging / "my_printer.def.json").read_bytes() == fake_content


def test_fetch_printer_def_url_adds_def_json_suffix(tmp_path):
    import urllib.request

    staging = tmp_path / "staging"
    staging.mkdir()

    with patch.object(urllib.request, "urlretrieve") as mock_dl:

        def _fake_retrieve(url, dest):
            dest.write_bytes(b"{}")

        mock_dl.side_effect = _fake_retrieve
        result = _fetch_printer_def(
            "https://example.com/my_printer",
            project_dir=None,
            staging=staging,
        )

    assert result == "my_printer.def.json"

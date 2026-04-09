"""Tests for CuraEngine slicer backend."""

from unittest.mock import MagicMock, patch

import pytest

from estampo import EstampoError
from estampo.cura import (
    CuraProfile,
    _patch_gcode_header,
    _place_on_bed,
    _resolve_def_name,
    _safe_eval_arithmetic,
    _safe_eval_condition,
    _settings_flags,
    _substitute_gcode_templates,
    cura_docker_image,
    cura_profile_from_config,
    slice_stl,
    slice_stl_multi,
)

# --- _resolve_def_name ---


def test_resolve_def_name_exact_match():
    """Exact manifest name maps to definition ID."""
    assert _resolve_def_name("BambuLab P1S") == "bambulab_p1s"


def test_resolve_def_name_none_returns_default():
    """None falls back to bambulab_p1s."""
    assert _resolve_def_name(None) == "bambulab_p1s"


def test_resolve_def_name_already_id():
    """If the name is already a definition ID, return it as-is."""
    assert _resolve_def_name("bambulab_p1s") == "bambulab_p1s"


def test_resolve_def_name_case_insensitive():
    """Case-insensitive matching against manifest names."""
    assert _resolve_def_name("bambulab p1s") == "bambulab_p1s"


def test_resolve_def_name_strips_nozzle_suffix():
    """Machine profile names with nozzle suffix resolve correctly."""
    assert _resolve_def_name("BambuLab P1S 0.4 nozzle") == "bambulab_p1s"


def test_resolve_def_name_strips_nozzle_mm_suffix():
    """Nozzle suffix with mm unit resolves correctly."""
    assert _resolve_def_name("BambuLab P1S 0.6mm nozzle") == "bambulab_p1s"


def test_resolve_def_name_unknown_raises():
    """Unknown printer name raises EstampoError."""
    with pytest.raises(EstampoError, match="not found in the definition manifest"):
        _resolve_def_name("Totally Unknown Printer XYZ")


# --- cura_docker_image ---


def test_cura_docker_image_default():
    assert cura_docker_image() == "estampo/estampo:cura-5.12.0"


def test_cura_docker_image_versioned():
    assert cura_docker_image("5.12.0") == "estampo/estampo:cura-5.12.0"


def test_cura_docker_image_custom_version():
    assert cura_docker_image("5.13.0") == "estampo/estampo:cura-5.13.0"


# --- CuraProfile defaults ---


def test_cura_profile_defaults():
    profile = CuraProfile()
    assert profile.nozzle_diameter == 0.4
    assert profile.material_print_temperature == 260
    assert profile.material_bed_temperature == 70
    assert profile.layer_height == 0.20
    assert profile.wall_line_count == 3
    assert profile.infill_sparse_density == 25
    assert profile.bed_type == "Textured PEI Plate"
    assert profile.filament_type == "PETG-CF"
    assert profile.overrides == {}


# --- cura_profile_from_config ---


def test_profile_from_config_bed_type():
    profile = cura_profile_from_config(bed_type="Engineering Plate")
    assert profile.bed_type == "Engineering Plate"


def test_profile_from_config_filament_type():
    profile = cura_profile_from_config(filament_type="PLA")
    assert profile.filament_type == "PLA"


def test_profile_from_config_orca_overrides():
    """OrcaSlicer-style override keys are mapped to CuraProfile fields."""
    overrides = {
        "layer_height": 0.12,
        "wall_loops": 5,
        "sparse_infill_density": 30,
        "top_shell_layers": 7,
        "bottom_shell_layers": 6,
        "initial_layer_print_height": 0.28,
        "nozzle_temperature": 250,
        "bed_temperature": 65,
    }
    profile = cura_profile_from_config(overrides=overrides)
    assert profile.layer_height == 0.12
    assert profile.wall_line_count == 5
    assert profile.infill_sparse_density == 30
    assert profile.top_layers == 7
    assert profile.bottom_layers == 6
    assert profile.layer_height_0 == 0.28
    assert profile.material_print_temperature == 250
    assert profile.material_bed_temperature == 65
    # No passthrough overrides — all keys were mapped
    assert profile.overrides == {}


def test_profile_from_config_passthrough_overrides():
    """Unknown keys are passed through as raw CuraEngine -s overrides."""
    overrides = {
        "retraction_amount": "0.8",
        "support_enable": "true",
    }
    profile = cura_profile_from_config(overrides=overrides)
    assert profile.overrides == {"retraction_amount": "0.8", "support_enable": "true"}


def test_profile_from_config_native_cura_keys():
    """Native CuraEngine key names set CuraProfile attributes directly."""
    overrides = {
        "infill_sparse_density": 30,
        "wall_line_count": 5,
        "material_print_temperature": 250,
        "layer_height_0": 0.28,
    }
    profile = cura_profile_from_config(overrides=overrides)
    assert profile.infill_sparse_density == 30
    assert profile.wall_line_count == 5
    assert profile.material_print_temperature == 250
    assert profile.layer_height_0 == 0.28
    # All mapped to attributes — no passthrough overrides
    assert profile.overrides == {}


# --- _settings_flags ---


def test_settings_flags_defaults():
    """Default profile produces expected flags."""
    profile = CuraProfile()
    flags = _settings_flags(profile)
    # Flags are -s key=value pairs
    assert len(flags) % 2 == 0
    # Convert to dict for easy inspection
    values = flags[1::2]
    value_dict = {}
    for v in values:
        k, val = v.split("=", 1)
        value_dict[k] = val
    assert value_dict["layer_height"] == "0.2"
    assert value_dict["material_print_temperature"] == "260"
    assert value_dict["material_bed_temperature"] == "70"
    assert value_dict["wall_line_count"] == "3"


def test_settings_flags_includes_required():
    """Flags include CuraEngine 5.12-specific required settings."""
    profile = CuraProfile()
    flags = _settings_flags(profile)
    values = flags[1::2]
    value_dict = {}
    for v in values:
        k, val = v.split("=", 1)
        value_dict[k] = val
    assert value_dict["roofing_layer_count"] == "0"
    assert value_dict["flooring_layer_count"] == "0"
    assert value_dict["material_print_temp_prepend"] == "false"
    assert value_dict["material_bed_temp_prepend"] == "false"


def test_settings_flags_no_machine_settings():
    """Machine settings (bed size, etc.) are NOT in flags — they come from the definition."""
    profile = CuraProfile()
    flags = _settings_flags(profile)
    values = flags[1::2]
    keys = {v.split("=", 1)[0] for v in values}
    assert "machine_width" not in keys
    assert "machine_depth" not in keys
    assert "machine_height" not in keys
    assert "machine_heated_bed" not in keys


def test_settings_flags_custom_overrides():
    """Profile overrides are appended to the flags."""
    profile = CuraProfile(overrides={"support_enable": "true", "retraction_amount": "0.8"})
    flags = _settings_flags(profile)
    values = flags[1::2]
    value_dict = {}
    for v in values:
        k, val = v.split("=", 1)
        value_dict[k] = val
    assert value_dict["support_enable"] == "true"
    assert value_dict["retraction_amount"] == "0.8"


# --- bundled definition files ---


def test_bundled_definitions_exist():
    """BBL definition files are bundled with the package."""
    from estampo.cura import _bundled_def_path, _resolve_def_chain

    # P1S definition and its base must exist
    for def_name in ("bambulab_p1s.def.json", "bambulab_base.def.json"):
        path = _bundled_def_path(def_name)
        assert path.exists(), f"Missing bundled definition: {def_name}"

    import json

    p1s = json.loads(_bundled_def_path("bambulab_p1s.def.json").read_text())
    assert p1s["name"] == "BambuLab P1S"
    assert p1s["inherits"] == "bambulab_base"
    assert "machine_start_gcode" in p1s["overrides"]
    assert "machine_end_gcode" in p1s["overrides"]

    # Definition chain should resolve both files
    chain = _resolve_def_chain("bambulab_p1s")
    assert len(chain) >= 2
    assert chain[0].name == "bambulab_p1s.def.json"
    assert chain[1].name == "bambulab_base.def.json"


# --- slice_stl Docker execution ---


def test_slice_stl_docker_command(tmp_path):
    """Verify Docker command is built correctly."""
    import trimesh

    mesh = trimesh.creation.box(extents=[10, 10, 10])
    stl = tmp_path / "model.stl"
    mesh.export(str(stl))
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # Create a fake gcode output file so the size check passes
    gcode_out = output_dir / "model.gcode"
    gcode_out.write_text("G28\n" * 100)

    profile = CuraProfile()
    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("estampo.cura.subprocess.run", return_value=mock_result) as mock_run,
        patch("estampo.ui.status"),
    ):
        slice_stl(stl, output_dir, profile, image="estampo/estampo:cura-5.12.0")

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
    # Inner command uses P1S definition
    inner_cmd = cmd[-1]
    assert "bambulab_p1s.def.json" in inner_cmd
    assert "-g -e0" in inner_cmd


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
        slice_stl(stl, output_dir, CuraProfile(), image="estampo/estampo:cura-5.12.0")


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
        slice_stl(stl, output_dir, CuraProfile(), image="estampo/estampo:cura-5.12.0")


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
    call_kwargs = mock_slice.call_args
    # Verify the profile was built with the right settings
    profile = call_kwargs[0][2] if len(call_kwargs[0]) > 2 else call_kwargs[1].get("profile")
    if profile is None:
        profile = call_kwargs.args[2]
    assert profile.layer_height == 0.12
    assert profile.filament_type == "PLA"
    assert "estampo/estampo:cura-5.12.0" in str(call_kwargs)


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
            CuraProfile(),
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
        slice_stl_multi([], tmp_path / "output", CuraProfile())


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


# --- _substitute_gcode_templates ---


def test_substitute_simple_variables(tmp_path):
    """Simple {variable} placeholders are replaced with profile values."""
    gcode = tmp_path / "test.gcode"
    gcode.write_text(
        "M140 S{material_bed_temperature_layer_0}\n"
        "M190 S{material_bed_temperature_layer_0}\n"
        "M104 S{material_print_temperature_layer_0}\n"
        "M109 S{material_print_temperature_layer_0}\n"
        "G1 X0 Y0\n"
    )
    profile = CuraProfile(material_print_temperature=260, material_bed_temperature=70)
    _substitute_gcode_templates(gcode, profile)
    text = gcode.read_text()
    assert "M140 S70" in text
    assert "M190 S70" in text
    assert "M104 S260" in text
    assert "M109 S260" in text
    assert "{material_" not in text


def test_substitute_expression(tmp_path):
    """Expressions like {temp - 20} are evaluated."""
    gcode = tmp_path / "test.gcode"
    gcode.write_text("M109 S{material_print_temperature_layer_0 - 20}\n")
    profile = CuraProfile(material_print_temperature=260)
    _substitute_gcode_templates(gcode, profile)
    text = gcode.read_text()
    assert "M109 S240" in text


def test_substitute_conditional(tmp_path):
    """Conditionals like {if condition}...{endif} are evaluated."""
    gcode = tmp_path / "test.gcode"
    gcode.write_text(
        "G28\n"
        "{if machine_buildplate_type=='textured_pei_plate'}"
        "M1002 set_flag bed_type textured\n"
        "{endif}"
        "G29\n"
    )
    profile = CuraProfile(bed_type="Textured PEI Plate")
    _substitute_gcode_templates(gcode, profile)
    text = gcode.read_text()
    assert "M1002 set_flag bed_type textured" in text
    assert "{if" not in text
    assert "{endif}" not in text


def test_substitute_machine_and_material_type(tmp_path):
    """Machine and material type placeholders are replaced."""
    gcode = tmp_path / "test.gcode"
    gcode.write_text(
        "; BAMBOX_NOZZLE_DIAMETER={machine_nozzle_size}\n"
        "; BAMBOX_BED_TYPE={machine_buildplate_type}\n"
        "; BAMBOX_FILAMENT_TYPE={material_type}\n"
    )
    profile = CuraProfile(
        nozzle_diameter=0.4,
        bed_type="Textured PEI Plate",
        filament_type="PLA",
    )
    _substitute_gcode_templates(gcode, profile)
    text = gcode.read_text()
    assert "; BAMBOX_NOZZLE_DIAMETER=0.4" in text
    assert "; BAMBOX_BED_TYPE=textured_pei_plate" in text
    assert "; BAMBOX_FILAMENT_TYPE=PLA" in text
    assert "{machine_" not in text
    assert "{material_type}" not in text


def test_substitute_no_change(tmp_path):
    """G-code without template variables is unchanged."""
    gcode = tmp_path / "test.gcode"
    original = "G28\nG1 X0 Y0 Z0.2\nG1 E5 F300\n"
    gcode.write_text(original)
    profile = CuraProfile()
    _substitute_gcode_templates(gcode, profile)
    assert gcode.read_text() == original


# --- _safe_eval_arithmetic ---


def test_safe_eval_arithmetic_basic():
    assert _safe_eval_arithmetic("260 - 20") == 240.0
    assert _safe_eval_arithmetic("100 + 50") == 150.0
    assert _safe_eval_arithmetic("10 * 3") == 30.0
    assert _safe_eval_arithmetic("100 / 4") == 25.0


def test_safe_eval_arithmetic_negative():
    assert _safe_eval_arithmetic("-5") == -5.0


def test_safe_eval_arithmetic_rejects_function_calls():
    with pytest.raises(ValueError, match="Unsupported"):
        _safe_eval_arithmetic("__import__('os').system('rm -rf /')")


def test_safe_eval_arithmetic_rejects_names():
    with pytest.raises(ValueError, match="Unsupported"):
        _safe_eval_arithmetic("x + 1")


# --- _safe_eval_condition ---


def test_safe_eval_condition_string_eq():
    assert _safe_eval_condition("'foo' == 'foo'") is True
    assert _safe_eval_condition("'foo' == 'bar'") is False


def test_safe_eval_condition_string_neq():
    assert _safe_eval_condition("'foo' != 'bar'") is True
    assert _safe_eval_condition("'foo' != 'foo'") is False


def test_safe_eval_condition_rejects_function_calls():
    with pytest.raises(ValueError):
        _safe_eval_condition("__import__('os').system('id') == ''")

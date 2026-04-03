"""Tests for CuraEngine slicer backend."""

from unittest.mock import MagicMock, patch

import pytest

from estampo import EstampoError
from estampo.cura import (
    CuraProfile,
    _render_bbl_gcode,
    _settings_flags,
    cura_docker_image,
    cura_profile_from_config,
    slice_stl,
)

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
    assert profile.machine_width == 256.0
    assert profile.machine_depth == 256.0
    assert profile.machine_height == 256.0
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


# --- _settings_flags ---


def test_settings_flags_defaults():
    """Default profile produces expected flags."""
    profile = CuraProfile()
    flags = _settings_flags(profile)
    # Flags are -s key=value pairs
    assert len(flags) % 2 == 0
    # Convert to dict for easy inspection
    pairs = dict(zip(flags[0::2], flags[1::2]))
    assert all(k == "-s" for k in pairs)
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
    assert value_dict["adhesion_type"] == "none"


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


# --- _render_bbl_gcode ---


def test_render_bbl_gcode_contains_temps():
    """Rendered gcode contains M190 (bed) and M109 (nozzle) temperature commands."""
    profile = CuraProfile(material_bed_temperature=65, material_print_temperature=245)

    # bambu_3mf may not be installed in the test environment — mock the import.
    def fake_render(template_name, context):
        if "start" in template_name:
            bed = context["bed_temperature_initial_layer_single"]
            nozzle = context["nozzle_temperature_initial_layer"][0]
            return f"M190 S{bed}\nM109 S{nozzle}\nG28\n"
        return "M400\nM104 S0\n"

    mock_templates = MagicMock()
    mock_templates.render_template.side_effect = fake_render

    with patch.dict(
        "sys.modules",
        {
            "bambu_3mf": MagicMock(),
            "bambu_3mf.templates": mock_templates,
        },
    ):
        start, end = _render_bbl_gcode(profile)

    assert "M190 S65" in start
    assert "M109 S245" in start


def test_render_bbl_gcode_contains_bed_type():
    """Rendered gcode contains the bed type string."""
    profile = CuraProfile(bed_type="Engineering Plate")

    def fake_render(template_name, context):
        if "start" in template_name:
            return f"; bed_type={context['curr_bed_type']}\nG28\n"
        return "M400\n"

    mock_templates = MagicMock()
    mock_templates.render_template.side_effect = fake_render

    with patch.dict(
        "sys.modules",
        {
            "bambu_3mf": MagicMock(),
            "bambu_3mf.templates": mock_templates,
        },
    ):
        start, _end = _render_bbl_gcode(profile)

    assert "Engineering Plate" in start


# --- slice_stl Docker execution ---


def test_slice_stl_docker_command(tmp_path):
    """Verify Docker command is built correctly."""
    stl = tmp_path / "model.stl"
    stl.write_text("solid cube")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # Create a fake gcode output file so the size check passes
    gcode_out = output_dir / "model.gcode"
    gcode_out.write_text("G28\n" * 100)

    profile = CuraProfile()
    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("estampo.cura.subprocess.run", return_value=mock_result) as mock_run,
        patch("estampo.cura._render_bbl_gcode", return_value=("START", "END")),
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


def test_slice_stl_docker_failure(tmp_path):
    """Docker failure raises EstampoError."""
    stl = tmp_path / "model.stl"
    stl.write_text("solid cube")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    mock_result = MagicMock(returncode=1, stdout="", stderr="CuraEngine error")

    with (
        patch("estampo.cura.subprocess.run", return_value=mock_result),
        patch("estampo.cura._render_bbl_gcode", return_value=("START", "END")),
        patch("estampo.ui.status"),
        pytest.raises(EstampoError, match="CuraEngine failed"),
    ):
        slice_stl(stl, output_dir, CuraProfile(), image="estampo/estampo:cura-5.12.0")


def test_slice_stl_no_output(tmp_path):
    """Success but empty/missing gcode file raises EstampoError."""
    stl = tmp_path / "model.stl"
    stl.write_text("solid cube")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("estampo.cura.subprocess.run", return_value=mock_result),
        patch("estampo.cura._render_bbl_gcode", return_value=("START", "END")),
        patch("estampo.ui.status"),
        pytest.raises(EstampoError, match="produced no output"),
    ):
        slice_stl(stl, output_dir, CuraProfile(), image="estampo/estampo:cura-5.12.0")


# --- slice_plate cura dispatch ---


def test_slice_plate_cura_dispatch(tmp_path):
    """slice_plate with engine='cura' dispatches to cura.slice_stl."""
    import zipfile

    from estampo.slicer import slice_plate

    # Create a minimal 3MF (zip) with an STL inside
    input_3mf = tmp_path / "plate.3mf"
    stl_content = b"solid cube\nendsolid cube"
    with zipfile.ZipFile(input_3mf, "w") as zf:
        zf.writestr("3D/model.stl", stl_content)

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

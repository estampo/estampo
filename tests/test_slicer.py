"""Tests for slicer module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from estampo import EstampoError
from estampo.slicer import (
    SLICER_PATHS,
    _apply_overrides,
    _has_docker_image,
    _resolve_profiles,
    _slice_via_docker,
    docker_image,
    find_slicer,
    parse_gcode_stats,
    slice_plate,
)

# --- find_slicer ---


def test_find_orca():
    if not SLICER_PATHS["orca"].exists():
        pytest.skip("OrcaSlicer not installed")
    assert find_slicer("orca") == SLICER_PATHS["orca"]


def test_find_unknown():
    with pytest.raises(ValueError, match="Unknown slicer"):
        find_slicer("cura")


def test_find_slicer_path_fallback():
    """Falls back to shutil.which when default path doesn't exist."""
    with patch.dict("estampo.slicer.SLICER_PATHS", {"orca": Path("/nonexistent/orca")}):
        with patch("estampo.slicer.shutil.which", return_value="/usr/local/bin/orca-slicer"):
            result = find_slicer("orca")
            assert result == Path("/usr/local/bin/orca-slicer")


def test_find_slicer_not_found():
    """Raises FileNotFoundError when slicer not at default path or on PATH."""
    with patch.dict("estampo.slicer.SLICER_PATHS", {"orca": Path("/nonexistent/orca")}):
        with patch("estampo.slicer.shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="not found"):
                find_slicer("orca")


# --- _apply_overrides ---


def test_apply_overrides():
    data = {
        "wall_loops": "2",
        "sparse_infill_density": "15%",
        "other_setting": "keep",
    }
    result = _apply_overrides(
        data,
        {
            "wall_loops": 4,
            "sparse_infill_density": "25%",
        },
        "test_profile",
    )

    assert result["wall_loops"] == "4"
    assert result["sparse_infill_density"] == "25%"
    assert result["other_setting"] == "keep"
    assert result is data  # modifies in place


# --- _resolve_profiles: filament resolution ---


def test_resolve_profiles_all_filaments_resolved(tmp_path):
    """All filament slots are resolved to their actual profiles."""
    profiles_dir = tmp_path / "profiles" / "filament"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "PLA.json").write_text('{"name": "PLA"}')
    (profiles_dir / "PETG-CF.json").write_text('{"name": "PETG-CF"}')

    out = tmp_path / "out"
    out.mkdir()

    _, filament_arg = _resolve_profiles(
        engine="orca",
        printer=None,
        process=None,
        filaments=["PLA", "PETG-CF"],
        overrides=None,
        project_dir=tmp_path,
        tmp_dir=out,
        profiles_dir="profiles",
    )

    assert filament_arg is not None
    paths = filament_arg.split(";")
    assert len(paths) == 2

    import json

    assert json.loads(Path(paths[0]).read_text())["name"] == "PLA"
    assert json.loads(Path(paths[1]).read_text())["name"] == "PETG-CF"


# --- docker_image ---


def test_docker_image_default():
    assert docker_image() == "estampo/estampo:latest"


def test_docker_image_versioned():
    assert docker_image("2.3.1") == "estampo/estampo:orca-2.3.1"
    assert docker_image("2.3.2") == "estampo/estampo:orca-2.3.2"


def test_docker_image_tag_consistency():
    """All hardcoded Docker image tags in the repo must match docker_image()."""
    import re

    repo_root = Path(__file__).parent.parent
    tag_pattern = re.compile(r"estampo/estampo:orca-(\S+)")
    # Files that construct the tag dynamically (variable interpolation) — skip them
    skip = {
        "scripts/build-docker.sh",
        ".github/workflows/publish-docker.yml",
        ".github/workflows/publish-cloud-bridge.yml",
        ".github/workflows/release-readiness.yml",
    }

    errors = []
    for path in sorted(repo_root.rglob("*")):
        if path.is_dir() or ".git/" in str(path) or path.suffix in {".pyc", ".lock"}:
            continue
        rel = str(path.relative_to(repo_root))
        if rel in skip:
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        for match in tag_pattern.finditer(text):
            version = match.group(1)
            # Skip template/variable patterns
            if "$" in version or "{" in version or "<" in version:
                continue
            expected = docker_image(version)
            actual = match.group(0)
            if actual != expected:
                errors.append(f"{rel}: found '{actual}', expected '{expected}'")

    assert not errors, "Docker image tag inconsistencies:\n" + "\n".join(errors)


# --- _has_docker_image ---


def test_has_docker_image_true():
    mock_result = MagicMock(returncode=0)
    with patch("estampo.slicer.subprocess.run", return_value=mock_result) as mock_run:
        assert _has_docker_image("estampo:orca-2.3.1") is True
        mock_run.assert_called_once_with(
            ["docker", "image", "inspect", "estampo:orca-2.3.1"],
            capture_output=True,
            timeout=10,
        )


def test_has_docker_image_false_no_image():
    mock_result = MagicMock(returncode=1)
    with patch("estampo.slicer.subprocess.run", return_value=mock_result):
        assert _has_docker_image("estampo:orca-2.3.1") is False


def test_has_docker_image_false_no_docker():
    with patch("estampo.slicer.subprocess.run", side_effect=FileNotFoundError):
        assert _has_docker_image("estampo:orca-2.3.1") is False


# --- _slice_via_docker ---


def test_slice_via_docker_command(tmp_path):
    """Verify Docker command is built correctly with profile path rewriting."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    profile_dir = output_dir / ".profiles"
    profile_dir.mkdir()
    (profile_dir / "machine.json").write_text("{}")
    (profile_dir / "process.json").write_text("{}")

    settings_arg = f"{profile_dir}/machine.json;{profile_dir}/process.json"
    filament_arg = None

    mock_result = MagicMock(returncode=0, stdout="", stderr="")
    with patch("estampo.slicer.subprocess.run", return_value=mock_result) as mock_run:
        _slice_via_docker(
            input_3mf,
            output_dir,
            profile_dir,
            settings_arg,
            filament_arg,
            "estampo:orca-2.3.1",
        )

    cmd = mock_run.call_args[0][0]
    assert "docker" == cmd[0]
    assert "--platform" in cmd
    assert "linux/amd64" in cmd
    assert "estampo:orca-2.3.1" in cmd
    entrypoint_idx = cmd.index("--entrypoint")
    assert cmd[entrypoint_idx + 1] == "xvfb-run"
    assert "orca-slicer" in cmd
    # Verify profile paths rewritten to container paths under /work/output/
    settings_idx = cmd.index("--load-settings") + 1
    assert "/work/output/.profiles/machine.json" in cmd[settings_idx]
    assert "/work/output/.profiles/process.json" in cmd[settings_idx]
    assert str(profile_dir) not in cmd[settings_idx]


def test_slice_via_docker_failure(tmp_path):
    """Verify Docker slicer failure raises RuntimeError."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    profile_dir = output_dir / ".profiles"
    profile_dir.mkdir()

    mock_result = MagicMock(returncode=1, stdout="", stderr="some error")
    with patch("estampo.slicer.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Docker slicer failed"):
            _slice_via_docker(
                input_3mf,
                output_dir,
                profile_dir,
                None,
                None,
                "estampo:latest",
            )


# --- slice_plate integration ---


def _mock_resolve(
    name, engine, category, project_dir=None, profiles_dir="profiles", docker_profile_dir=None
):
    """Return fake profile data for testing."""
    return {"name": name, "from": "test"}


def test_slice_plate_local_command(tmp_path):
    """Verify local slicer builds correct CLI command."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")
    output_dir = tmp_path / "output"

    mock_result = MagicMock(returncode=0, stdout="", stderr="")
    slicer_path = Path("/usr/bin/orca-slicer")

    with (
        patch("estampo.slicer._needs_xvfb", return_value=False),
        patch("estampo.slicer.find_slicer", return_value=slicer_path),
        patch("estampo.slicer.resolve_profile_data", side_effect=_mock_resolve),
        patch("estampo.slicer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        slice_plate(
            input_3mf,
            engine="orca",
            output_dir=output_dir,
            printer="My Printer",
            process="My Process",
            filaments=["PLA"],
            overrides={"wall_loops": 4},
            local=True,
        )

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == str(slicer_path)
    assert "--load-settings" in cmd
    assert "--load-filaments" in cmd
    assert "--slice" in cmd
    assert str(output_dir) in cmd


def test_slice_plate_local_fallback(tmp_path):
    """When Docker image not found, falls back to local slicer."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")
    output_dir = tmp_path / "output"

    mock_result = MagicMock(returncode=0, stdout="", stderr="")
    slicer_path = Path("/usr/bin/orca-slicer")

    with (
        patch("estampo.slicer._needs_xvfb", return_value=False),
        patch("estampo.slicer._ensure_docker_image", return_value=False),
        patch("estampo.slicer.find_slicer", return_value=slicer_path),
        patch("estampo.slicer.resolve_profile_data", side_effect=_mock_resolve),
        patch("estampo.slicer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        slice_plate(
            input_3mf,
            engine="orca",
            output_dir=output_dir,
            printer="My Printer",
        )

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == str(slicer_path)


def test_slice_plate_docker_default(tmp_path):
    """Default behavior uses Docker when image is available."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")
    output_dir = tmp_path / "output"

    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("estampo.slicer._ensure_docker_image", return_value=True),
        patch("estampo.slicer.resolve_profile_data", side_effect=_mock_resolve),
        patch("estampo.slicer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        slice_plate(
            input_3mf,
            engine="orca",
            output_dir=output_dir,
            printer="My Printer",
        )

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "docker"
    assert "estampo/estampo:latest" in cmd


def test_slice_plate_docker_version(tmp_path):
    """docker_version selects a versioned image."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")
    output_dir = tmp_path / "output"

    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("estampo.slicer._ensure_docker_image", return_value=True),
        patch("estampo.slicer.resolve_profile_data", side_effect=_mock_resolve),
        patch("estampo.slicer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        slice_plate(
            input_3mf,
            engine="orca",
            output_dir=output_dir,
            printer="My Printer",
            docker_version="2.3.1",
        )

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "docker"
    assert "estampo/estampo:orca-2.3.1" in cmd


def test_slice_plate_docker_image_missing_no_local(tmp_path):
    """Raises FileNotFoundError when Docker image and local slicer both unavailable."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")

    with (
        patch("estampo.slicer._ensure_docker_image", return_value=False),
        patch("estampo.slicer.find_slicer", side_effect=FileNotFoundError("not found")),
    ):
        with pytest.raises(FileNotFoundError, match="Docker image.*not found"):
            slice_plate(
                input_3mf,
                engine="orca",
                docker_version="9.9.9",
            )


def test_slice_plate_docker_fallback_to_local(tmp_path):
    """Falls back to local slicer when Docker image unavailable but local slicer exists."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")
    output_dir = tmp_path / "output"

    mock_result = MagicMock(returncode=0, stdout="", stderr="")
    slicer_path = Path("/usr/bin/orca-slicer")

    with (
        patch("estampo.slicer._needs_xvfb", return_value=False),
        patch("estampo.slicer._ensure_docker_image", return_value=False),
        patch("estampo.slicer.find_slicer", return_value=slicer_path),
        patch("estampo.slicer.resolve_profile_data", side_effect=_mock_resolve),
        patch("estampo.slicer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        slice_plate(
            input_3mf,
            engine="orca",
            output_dir=output_dir,
            printer="My Printer",
            docker_version="2.3.1",
        )

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == str(slicer_path)


def test_slice_plate_xvfb_wraps_local_slicer(tmp_path):
    """xvfb-run is prepended on headless Linux to avoid GL segfaults."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")
    output_dir = tmp_path / "output"

    mock_result = MagicMock(returncode=0, stdout="", stderr="")
    slicer_path = Path("/usr/bin/orca-slicer")

    with (
        patch("estampo.slicer._needs_xvfb", return_value=True),
        patch("estampo.slicer.find_slicer", return_value=slicer_path),
        patch("estampo.slicer.resolve_profile_data", side_effect=_mock_resolve),
        patch("estampo.slicer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        slice_plate(
            input_3mf,
            engine="orca",
            output_dir=output_dir,
            printer="My Printer",
            local=True,
        )

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "xvfb-run"
    assert cmd[1] == str(slicer_path)


# --- slice_plate: --allow-mix-temp version gating ---


def test_slice_plate_allow_mix_temp_on_232(tmp_path):
    """--allow-mix-temp is passed for OrcaSlicer 2.3.2+ with mixed filaments."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")
    output_dir = tmp_path / "output"

    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("estampo.slicer._ensure_docker_image", return_value=True),
        patch("estampo.slicer.resolve_profile_data", side_effect=_mock_resolve),
        patch("estampo.slicer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        slice_plate(
            input_3mf,
            engine="orca",
            output_dir=output_dir,
            printer="My Printer",
            filaments=["PLA", "PETG"],
            docker_version="2.3.2",
        )

    cmd = mock_run.call_args[0][0]
    assert "--allow-mix-temp" in cmd


def test_slice_plate_no_allow_mix_temp_on_231(tmp_path):
    """--allow-mix-temp is NOT passed for OrcaSlicer 2.3.1 (flag doesn't exist)."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")
    output_dir = tmp_path / "output"

    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("estampo.slicer._ensure_docker_image", return_value=True),
        patch("estampo.slicer.resolve_profile_data", side_effect=_mock_resolve),
        patch("estampo.slicer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        slice_plate(
            input_3mf,
            engine="orca",
            output_dir=output_dir,
            printer="My Printer",
            filaments=["PLA", "PETG"],
            docker_version="2.3.1",
        )

    cmd = mock_run.call_args[0][0]
    assert "--allow-mix-temp" not in cmd


def test_slice_plate_no_allow_mix_temp_single_filament(tmp_path):
    """--allow-mix-temp is NOT passed with only one filament type."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")
    output_dir = tmp_path / "output"

    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("estampo.slicer._ensure_docker_image", return_value=True),
        patch("estampo.slicer.resolve_profile_data", side_effect=_mock_resolve),
        patch("estampo.slicer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        slice_plate(
            input_3mf,
            engine="orca",
            output_dir=output_dir,
            printer="My Printer",
            filaments=["PLA"],
            docker_version="2.3.2",
        )

    cmd = mock_run.call_args[0][0]
    assert "--allow-mix-temp" not in cmd


# --- slice_plate: stale pinned profiles ---


def test_slice_plate_errors_on_stale_pinned_profiles_no_marker(tmp_path):
    """Error when pinned profiles exist without a version marker."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")

    # Create pinned profiles without version marker
    profiles = tmp_path / "profiles" / "machine"
    profiles.mkdir(parents=True)
    (profiles / "Printer.json").write_text('{"name": "Printer"}')

    with (
        patch("estampo.slicer._ensure_docker_image", return_value=True),
        pytest.raises(EstampoError, match="no version marker"),
    ):
        slice_plate(
            input_3mf,
            engine="orca",
            printer="Printer",
            project_dir=tmp_path,
            docker_version="2.3.2",
        )


def test_slice_plate_errors_on_version_mismatch(tmp_path):
    """Error when pinned profiles were created for a different slicer version."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")

    # Create pinned profiles with mismatched version marker
    profiles = tmp_path / "profiles" / "machine"
    profiles.mkdir(parents=True)
    (profiles / "Printer.json").write_text('{"name": "Printer"}')
    (tmp_path / "profiles" / ".slicer-version").write_text("2.3.1\n")

    with (
        patch("estampo.slicer._ensure_docker_image", return_value=True),
        pytest.raises(EstampoError, match="created for slicer 2.3.1"),
    ):
        slice_plate(
            input_3mf,
            engine="orca",
            printer="Printer",
            project_dir=tmp_path,
            docker_version="2.3.2",
        )


def test_slice_plate_ok_with_matching_version(tmp_path):
    """No error when pinned profiles match the target slicer version."""
    input_3mf = tmp_path / "plate.3mf"
    input_3mf.write_text("fake")
    output_dir = tmp_path / "output"

    # Create pinned profiles with matching version marker
    profiles = tmp_path / "profiles" / "machine"
    profiles.mkdir(parents=True)
    (profiles / "Printer.json").write_text('{"type": "machine", "name": "Printer"}')
    (tmp_path / "profiles" / ".slicer-version").write_text("2.3.2\n")

    with (
        patch("estampo.slicer._ensure_docker_image", return_value=True),
        patch("estampo.slicer._slice_via_docker", return_value=output_dir) as mock_docker,
        patch("estampo.slicer._fix_sliced_3mf"),
        patch("estampo.profiles.extract_docker_profiles", return_value=tmp_path / "docker"),
    ):
        slice_plate(
            input_3mf,
            engine="orca",
            output_dir=output_dir,
            printer="Printer",
            project_dir=tmp_path,
            docker_version="2.3.2",
        )

    # Should reach the Docker slicer call without error
    mock_docker.assert_called_once()


# --- parse_gcode_stats ---


def test_parse_gcode_stats_full(tmp_path):
    gcode = tmp_path / "plate.gcode"
    gcode.write_text(
        "; HEADER_BLOCK_START\n"
        "; generated by OrcaSlicer\n"
        "; estimated printing time (normal mode) = 1h 33m 15s\n"
        "; HEADER_BLOCK_END\n"
        "G28 ; home\n"
        "G1 X10 Y10\n"
        "; filament used [mm] = 14395.62\n"
        "; filament used [cm3] = 34.63\n"
        "; filament used [g] = 42.94\n"
        "; total filament used [g] = 42.94\n"
    )
    stats = parse_gcode_stats(tmp_path)
    assert stats["filament_g"] == 42.94
    assert stats["print_time"] == "1h 33m 15s"


def test_parse_gcode_stats_orca_format(tmp_path):
    """OrcaSlicer 2.3+ format: time in header, cm3 in footer, no grams."""
    gcode = tmp_path / "plate.gcode"
    gcode.write_text(
        "; model printing time: 4m 23s; total estimated time: 10m 52s\n"
        "; filament_density: 0\n"
        "G28 ; home\n"
        "G1 X10 Y10\n"
        "; filament used [mm] = 101.51\n"
        "; filament used [cm3] = 0.24\n"
    )
    stats = parse_gcode_stats(tmp_path)
    assert stats["filament_cm3"] == 0.24
    assert stats["print_time"] == "10m 52s"
    assert "filament_g" not in stats


def test_parse_gcode_stats_empty(tmp_path):
    assert parse_gcode_stats(tmp_path) == {}


def test_parse_gcode_stats_no_metadata(tmp_path):
    gcode = tmp_path / "plate.gcode"
    gcode.write_text("G28 ; home\nG1 X10 Y10\n")
    assert parse_gcode_stats(tmp_path) == {}

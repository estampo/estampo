"""Tests for CLI entry point."""

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from packaging.version import Version

from estampo import EstampoError, __version__
from estampo.cli import (
    _resolve_config_path,
    _version_callback,
    main,
)
from estampo.profiles import SYSTEM_DIRS

FIXTURES = Path(__file__).parent / "fixtures"

_orca_system = SYSTEM_DIRS.get("orca")
_has_orca = _orca_system is not None and _orca_system.is_dir()


def _docker_orca_version() -> str | None:
    """Return the OrcaSlicer Docker image version to test with.

    Uses ESTAMPO_TEST_ORCA_VERSION env var if set, otherwise auto-detects
    the first available estampo:orca-* image.
    """
    env_ver = os.environ.get("ESTAMPO_TEST_ORCA_VERSION")
    if env_ver:
        return env_ver
    try:
        r = subprocess.run(
            ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        versions = []
        for line in r.stdout.splitlines():
            if line.startswith("estampo:orca-"):
                versions.append(line.split("estampo:orca-", 1)[1])
        # Prefer stable releases over pre-releases, sorted by version number
        stable = [v for v in versions if not Version(v).is_prerelease]
        if stable:
            return max(stable, key=Version)
        if versions:
            return max(versions, key=Version)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


_docker_version = _docker_orca_version()
skip_no_docker = pytest.mark.skipif(
    _docker_version is None, reason="Docker not running or no estampo:orca-* image"
)


def _posix(p: Path) -> str:
    """Return a forward-slash path string (avoids TOML backslash escaping on Windows)."""
    return p.as_posix()


def _write_config(tmp_path: Path, engine: str = "orca") -> Path:
    toml = tmp_path / "estampo.toml"
    toml.write_text(f"""
[plate]
size = [256, 256]
padding = 5.0

[slicer]
engine = "{engine}"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
copies = 2
orient = "flat"

[[parts]]
file = "{_posix(FIXTURES / "cylinder_5x20mm.stl")}"
orient = "upright"
""")
    return toml


def test_run_until_plate(tmp_path):
    config = _write_config(tmp_path)
    output_dir = tmp_path / "output"
    main(["run", str(config), "-o", str(output_dir), "--until", "plate"])
    assert (output_dir / "plate.3mf").exists()
    assert (output_dir / "plate.3mf").stat().st_size > 0


def test_run_default_output(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    main(["run", str(config), "--until", "plate"])
    assert (tmp_path / "estampo_output" / "plate.3mf").exists()


def test_run_verbose(tmp_path):
    config = _write_config(tmp_path)
    output_dir = tmp_path / "output"
    main(["run", str(config), "-o", str(output_dir), "--until", "plate", "-v"])
    assert (output_dir / "plate.3mf").exists()


def test_no_subcommand():
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 1


def test_run_auto_discover_config(tmp_path, monkeypatch):
    """Running without config arg should find ./estampo.toml."""
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    main(["run", "--until", "plate"])
    assert (tmp_path / "estampo_output" / "plate.3mf").exists()


def test_run_missing_config_no_traceback(tmp_path, monkeypatch, capsys):
    """Missing config should print a clean error, not a traceback."""
    monkeypatch.chdir(tmp_path)  # no estampo.toml here
    with pytest.raises(SystemExit) as exc_info:
        main(["run"])
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "estampo.toml" in captured.err


def test_run_until_and_only_conflict(tmp_path, capsys):
    config = _write_config(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        main(["run", str(config), "--until", "plate", "--only", "slice"])
    assert exc_info.value.code == 1
    assert "Cannot use both" in capsys.readouterr().err


def test_run_only_plate(tmp_path):
    """--only plate should work without any pre-existing artifacts."""
    config = _write_config(tmp_path)
    output_dir = tmp_path / "output"
    main(["run", str(config), "-o", str(output_dir), "--only", "plate"])
    assert (output_dir / "plate.3mf").exists()


def test_run_only_slice_fails_without_plate(tmp_path, capsys):
    """--only slice should fail when plate.3mf doesn't exist."""
    config = _write_config(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    with pytest.raises(SystemExit) as exc_info:
        main(["run", str(config), "-o", str(output_dir), "--only", "slice"])
    assert exc_info.value.code == 1
    assert "plate 3MF file" in capsys.readouterr().err


def test_run_custom_stages(tmp_path):
    """Config with custom pipeline stages should be respected."""
    toml = tmp_path / "estampo.toml"
    toml.write_text(f"""
[plate]
size = [256, 256]
padding = 5.0

[slicer]
engine = "orca"

[pipeline]
stages = ["load", "arrange", "plate"]

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
    output_dir = tmp_path / "output"
    # Running all stages (only up to plate since that's all that's configured)
    main(["run", str(toml), "-o", str(output_dir)])
    assert (output_dir / "plate.3mf").exists()


def test_run_name_output_dir(tmp_path, monkeypatch):
    """Project name should create a subdirectory under estampo_output/."""
    toml = tmp_path / "estampo.toml"
    toml.write_text(f"""
name = "benchy"

[plate]
size = [256, 256]

[slicer]
engine = "orca"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
    monkeypatch.chdir(tmp_path)
    main(["run", str(toml), "--until", "plate"])
    assert (tmp_path / "estampo_output" / "benchy" / "plate.3mf").exists()


def test_run_name_explicit_output_dir(tmp_path):
    """Explicit -o should override name-based default."""
    toml = tmp_path / "estampo.toml"
    toml.write_text(f"""
name = "benchy"

[plate]
size = [256, 256]

[slicer]
engine = "orca"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
    output_dir = tmp_path / "custom"
    main(["run", str(toml), "-o", str(output_dir), "--until", "plate"])
    assert (output_dir / "plate.3mf").exists()


def test_run_invalid_stage_in_config(tmp_path):
    """Unknown stage in config should raise at parse time."""
    toml = tmp_path / "estampo.toml"
    toml.write_text(f"""
[plate]
size = [256, 256]

[slicer]
engine = "orca"

[pipeline]
stages = ["load", "arrange", "foobar"]

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
    with pytest.raises(SystemExit) as exc_info:
        main(["run", str(toml)])
    assert exc_info.value.code == 1


def test_run_warns_on_unknown_override_keys(tmp_path, capsys):
    """Run should warn when override keys don't exist in the process profile."""
    profiles = tmp_path / "profiles" / "orca" / "process"
    profiles.mkdir(parents=True)
    (profiles / "MyProcess.json").write_text(
        '{"type": "process", "layer_height": "0.2", "wall_loops": "2"}'
    )
    toml = tmp_path / "estampo.toml"
    toml.write_text(f"""
[plate]
size = [256, 256]

[slicer]
engine = "orca"

[slicer.orca]
process = "MyProcess"

[slicer.orca.overrides]
bogus_key = "42"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
    main(["run", str(toml), "-o", str(tmp_path / "out"), "--until", "plate"])
    captured = capsys.readouterr()
    assert "bogus_key" in captured.out


def test_profiles_list(capsys):
    """Profiles list should run and produce output."""
    main(["profiles", "list", "--engine", "orca", "--category", "machine"])
    captured = capsys.readouterr()
    assert "machine" in captured.out.lower()


@pytest.mark.skipif(not _has_orca, reason="OrcaSlicer not installed")
def test_profiles_pin(tmp_path):
    config = tmp_path / "estampo.toml"
    config.write_text(f"""
[slicer]
engine = "orca"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"
filaments = ["Generic PLA @base"]

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
    main(["profiles", "pin", str(config)])
    assert (tmp_path / "profiles" / "orca" / "machine" / "Bambu Lab P1S 0.4 nozzle.json").exists()
    assert (tmp_path / "profiles" / "orca" / "process" / "0.20mm Standard @BBL X1C.json").exists()
    assert (tmp_path / "profiles" / "orca" / "filament" / "Generic PLA @base.json").exists()


# --- Docker-based slicing integration tests ---


def _docker_work_dir(suffix: str = "") -> Path:
    """Return a work directory suitable for Docker volume mounts."""
    work_dir = Path.home() / ".cache" / f"estampo-test{suffix}"
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _write_slice_config(
    tmp_path: Path,
    filaments: list[str] | None = None,
    version: str | None = None,
) -> Path:
    """Write an estampo.toml for slicing tests."""
    filaments = filaments or ["Generic PLA @base"]
    filament_toml = ", ".join(f'"{f}"' for f in filaments)
    version_line = f'version = "{version}"' if version else ""
    toml = tmp_path / "estampo.toml"
    toml.write_text(f"""
[plate]
size = [256, 256]
padding = 5.0

[slicer]
engine = "orca"
{version_line}
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"
filaments = [{filament_toml}]

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
copies = 1
""")
    return toml


@skip_no_docker
def test_slice_docker(monkeypatch):
    """Slice a single cube via Docker using version from config."""
    work_dir = _docker_work_dir()
    config = _write_slice_config(work_dir, version=_docker_version)
    output_dir = work_dir / "output"
    monkeypatch.chdir(work_dir)
    try:
        main(
            [
                "run",
                str(config),
                "-o",
                str(output_dir),
                "--until",
                "slice",
            ]
        )
        gcode_files = list(output_dir.glob("*.gcode"))
        assert len(gcode_files) >= 1, "Expected at least one gcode file"
        assert gcode_files[0].stat().st_size > 0
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@skip_no_docker
def test_slice_docker_filament_override(monkeypatch):
    """--filament-type overrides config filaments with a single filament."""
    work_dir = _docker_work_dir("-override")
    config = _write_slice_config(
        work_dir,
        filaments=["Generic PLA @base", "Generic PLA @base"],
        version=_docker_version,
    )
    output_dir = work_dir / "output"
    monkeypatch.chdir(work_dir)
    try:
        main(
            [
                "run",
                str(config),
                "-o",
                str(output_dir),
                "--until",
                "slice",
                "--filament-type",
                "Generic PLA @base",
                "--filament-slot",
                "1",
            ]
        )
        gcode_files = list(output_dir.glob("*.gcode"))
        assert len(gcode_files) >= 1, "Expected at least one gcode file"
        assert gcode_files[0].stat().st_size > 0
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@skip_no_docker
def test_slice_docker_version_mismatch(monkeypatch):
    """Config version that doesn't match any Docker image should fail."""
    work_dir = _docker_work_dir("-mismatch")
    config = _write_slice_config(work_dir, version="99.99.99")
    monkeypatch.chdir(work_dir)
    try:
        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "run",
                    str(config),
                    "-o",
                    str(work_dir / "output"),
                    "--until",
                    "slice",
                ]
            )
        assert exc_info.value.code == 1
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Unit tests for CLI helpers and commands (mocked, no I/O)
# ---------------------------------------------------------------------------


# --- _version_callback ---


def test_version_callback_prints_version(capsys):
    """_version_callback should print version and raise typer.Exit."""
    import typer

    with pytest.raises(typer.Exit):
        _version_callback(True)
    assert __version__ in capsys.readouterr().out


def test_version_callback_noop_when_false():
    """_version_callback should do nothing when value is False."""
    _version_callback(False)  # should not raise


def test_version_flag_via_main(capsys):
    """--version flag via main() should print version and exit cleanly."""
    main(["--version"])
    assert __version__ in capsys.readouterr().out


# --- _resolve_config_path ---


def test_resolve_config_path_explicit(tmp_path):
    """Explicit path is returned as-is."""
    p = tmp_path / "custom.toml"
    assert _resolve_config_path(p) == p


def test_resolve_config_path_fallback(tmp_path, monkeypatch):
    """Falls back to ./estampo.toml when it exists."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "estampo.toml").write_text("[slicer]\n")
    result = _resolve_config_path(None)
    assert result == Path("estampo.toml")


def test_resolve_config_path_missing(tmp_path, monkeypatch):
    """Raises EstampoError when no config and no estampo.toml."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(EstampoError, match="No config file specified"):
        _resolve_config_path(None)


# --- validate command ---


@patch("estampo.init.validate_config")
@patch("estampo.cli.load_config")
def test_validate_no_warnings(mock_load, mock_validate, tmp_path, capsys):
    """validate with no warnings should print 'All checks passed'."""
    from estampo.init import ValidationResult

    config = tmp_path / "estampo.toml"
    config.write_text("[slicer]\n")
    mock_validate.return_value = ValidationResult(
        passes=["Slicer version pinned: 2.3.1"],
        warnings=[],
    )
    main(["validate", str(config)])
    out = capsys.readouterr().out
    assert "All checks passed" in out


@patch("estampo.init.validate_config")
@patch("estampo.cli.load_config")
def test_validate_with_warnings(mock_load, mock_validate, tmp_path, capsys):
    """validate with warnings should show warning count."""
    from estampo.init import ValidationResult

    config = tmp_path / "estampo.toml"
    config.write_text("[slicer]\n")
    mock_validate.return_value = ValidationResult(
        passes=["OK thing"],
        warnings=["slicer.version is not set", "some other issue"],
    )
    main(["validate", str(config)])
    out = capsys.readouterr().out
    assert "2" in out
    assert "warning" in out


# --- main() error handling ---


def test_main_estampo_error(capsys):
    """EstampoError should print clean error and exit 1."""
    with patch("estampo.cli.app", side_effect=EstampoError("boom")):
        with pytest.raises(SystemExit) as exc_info:
            main(["run"])
        assert exc_info.value.code == 1
    assert "boom" in capsys.readouterr().err


def test_main_value_error(capsys):
    """ValueError should print clean error and exit 1."""
    with patch("estampo.cli.app", side_effect=ValueError("bad value")):
        with pytest.raises(SystemExit) as exc_info:
            main(["run"])
        assert exc_info.value.code == 1
    assert "bad value" in capsys.readouterr().err


def test_main_file_not_found_error(capsys):
    """FileNotFoundError should print clean error and exit 1."""
    with patch("estampo.cli.app", side_effect=FileNotFoundError("no such file")):
        with pytest.raises(SystemExit) as exc_info:
            main(["run"])
        assert exc_info.value.code == 1
    assert "no such file" in capsys.readouterr().err


def test_main_system_exit_with_code():
    """SystemExit with non-zero code should propagate."""
    with patch("estampo.cli.app", side_effect=SystemExit(42)):
        with pytest.raises(SystemExit) as exc_info:
            main(["run"])
        assert exc_info.value.code == 42


def test_main_system_exit_zero():
    """SystemExit(0) should not re-raise."""
    with patch("estampo.cli.app", side_effect=SystemExit(0)):
        main(["run"])  # should not raise


def test_main_keyboard_interrupt():
    """KeyboardInterrupt should exit 130."""
    with patch("estampo.cli.app", side_effect=KeyboardInterrupt()):
        with pytest.raises(SystemExit) as exc_info:
            main(["run"])
        assert exc_info.value.code == 130


# --- profiles list ---


@patch("estampo.profiles.discover_profiles")
def test_profiles_list_command(mock_discover, capsys):
    """profiles list should show category and profile names."""
    mock_discover.return_value = {
        "machine": {"Bambu P1S": Path("/fake")},
        "process": {},
        "filament": {},
    }
    main(["profiles", "list", "--engine", "orca", "--category", "machine"])
    out = capsys.readouterr().out
    assert "machine" in out
    assert "Bambu P1S" in out


# --- profiles pin ---


def _mock_pin_cfg(tmp_path, profiles_dir="profiles"):
    """Create a mock config for profiles pin tests."""
    mock_cfg = MagicMock()
    mock_cfg.slicer.engine = "orca"
    mock_cfg.slicer.active = mock_cfg.slicer.orca
    mock_cfg.slicer.orca.printer = "Bambu Lab P1S 0.4 nozzle"
    mock_cfg.slicer.orca.process = "0.20mm Standard @BBL X1C"
    mock_cfg.slicer.orca.filaments = ["Generic PLA @base"]
    mock_cfg.slicer.version = None
    mock_cfg.slicer.profiles_dir = profiles_dir
    mock_cfg.base_dir = tmp_path
    return mock_cfg


@patch("estampo.profiles.pin_profiles", return_value=[Path("/a/b.json"), Path("/c/d.json")])
@patch("estampo.cli.load_config")
def test_profiles_pin_command(mock_load, mock_pin, tmp_path, capsys):
    """profiles pin should call pin_profiles and report count."""
    config = tmp_path / "estampo.toml"
    config.write_text("[slicer]\n")
    mock_load.return_value = _mock_pin_cfg(tmp_path)

    main(["profiles", "pin", str(config)])
    out = capsys.readouterr().out
    assert "Pinned 2 profile(s)" in out
    mock_pin.assert_called_once()


@patch("estampo.profiles.pin_profiles", return_value=[Path("/a/b.json")])
@patch("estampo.cli.load_config")
def test_profiles_pin_existing_dir_overwrite(mock_load, mock_pin, tmp_path, capsys):
    """profiles pin should allow overwriting an existing profiles directory."""
    config = tmp_path / "estampo.toml"
    config.write_text("[slicer]\n")
    # Create existing engine-specific profiles dir with content
    (tmp_path / "profiles" / "orca").mkdir(parents=True)
    (tmp_path / "profiles" / "orca" / "old.json").write_text("{}")
    mock_load.return_value = _mock_pin_cfg(tmp_path)

    with patch("builtins.input", return_value="o"):
        main(["profiles", "pin", str(config)])
    out = capsys.readouterr().out
    assert "Pinned 1 profile(s)" in out


@patch("estampo.profiles.pin_profiles", return_value=[Path("/a/b.json")])
@patch("estampo.cli.load_config")
def test_profiles_pin_existing_dir_cancel(mock_load, mock_pin, tmp_path, capsys):
    """profiles pin should allow cancelling when dir exists."""
    config = tmp_path / "estampo.toml"
    config.write_text("[slicer]\n")
    (tmp_path / "profiles" / "orca").mkdir(parents=True)
    (tmp_path / "profiles" / "orca" / "old.json").write_text("{}")
    mock_load.return_value = _mock_pin_cfg(tmp_path)

    with patch("builtins.input", return_value="c"):
        main(["profiles", "pin", str(config)])
    # Cancel means pin_profiles is never called
    mock_pin.assert_not_called()


@patch("estampo.profiles.pin_profiles", return_value=[Path("/a/b.json")])
@patch("estampo.cli.load_config")
def test_profiles_pin_existing_dir_different(mock_load, mock_pin, tmp_path, capsys):
    """profiles pin should allow choosing a different directory."""
    config = tmp_path / "estampo.toml"
    config.write_text('[slicer]\nengine = "orca"\n')
    (tmp_path / "profiles" / "orca").mkdir(parents=True)
    (tmp_path / "profiles" / "orca" / "old.json").write_text("{}")
    mock_load.return_value = _mock_pin_cfg(tmp_path)

    with patch("builtins.input", side_effect=["d", "my-profiles"]):
        main(["profiles", "pin", str(config)])
    out = capsys.readouterr().out
    assert "Pinned 1 profile(s) to my-profiles/" in out
    # Should have written profiles_dir to TOML
    updated = config.read_text()
    assert 'profiles_dir = "my-profiles"' in updated


@patch("estampo.profiles.pin_profiles", return_value=[Path("/a/b.json")])
@patch("estampo.cli.load_config")
def test_profiles_pin_updates_toml_when_nondefault(mock_load, mock_pin, tmp_path, capsys):
    """profiles pin should add profiles_dir to TOML when using non-default dir."""
    config = tmp_path / "estampo.toml"
    config.write_text('[slicer]\nengine = "orca"\n')
    mock_load.return_value = _mock_pin_cfg(tmp_path, profiles_dir="custom")

    main(["profiles", "pin", str(config)])
    updated = config.read_text()
    assert 'profiles_dir = "custom"' in updated


@patch("estampo.profiles.pin_profiles", return_value=[Path("/a/b.json")])
@patch("estampo.cli.load_config")
def test_profiles_pin_default_dir_no_toml_change(mock_load, mock_pin, tmp_path, capsys):
    """profiles pin should not modify TOML when using default profiles dir."""
    config = tmp_path / "estampo.toml"
    original = '[slicer]\nengine = "orca"\n'
    config.write_text(original)
    mock_load.return_value = _mock_pin_cfg(tmp_path)

    main(["profiles", "pin", str(config)])
    assert config.read_text() == original
    out = capsys.readouterr().out
    assert "no config change needed" in out


@patch("estampo.profiles.pin_profiles", return_value=[Path("/a/b.json")])
@patch("estampo.cli.load_config")
def test_profiles_pin_asks_before_changing_existing_dir(mock_load, mock_pin, tmp_path, capsys):
    """profiles pin should ask before changing an existing profiles_dir value."""
    config = tmp_path / "estampo.toml"
    config.write_text('[slicer]\nengine = "orca"\nprofiles_dir = "old-profiles"\n')
    mock_load.return_value = _mock_pin_cfg(tmp_path, profiles_dir="new-profiles")

    with patch("builtins.input", return_value="y"):
        main(["profiles", "pin", str(config)])
    updated = config.read_text()
    assert 'profiles_dir = "new-profiles"' in updated


@patch("estampo.profiles.pin_profiles", return_value=[Path("/a/b.json")])
@patch("estampo.cli.load_config")
def test_profiles_pin_empty_dir_name_cancels(mock_load, mock_pin, tmp_path, capsys):
    """profiles pin should cancel when user enters empty directory name."""
    config = tmp_path / "estampo.toml"
    config.write_text("[slicer]\n")
    (tmp_path / "profiles" / "orca").mkdir(parents=True)
    (tmp_path / "profiles" / "orca" / "old.json").write_text("{}")
    mock_load.return_value = _mock_pin_cfg(tmp_path)

    with patch("builtins.input", side_effect=["d", ""]):
        main(["profiles", "pin", str(config)])
    out = capsys.readouterr().out
    assert "Cancelled" in out
    mock_pin.assert_not_called()


@patch("estampo.profiles.pin_profiles", return_value=[Path("/a/b.json")])
@patch("estampo.cli.load_config")
def test_profiles_pin_toml_already_correct(mock_load, mock_pin, tmp_path, capsys):
    """profiles pin should skip TOML update when profiles_dir already matches."""
    config = tmp_path / "estampo.toml"
    original = '[slicer]\nengine = "orca"\nprofiles_dir = "custom"\n'
    config.write_text(original)
    mock_load.return_value = _mock_pin_cfg(tmp_path, profiles_dir="custom")

    main(["profiles", "pin", str(config)])
    # TOML should be unchanged
    assert config.read_text() == original


# --- profiles add ---


@patch("estampo.profiles.add_profile", return_value=Path("/profiles/machine/test.json"))
def test_profiles_add_command(mock_add, capsys):
    """profiles add should call add_profile and report the path."""
    main(["profiles", "add", "/tmp/test.json"])
    out = capsys.readouterr().out
    assert "Added profile:" in out
    mock_add.assert_called_once()


# --- init ---


def test_init_template(capsys):
    """init --template should dump template to stdout."""
    main(["init", "--template"])
    out = capsys.readouterr().out
    assert "estampo.toml" in out
    assert "[[parts]]" in out


# --- validate ---


def test_init_non_interactive(tmp_path, capsys):
    """init with --engine, --filament, --part should generate TOML without wizard."""
    dest = tmp_path / "estampo.toml"
    main(
        [
            "init",
            "--engine",
            "orca",
            "--printer",
            "Bambu Lab P1S 0.4 nozzle",
            "--process",
            "0.20mm Standard @BBL X1C",
            "--filament",
            "Generic PLA @base",
            "--part",
            "cube.stl",
            "--part",
            "bracket.stl",
            "-o",
            str(dest),
        ]
    )
    toml = dest.read_text()
    assert 'engine = "orca"' in toml
    assert 'printer = "Bambu Lab P1S 0.4 nozzle"' in toml
    assert 'process = "0.20mm Standard @BBL X1C"' in toml
    assert "Generic PLA @base" in toml
    assert 'file = "cube.stl"' in toml
    assert 'file = "bracket.stl"' in toml


def test_init_non_interactive_partial_falls_back_to_wizard_warning(capsys):
    """init with only some non-interactive params should warn about fallback."""
    # This will fall back to wizard which will fail without a terminal,
    # but we should see the warning first
    with pytest.raises((SystemExit, Exception)):
        main(["init", "--engine", "orca", "--part", "cube.stl"])
    out = capsys.readouterr().out
    assert "Non-interactive init requires" in out


# --- info ---


def test_info_json(capsys):
    """info --json should output valid JSON with expected keys."""
    import json as json_mod

    main(["info", "--json"])
    out = capsys.readouterr().out
    data = json_mod.loads(out)
    assert "stages" in data
    assert "engines" in data
    assert "orient_values" in data
    assert "bed_types" in data
    assert "file_extensions" in data
    assert "command_variables" in data
    assert "orca" in data["engines"]
    assert "cura" in data["engines"]
    assert "flat" in data["orient_values"]
    assert ".stl" in data["file_extensions"]
    assert "output_dir" in data["command_variables"]


def test_info_human(capsys):
    """info without --json should output human-readable text."""
    main(["info"])
    out = capsys.readouterr().out
    assert "Stages" in out
    assert "Engines" in out
    assert "flat" in out


# --- profiles list --json ---


@patch("estampo.profiles.discover_profile_names")
def test_profiles_list_json(mock_discover, capsys):
    """profiles list --json should output valid JSON."""
    import json as json_mod

    mock_discover.return_value = (
        {"machine": ["Bambu P1S"], "process": ["0.20mm Standard"], "filament": ["PLA"]},
        "bundled",
    )
    main(["profiles", "list", "--engine", "orca", "--json"])
    out = capsys.readouterr().out
    data = json_mod.loads(out)
    assert data["source"] == "bundled"
    assert data["engine"] == "orca"
    assert "Bambu P1S" in data["profiles"]["machine"]


@patch("estampo.profiles.discover_profile_names")
def test_profiles_list_json_with_category(mock_discover, capsys):
    """profiles list --json --category should filter."""
    import json as json_mod

    mock_discover.return_value = (
        {"machine": ["P1S"], "process": ["Standard"], "filament": ["PLA"]},
        "bundled",
    )
    main(["profiles", "list", "--engine", "orca", "--category", "machine", "--json"])
    out = capsys.readouterr().out
    data = json_mod.loads(out)
    assert "machine" in data["profiles"]
    assert "process" not in data["profiles"]


# --- profiles list --printer ---


@patch("estampo.profiles.filter_profiles_by_printer")
@patch("estampo.profiles.discover_profile_names")
def test_profiles_list_printer_filters(mock_discover, mock_filter, capsys):
    """profiles list --printer applies the compat filter before printing."""
    mock_discover.return_value = (
        {
            "machine": ["P1S", "P1P"],
            "process": ["HQ P1P", "HQ P1S"],
            "filament": [],
        },
        "bundled",
    )
    mock_filter.return_value = {"machine": ["P1S", "P1P"], "process": ["HQ P1S"], "filament": []}

    main(["profiles", "list", "--engine", "orca", "--category", "process", "--printer", "P1S"])
    out = capsys.readouterr().out
    assert "HQ P1S" in out
    assert "HQ P1P" not in out
    mock_filter.assert_called_once()


@patch("estampo.profiles.filter_profiles_by_printer")
@patch("estampo.profiles.discover_profile_names")
def test_profiles_list_printer_json(mock_discover, mock_filter, capsys):
    """profiles list --printer --json applies filter and emits JSON."""
    import json as json_mod

    mock_discover.return_value = (
        {"machine": ["P1S"], "process": ["HQ P1P", "HQ P1S"], "filament": []},
        "bundled",
    )
    mock_filter.return_value = {"machine": ["P1S"], "process": ["HQ P1S"], "filament": []}

    main(
        [
            "profiles",
            "list",
            "--engine",
            "orca",
            "--category",
            "process",
            "--printer",
            "P1S",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    data = json_mod.loads(out)
    assert data["profiles"] == {"process": ["HQ P1S"]}


def test_profiles_list_printer_cura_errors(capsys):
    """--printer is not supported for CuraEngine (no compat concept)."""
    with pytest.raises(SystemExit) as exc:
        main(["profiles", "list", "--engine", "cura", "--printer", "anything"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "not supported" in err and "cura" in err


# --- profiles pin --yes ---


@patch("estampo.profiles.pin_profiles", return_value=[Path("/a/b.json")])
@patch("estampo.cli.load_config")
def test_profiles_pin_yes_skips_prompts(mock_load, mock_pin, tmp_path, capsys):
    """profiles pin --yes should overwrite without prompting."""
    config = tmp_path / "estampo.toml"
    config.write_text("[slicer]\n")
    (tmp_path / "profiles" / "orca").mkdir(parents=True)
    (tmp_path / "profiles" / "orca" / "old.json").write_text("{}")
    mock_load.return_value = _mock_pin_cfg(tmp_path)

    # No input() mock needed — --yes should skip prompts
    main(["profiles", "pin", str(config), "--yes"])
    out = capsys.readouterr().out
    assert "Pinned 1 profile(s)" in out
    mock_pin.assert_called_once()


@patch("estampo.profiles.pin_profiles", return_value=[Path("/a/b.json")])
@patch("estampo.cli.load_config")
def test_profiles_pin_yes_updates_toml(mock_load, mock_pin, tmp_path, capsys):
    """profiles pin --yes should auto-accept TOML updates."""
    config = tmp_path / "estampo.toml"
    config.write_text('[slicer]\nengine = "orca"\nprofiles_dir = "old"\n')
    mock_load.return_value = _mock_pin_cfg(tmp_path, profiles_dir="new")

    main(["profiles", "pin", str(config), "--yes"])
    updated = config.read_text()
    assert 'profiles_dir = "new"' in updated


# --- validate ---


def test_validate_json(tmp_path, capsys):
    """validate --json should output structured JSON."""
    import json as json_mod

    config = tmp_path / "estampo.toml"
    (tmp_path / "cube.stl").write_bytes(b"solid cube\nendsolid cube\n")
    config.write_text(
        '[slicer]\nengine = "orca"\nversion = "2.3.1"\n\n[[parts]]\nfile = "cube.stl"\n'
    )
    main(["validate", str(config), "--json"])
    out = capsys.readouterr().out
    data = json_mod.loads(out)
    assert "valid" in data
    assert "passes" in data
    assert "warnings" in data
    assert isinstance(data["valid"], bool)
    assert isinstance(data["passes"], list)


def test_validate_json_with_warnings(tmp_path, capsys):
    """validate --json should report warnings."""
    import json as json_mod

    config = tmp_path / "estampo.toml"
    (tmp_path / "cube.stl").write_bytes(b"solid cube\nendsolid cube\n")
    # Missing slicer version — should produce a warning
    config.write_text('[slicer]\nengine = "orca"\n\n[[parts]]\nfile = "cube.stl"\n')
    main(["validate", str(config), "--json"])
    out = capsys.readouterr().out
    data = json_mod.loads(out)
    assert isinstance(data["warnings"], list)


def test_validate_missing_config(tmp_path):
    """validate should fail when config file doesn't exist."""
    with pytest.raises(SystemExit):
        main(["validate", str(tmp_path / "nonexistent.toml")])

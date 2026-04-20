"""Tests for estampo init, validate, and template commands."""

from pathlib import Path

import pytest

from estampo.cli import main
from estampo.init import (
    BED_TYPES,
    ValidationResult,
    _build_toml,
    _check_cura_template_gcode,
    _closest_match,
    _emit_cura_pin_hint,
    _is_bambu_printer,
    _validate_override,
    build_config_toml,
    dump_template,
    generate_workflow,
    validate_config,
    write_workflow,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _posix(p: Path) -> str:
    return p.as_posix()


def _write_valid_config(tmp_path: Path) -> Path:
    """Write a minimal valid config for validation tests."""
    toml = tmp_path / "estampo.toml"
    toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
    return toml


def _mock_ui_inputs(monkeypatch, inputs):
    """Mock ui prompt functions with an iterator of responses."""
    it = iter(inputs)

    def next_str(prompt, default=None):
        try:
            val = next(it)
        except StopIteration:
            return default or ""
        return val if val != "" else (default or "")

    def next_int(prompt, default=0):
        try:
            val = next(it)
        except StopIteration:
            return default
        return int(val) if val != "" else default

    def next_yn(prompt, default=True):
        try:
            val = next(it)
        except StopIteration:
            return default
        if val == "":
            return default
        return str(val).lower().startswith("y")

    monkeypatch.setattr("estampo.ui.prompt_str", next_str)
    monkeypatch.setattr("estampo.ui.prompt_int", next_int)
    monkeypatch.setattr("estampo.ui.prompt_yn", next_yn)
    monkeypatch.setattr("estampo.ui.prompt_password", lambda prompt: next_str(prompt))
    monkeypatch.setattr("estampo.ui.heading", lambda text: None)
    monkeypatch.setattr("estampo.ui.success", lambda text: None)
    monkeypatch.setattr("estampo.ui.warn", lambda text: None)
    monkeypatch.setattr("estampo.ui.error", lambda text: None)
    monkeypatch.setattr("estampo.ui.info", lambda text: None)
    monkeypatch.setattr("estampo.ui.choice_table", lambda items, columns: None)
    monkeypatch.setattr("estampo.ui.preview_toml", lambda text: None)

    def mock_pick(options, prompt="Pick", allow_multi=False):
        try:
            val = next(it)
        except StopIteration:
            return [0]
        if val == "all":
            return list(range(len(options)))
        try:
            return [int(val) - 1]
        except (ValueError, TypeError):
            return [0]

    monkeypatch.setattr("estampo.ui.pick", mock_pick)


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------


class TestBedTypes:
    def test_matches_orca_2_3_1_enum(self):
        # Source: libslic3r/PrintConfig.cpp curr_bed_type enum_values @ v2.3.1.
        # Order matters: it's the enum ordinal order and the wizard menu order.
        assert BED_TYPES == [
            "Cool Plate",
            "Engineering Plate",
            "High Temp Plate",
            "Textured PEI Plate",
            "Textured Cool Plate",
            "Supertack Plate",
        ]


class TestTemplate:
    def test_dump_template_returns_string(self):
        t = dump_template()
        assert isinstance(t, str)
        assert "[slicer]" in t
        assert "[[parts]]" in t
        assert "[plate]" in t
        assert "[pipeline]" in t

    def test_dump_template_has_comments(self):
        t = dump_template()
        assert "# " in t

    def test_cli_init_template(self, capsys):
        main(["init", "--template"])
        out = capsys.readouterr().out
        assert "[slicer]" in out
        assert "[[parts]]" in out


class TestWorkflow:
    def test_generate_workflow_default_config(self):
        yml = generate_workflow()
        assert "config: estampo.toml" in yml
        assert "estampo/estampo/action@main" in yml
        assert "pull-requests: write" in yml

    def test_generate_workflow_custom_config(self):
        yml = generate_workflow("custom/path.toml")
        assert "config: custom/path.toml" in yml

    def test_write_workflow_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        dest = write_workflow()
        assert dest == Path(".github/workflows/slice.yml")
        assert dest.exists()
        content = dest.read_text()
        assert "estampo/estampo/action@main" in content

    def test_write_workflow_skips_existing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        workflow_dir = tmp_path / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        existing = workflow_dir / "slice.yml"
        existing.write_text("existing content")
        dest = write_workflow()
        assert dest.read_text() == "existing content"

    def test_cli_init_template_with_workflow(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        main(["init", "--template", "--workflow"])
        assert (tmp_path / ".github" / "workflows" / "slice.yml").exists()

    def test_cli_workflow_only_creates_workflow(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "estampo.toml").write_text("[slicer]\nengine = 'orca'\n")
        main(["init", "--workflow-only"])
        assert (tmp_path / ".github" / "workflows" / "slice.yml").exists()

    def test_cli_workflow_only_errors_without_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        main(["init", "--workflow-only"])
        assert not (tmp_path / ".github" / "workflows" / "slice.yml").exists()

    def test_cli_workflow_only_custom_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "custom.toml").write_text("[slicer]\nengine = 'orca'\n")
        main(["init", "--workflow-only", "--output", "custom.toml"])
        content = (tmp_path / ".github" / "workflows" / "slice.yml").read_text()
        assert "config: custom.toml" in content


class TestExtractFrom3MF:
    def test_extracts_profiles(self, tmp_path):
        import json
        import zipfile

        from estampo.init import extract_from_3mf

        threemf = tmp_path / "project.3mf"
        with zipfile.ZipFile(threemf, "w") as zf:
            zf.writestr(
                "Metadata/project_settings.config",
                json.dumps(
                    {
                        "printer_settings_id": "Bambu Lab P1S 0.4 nozzle",
                        "print_settings_id": "0.20mm Standard @BBL X1C",
                        "filament_settings_id": ["Generic PLA @base"],
                        "curr_bed_type": "Textured PEI Plate",
                        "nozzle_type": "stainless_steel",
                        "printable_area": ["0x0", "256x0", "256x256", "0x256"],
                    }
                ),
            )

        toml = extract_from_3mf(threemf)
        assert 'printer = "Bambu Lab P1S 0.4 nozzle"' in toml
        assert 'process = "0.20mm Standard @BBL X1C"' in toml
        assert '"Generic PLA @base"' in toml
        assert 'bed_type = "Textured PEI Plate"' in toml
        assert "machine_overrides" not in toml  # default nozzle, no override

    def test_detects_hardened_steel_nozzle(self, tmp_path):
        import json
        import zipfile

        from estampo.init import extract_from_3mf

        threemf = tmp_path / "project.3mf"
        with zipfile.ZipFile(threemf, "w") as zf:
            zf.writestr(
                "Metadata/project_settings.config",
                json.dumps(
                    {
                        "printer_settings_id": "Bambu Lab P1S 0.4 nozzle",
                        "print_settings_id": "0.20mm Standard @BBL X1C",
                        "filament_settings_id": ["Generic PETG-CF @base"],
                        "nozzle_type": "hardened_steel",
                        "printable_area": ["0x0", "256x0", "256x256", "0x256"],
                    }
                ),
            )

        toml = extract_from_3mf(threemf)
        assert "[slicer.orca.machine_overrides]" in toml
        assert 'nozzle_type = "hardened_steel"' in toml

    def test_missing_settings_raises(self, tmp_path):
        import zipfile

        import pytest

        from estampo import EstampoError
        from estampo.init import extract_from_3mf

        threemf = tmp_path / "empty.3mf"
        with zipfile.ZipFile(threemf, "w") as zf:
            zf.writestr("3D/3dmodel.model", "<model/>")

        with pytest.raises(EstampoError, match="project_settings.config"):
            extract_from_3mf(threemf)

    def test_cli_from_3mf(self, tmp_path, capsys):
        import json
        import zipfile

        threemf = tmp_path / "project.3mf"
        with zipfile.ZipFile(threemf, "w") as zf:
            zf.writestr(
                "Metadata/project_settings.config",
                json.dumps(
                    {
                        "printer_settings_id": "My Printer",
                        "filament_settings_id": ["PLA"],
                        "nozzle_type": "hardened_steel",
                        "printable_area": ["0x0", "200x0", "200x200", "0x200"],
                    }
                ),
            )

        dest = tmp_path / "estampo.toml"
        main(["init", "--from-3mf", str(threemf), "-o", str(dest)])
        assert dest.exists()
        content = dest.read_text()
        assert 'printer = "My Printer"' in content
        assert 'nozzle_type = "hardened_steel"' in content
        assert "size = [200, 200]" in content


# ---------------------------------------------------------------------------
# Validate tests
# ---------------------------------------------------------------------------


class TestValidate:
    def test_valid_config_no_warnings(self, tmp_path):
        # Config with version set — no warnings expected (profiles may not be installed)
        cfg = _write_valid_config(tmp_path)
        result = validate_config(cfg)
        # The only possible warnings are about profiles not being installed,
        # which is environment-dependent. No hard errors should occur.
        assert isinstance(result, ValidationResult)
        assert len(result.passes) > 0

    def test_missing_version_warning(self, tmp_path):
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        warnings = validate_config(toml)
        assert any("version" in w for w in warnings)

    def test_absolute_path_warning(self, tmp_path):
        abs_path = FIXTURES / "cube_10mm.stl"
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[[parts]]
file = "{_posix(abs_path.resolve())}"
""")
        warnings = validate_config(toml)
        assert any("absolute path" in w for w in warnings)

    def test_cli_validate(self, tmp_path, capsys, monkeypatch):
        cfg = _write_valid_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        main(["validate", str(cfg)])
        out = capsys.readouterr().out
        # Should print either "Config OK" or warnings — not crash
        assert "OK" in out or "warning" in out

    def test_cli_validate_auto_discover(self, tmp_path, capsys, monkeypatch):
        _write_valid_config(tmp_path)
        monkeypatch.chdir(tmp_path)
        main(["validate"])
        out = capsys.readouterr().out
        assert "OK" in out or "warning" in out

    def test_cli_validate_missing_config(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(["validate"])
        assert exc_info.value.code == 1

    def test_missing_part_file_hard_error(self, tmp_path):
        """Missing part file is a hard error from load_config, not a warning."""
        from estampo import EstampoError

        toml = tmp_path / "estampo.toml"
        toml.write_text("""
[slicer]
engine = "orca"
version = "2.3.1"

[[parts]]
file = "nonexistent.stl"
""")
        with pytest.raises(EstampoError, match="file not found"):
            validate_config(toml)

    def test_unreadable_part_extension(self, tmp_path):
        bad_file = tmp_path / "model.zip"
        bad_file.write_bytes(b"fake")
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[[parts]]
file = "{_posix(bad_file)}"
""")
        warnings = validate_config(toml)
        assert any("unsupported extension" in w for w in warnings)

    def test_duplicate_part_files(self, tmp_path):
        stl = FIXTURES / "cube_10mm.stl"
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[[parts]]
file = "{_posix(stl)}"

[[parts]]
file = "{_posix(stl)}"
""")
        warnings = validate_config(toml)
        assert any("appears more than once" in w for w in warnings)

    def test_small_plate_warning(self, tmp_path):
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[plate]
size = [10, 10]

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        warnings = validate_config(toml)
        assert any("seems very small" in w for w in warnings)

    def test_large_plate_warning(self, tmp_path):
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[plate]
size = [2000, 2000]

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        warnings = validate_config(toml)
        assert any("seems very large" in w for w in warnings)

    def test_command_stage_not_flagged_unknown(self, tmp_path):
        """Command stages like 'pack' should not trigger 'unknown stage' warnings."""
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[slicer]
engine = "orca"
version = "2.3.1"

[pack]
command = "bambox repack {{sliced_3mf}}"
output = "{{sliced_3mf}}"
docker = true

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        result = validate_config(toml)
        assert not any("unknown" in w for w in result.warnings)
        assert any("pack" in p for p in result.passes)

    def test_missing_executable_warns_without_docker(self, tmp_path):
        """Warn when command stage executable is not on PATH and docker is not set."""
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[slicer]
engine = "orca"
version = "2.3.1"

[pack]
command = "nonexistent_tool_xyz repack {{sliced_3mf}}"
output = "{{sliced_3mf}}"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        result = validate_config(toml)
        assert any("nonexistent_tool_xyz" in w and "docker = true" in w for w in result.warnings)

    def test_no_executable_warning_with_docker_true(self, tmp_path):
        """No warning when docker=true even if executable is not on PATH."""
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[slicer]
engine = "orca"
version = "2.3.1"

[pack]
command = "nonexistent_tool_xyz repack {{sliced_3mf}}"
output = "{{sliced_3mf}}"
docker = true

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        result = validate_config(toml)
        assert not any("nonexistent_tool_xyz" in w for w in result.warnings)

    def test_override_keys_valid_passes(self, tmp_path):
        """Valid override keys produce a pass message."""
        profiles = tmp_path / "profiles" / "orca" / "process"
        profiles.mkdir(parents=True)
        (profiles / "MyProcess.json").write_text(
            '{"type": "process", "layer_height": "0.2", "wall_loops": "2"}'
        )
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[slicer.orca]
process = "MyProcess"

[slicer.orca.overrides]
layer_height = "0.28"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        result = validate_config(toml)
        assert any("override keys valid" in p.lower() for p in result.passes)

    def test_process_printer_compat_mismatch_warns(self, tmp_path):
        """Process listed with an incompatible printer produces a compat warning."""
        process_dir = tmp_path / "profiles" / "orca" / "process"
        process_dir.mkdir(parents=True)
        (process_dir / "HighQuality P1P.json").write_text(
            '{"type": "process", "name": "HighQuality P1P", "layer_height": "0.12", '
            '"compatible_printers": ["Bambu Lab P1P 0.4 nozzle"]}'
        )
        machine_dir = tmp_path / "profiles" / "orca" / "machine"
        machine_dir.mkdir(parents=True)
        (machine_dir / "Bambu Lab P1S 0.4 nozzle.json").write_text(
            '{"type": "machine", "name": "Bambu Lab P1S 0.4 nozzle"}'
        )

        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "HighQuality P1P"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        result = validate_config(toml)
        assert any("not compatible" in w and "exit 239" in w for w in result.warnings)
        assert not any("Process" in p and "compatible with printer" in p for p in result.passes)

    def test_process_printer_compat_match_passes(self, tmp_path):
        """Process whose compatible_printers includes the active printer passes."""
        process_dir = tmp_path / "profiles" / "orca" / "process"
        process_dir.mkdir(parents=True)
        (process_dir / "HighQuality P1S.json").write_text(
            '{"type": "process", "name": "HighQuality P1S", "layer_height": "0.12", '
            '"compatible_printers": ["Bambu Lab P1S 0.4 nozzle"]}'
        )
        machine_dir = tmp_path / "profiles" / "orca" / "machine"
        machine_dir.mkdir(parents=True)
        (machine_dir / "Bambu Lab P1S 0.4 nozzle.json").write_text(
            '{"type": "machine", "name": "Bambu Lab P1S 0.4 nozzle"}'
        )

        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "HighQuality P1S"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        result = validate_config(toml)
        assert not any("not compatible" in w for w in result.warnings)
        assert any("compatible with printer" in p for p in result.passes)

    def test_process_printer_compat_skipped_with_dynamic_condition(self, tmp_path):
        """A compatible_printers_condition expression is dynamic — skip the check."""
        process_dir = tmp_path / "profiles" / "orca" / "process"
        process_dir.mkdir(parents=True)
        (process_dir / "DynamicProcess.json").write_text(
            '{"type": "process", "name": "DynamicProcess", "layer_height": "0.2", '
            '"compatible_printers": ["Bambu Lab P1P 0.4 nozzle"], '
            '"compatible_printers_condition": "nozzle_diameter[0]==0.4"}'
        )
        machine_dir = tmp_path / "profiles" / "orca" / "machine"
        machine_dir.mkdir(parents=True)
        (machine_dir / "Bambu Lab P1S 0.4 nozzle.json").write_text(
            '{"type": "machine", "name": "Bambu Lab P1S 0.4 nozzle"}'
        )

        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "DynamicProcess"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        result = validate_config(toml)
        assert not any("not compatible" in w for w in result.warnings)

    def test_override_keys_unknown_errors(self, tmp_path):
        """Unknown override keys produce errors (not just warnings)."""
        profiles = tmp_path / "profiles" / "orca" / "process"
        profiles.mkdir(parents=True)
        (profiles / "MyProcess.json").write_text('{"type": "process", "layer_height": "0.2"}')
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[slicer.orca]
process = "MyProcess"

[slicer.orca.overrides]
bogus_setting = "42"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        result = validate_config(toml)
        assert result.errors is not None
        assert any("bogus_setting" in e for e in result.errors)

    def test_unknown_key_orca_build_plate_points_to_slicer(self, tmp_path):
        """bed_type misplaced under [slicer.orca] as build_plate — should
        hint to set it in [slicer]."""
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.12mm Fine @BBL X1C"
filaments = ["Generic PLA @base"]
build_plate = "Textured PEI Plate"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        warnings = validate_config(toml)
        matched = [w for w in warnings if "build_plate" in w]
        assert matched, f"expected a warning for build_plate, got: {list(warnings)}"
        assert "bed_type" in matched[0]
        assert "[slicer]" in matched[0]

    def test_unknown_key_orca_exact_parent_match(self, tmp_path):
        """bed_type placed directly under [slicer.orca] — exact match on
        parent table key, should point to [slicer]."""
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
bed_type = "Textured PEI Plate"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        warnings = validate_config(toml)
        matched = [w for w in warnings if "bed_type" in w and "[slicer.orca]" in w]
        assert matched, f"expected a warning for bed_type in [slicer.orca], got: {list(warnings)}"
        assert "[slicer]" in matched[0]

    def test_unknown_key_typo_same_table(self, tmp_path):
        """printr → printer in [slicer.orca]."""
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[slicer.orca]
printr = "Bambu Lab P1S 0.4 nozzle"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        warnings = validate_config(toml)
        matched = [w for w in warnings if "printr" in w]
        assert matched, f"expected a warning for printr, got: {list(warnings)}"
        assert "'printer'" in matched[0]

    def test_unknown_key_parts_typo(self, tmp_path):
        """copys → copies in [[parts]]."""
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
copys = 2
""")
        warnings = validate_config(toml)
        matched = [w for w in warnings if "copys" in w]
        assert matched, f"expected a warning for copys, got: {list(warnings)}"
        assert "'copies'" in matched[0]

    def test_unknown_key_command_stage_typo(self, tmp_path):
        """dcker → docker in a user-defined command-stage table."""
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[pipeline]
stages = ["slice", "pack"]

[pack]
command = "bambox repack {{gcode}} -o {{output}}"
output = "packed.gcode.3mf"
dcker = true

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        warnings = validate_config(toml)
        matched = [w for w in warnings if "dcker" in w]
        assert matched, f"expected a warning for dcker, got: {list(warnings)}"
        assert "'docker'" in matched[0]

    def test_declared_command_stage_not_flagged(self, tmp_path):
        """A top-level table whose name is listed in pipeline.stages is a
        user-defined command stage, not an unknown key."""
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "orca"
version = "2.3.1"

[pipeline]
stages = ["slice", "pack"]

[pack]
command = "bambox repack {{gcode}} -o {{output}}"
output = "packed.gcode.3mf"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        warnings = validate_config(toml)
        assert not any("'pack'" in w and "Unknown" in w for w in warnings)

    def test_unknown_top_level_key(self, tmp_path):
        """A top-level key not in the allow-list and not a declared command
        stage is flagged."""
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
outpt_dir = "./build"

[slicer]
engine = "orca"
version = "2.3.1"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        warnings = validate_config(toml)
        matched = [w for w in warnings if "outpt_dir" in w]
        assert matched, f"expected a warning for outpt_dir, got: {list(warnings)}"
        assert "'output_dir'" in matched[0]

    def test_cura_printer_unreachable_warns(self, tmp_path):
        """Cura printer in bundled name manifest but with no local def.json warns."""
        # `bambox_p1s` is in the bundled Cura name manifest (scraped from the
        # Docker image) but its `.def.json` is not shipped with the pip
        # package, so a local (non-Docker) slice would fail.  Validate must
        # flag this rather than reporting "profiles valid".
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "cura"
version = "5.12.0"

[slicer.cura]
printer = "bambox_p1s"
filaments = ["PLA"]

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        result = validate_config(toml)
        matched = [w for w in result.warnings if "reachable locally" in w]
        assert matched, f"expected a reachability warning, got: {list(result.warnings)}"
        assert "bambox_p1s" in matched[0]
        assert "profiles pin" in matched[0]

    def test_cura_bundled_printer_no_reachability_warning(self, tmp_path):
        """Cura printer whose def.json is bundled does not warn."""
        # `ultimaker2` ships in src/estampo/data/ultimaker2.def.json so the
        # reachability check must find it locally and stay quiet.
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "cura"
version = "5.12.0"

[slicer.cura]
printer = "ultimaker2"
filaments = ["PLA"]

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        result = validate_config(toml)
        assert not any("reachable locally" in w for w in result.warnings)

    def test_cura_pinned_printer_no_reachability_warning(self, tmp_path):
        """Cura printer pinned under profiles/cura/definitions/ does not warn."""
        defs_dir = tmp_path / "profiles" / "cura" / "definitions"
        defs_dir.mkdir(parents=True)
        (defs_dir / "bambox_p1s.def.json").write_text(
            '{"version": 2, "name": "Bambu Lab P1S (bambox)", "inherits": "fdmprinter"}'
        )
        toml = tmp_path / "estampo.toml"
        toml.write_text(f"""
[slicer]
engine = "cura"
version = "5.12.0"

[slicer.cura]
printer = "bambox_p1s"
filaments = ["PLA"]

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""")
        result = validate_config(toml)
        assert not any("reachable locally" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Closest match helper
# ---------------------------------------------------------------------------


class TestClosestMatch:
    def test_substring_match(self):
        candidates = ["Generic PLA @base", "Generic PETG @base"]
        assert _closest_match("PLA", candidates) == "Generic PLA @base"

    def test_no_candidates(self):
        assert _closest_match("PLA", []) is None

    def test_no_match(self):
        result = _closest_match("xyz_nothing", ["abc", "def"])
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# Override validation
# ---------------------------------------------------------------------------


class TestValidateOverride:
    def test_percent_bare_number(self):
        assert _validate_override("25", "percent") == "25%"

    def test_percent_with_sign(self):
        assert _validate_override("25%", "percent") == "25%"

    def test_percent_with_spaces(self):
        assert _validate_override(" 30 ", "percent") == "30%"

    def test_percent_rejects_text(self):
        assert _validate_override("abc", "percent") is None

    def test_percent_rejects_negative(self):
        assert _validate_override("-5", "percent") is None

    def test_percent_rejects_over_100(self):
        assert _validate_override("150", "percent") is None

    def test_percent_zero(self):
        assert _validate_override("0", "percent") == "0%"

    def test_int_valid(self):
        assert _validate_override("3", "int") == "3"

    def test_int_rejects_float(self):
        assert _validate_override("3.5", "int") is None

    def test_int_rejects_text(self):
        assert _validate_override("abc", "int") is None

    def test_int_rejects_negative(self):
        assert _validate_override("-1", "int") is None

    def test_float_valid(self):
        assert _validate_override("0.20", "float") == "0.20"

    def test_float_rejects_zero(self):
        assert _validate_override("0", "float") is None

    def test_float_rejects_text(self):
        assert _validate_override("abc", "float") is None

    def test_text_passthrough(self):
        assert _validate_override("anything", "text") == "anything"

    def test_empty_returns_none(self):
        assert _validate_override("", "percent") is None
        assert _validate_override("  ", "int") is None


# ---------------------------------------------------------------------------
# Interactive picker (ui.pick) — uses questionary
# ---------------------------------------------------------------------------


class TestPick:
    def test_single_select(self, monkeypatch):
        """Single selection returns a one-element list."""
        from unittest.mock import patch

        from estampo import ui

        with patch("questionary.select") as mock_select:
            mock_select.return_value.ask.return_value = "B"
            result = ui.pick(["A", "B", "C"], prompt="Pick")
        assert result == [1]

    def test_multi_select(self, monkeypatch):
        """Multi-select returns a list of indices."""
        from unittest.mock import patch

        from estampo import ui

        with patch("questionary.checkbox") as mock_cb:
            mock_cb.return_value.ask.return_value = ["A", "C"]
            result = ui.pick(["A", "B", "C"], prompt="Pick", allow_multi=True)
        assert result == [0, 2]

    def test_cancel_raises_keyboard_interrupt(self):
        """Cancelling the menu (None) raises KeyboardInterrupt."""
        from unittest.mock import patch

        from estampo import ui

        with patch("questionary.select") as mock_select:
            mock_select.return_value.ask.return_value = None
            try:
                ui.pick(["A", "B"])
                raise AssertionError("Expected KeyboardInterrupt")
            except KeyboardInterrupt:
                pass


# ---------------------------------------------------------------------------
# Build TOML helper
# ---------------------------------------------------------------------------


class TestBuildToml:
    def test_basic(self):
        toml = _build_toml(
            engine="orca",
            printer_profile="Bambu Lab P1S 0.4 nozzle",
            process_profile="0.20mm Standard @BBL X1C",
            filament_names=["Generic PLA @base"],
            parts=[{"file": "cube.stl", "copies": 1, "orient": "flat", "filament": 1}],
            plate_size=(256, 256),
            slicer_version="2.3.1",
            stages=["load", "arrange", "plate", "slice"],
        )
        assert "[slicer]" in toml
        assert 'engine = "orca"' in toml
        assert 'version = "2.3.1"' in toml
        assert "[[parts]]" in toml
        assert 'file = "cube.stl"' in toml

    def test_multiple_copies_shown(self):
        toml = _build_toml(
            engine="orca",
            printer_profile=None,
            process_profile=None,
            filament_names=[],
            parts=[{"file": "a.stl", "copies": 3, "orient": "flat", "filament": 1}],
            plate_size=(256, 256),
            slicer_version=None,
            stages=["load", "arrange", "plate"],
        )
        assert "copies = 3" in toml

    def test_non_default_orient_shown(self):
        toml = _build_toml(
            engine="orca",
            printer_profile=None,
            process_profile=None,
            filament_names=[],
            parts=[{"file": "a.stl", "copies": 1, "orient": "upright", "filament": 1}],
            plate_size=(256, 256),
            slicer_version=None,
            stages=["load", "arrange", "plate"],
        )
        assert 'orient = "upright"' in toml

    def test_overrides_section(self):
        toml = _build_toml(
            engine="orca",
            printer_profile=None,
            process_profile=None,
            filament_names=[],
            parts=[{"file": "a.stl", "copies": 1, "orient": "flat", "filament": 1}],
            plate_size=(256, 256),
            slicer_version=None,
            stages=["load", "arrange", "plate", "slice"],
            overrides={"sparse_infill_density": "25%", "wall_loops": "3"},
        )
        assert "[slicer.orca.overrides]" in toml
        assert 'sparse_infill_density = "25%"' in toml
        assert "wall_loops = 3" in toml

    def test_no_overrides_section(self):
        toml = _build_toml(
            engine="orca",
            printer_profile=None,
            process_profile=None,
            filament_names=[],
            parts=[{"file": "a.stl", "copies": 1, "orient": "flat", "filament": 1}],
            plate_size=(256, 256),
            slicer_version=None,
            stages=["load", "arrange", "plate", "slice"],
            overrides={},
        )
        assert "[slicer.orca.overrides]" not in toml

    def test_defaults_omitted(self):
        """copies=1, orient=flat, filament=1 should not appear in output."""
        toml = _build_toml(
            engine="orca",
            printer_profile=None,
            process_profile=None,
            filament_names=[],
            parts=[{"file": "a.stl", "copies": 1, "orient": "flat", "filament": 1}],
            plate_size=(256, 256),
            slicer_version=None,
            stages=["load", "arrange", "plate"],
        )
        assert "copies" not in toml
        assert "orient" not in toml
        assert "filament" not in toml.split("[[parts]]")[1]

    def test_orca_pack_command_stage(self):
        toml = _build_toml(
            engine="orca",
            printer_profile="Bambu Lab P1S 0.4 nozzle",
            process_profile="0.20mm Standard @BBL X1C",
            filament_names=["Generic PLA @base"],
            parts=[{"file": "cube.stl", "copies": 1, "orient": "flat", "filament": 1}],
            plate_size=(256, 256),
            slicer_version="2.3.1",
            stages=["load", "arrange", "plate", "slice", "pack"],
            command_stages={
                "pack": {
                    "command": "bambox repack {sliced_3mf}",
                    "output": "{sliced_3mf}",
                    "docker": True,
                },
            },
        )
        assert '"pack"' in toml
        assert "[pack]" in toml
        assert "bambox repack" in toml
        assert 'output = "{sliced_3mf}"' in toml
        assert "docker = true" in toml

    def test_cura_resolve_and_pack_stages(self):
        toml = _build_toml(
            engine="cura",
            printer_profile="bambox_p1s",
            process_profile=None,
            filament_names=["PLA"],
            parts=[{"file": "cube.stl", "copies": 1, "orient": "flat", "filament": 1}],
            plate_size=(256, 256),
            slicer_version="5.12.0",
            stages=["load", "arrange", "plate", "slice", "resolve_templates", "pack"],
            command_stages={
                "resolve_templates": {
                    "command": (
                        "cura-p1s resolve {sliced_dir}/plate.gcode --settings {cura_settings}"
                    ),
                    "docker": True,
                },
                "pack": {
                    "command": (
                        "bambox pack {sliced_dir}/plate.gcode -o {output_dir}/plate.gcode.3mf"
                    ),
                    "output": "{output_dir}/plate.gcode.3mf",
                    "docker": True,
                },
            },
        )
        assert '"resolve_templates"' in toml
        assert '"pack"' in toml
        assert "[resolve_templates]" in toml
        assert "cura-p1s resolve" in toml
        assert "docker = true" in toml
        assert "[pack]" in toml
        assert "bambox pack" in toml

    def test_no_command_stages_when_none(self):
        toml = _build_toml(
            engine="orca",
            printer_profile=None,
            process_profile=None,
            filament_names=[],
            parts=[{"file": "a.stl", "copies": 1, "orient": "flat", "filament": 1}],
            plate_size=(256, 256),
            slicer_version=None,
            stages=["load", "arrange", "plate", "slice"],
        )
        assert "[pack]" not in toml
        assert "[resolve_templates]" not in toml


# ---------------------------------------------------------------------------
# _is_bambu_printer
# ---------------------------------------------------------------------------


class TestIsBambuPrinter:
    def test_bambu_lab_detected(self):
        assert _is_bambu_printer("Bambu Lab P1S 0.4 nozzle") is True

    def test_bbl_detected(self):
        assert _is_bambu_printer("0.20mm Standard @BBL X1C") is True

    def test_bambox_detected(self):
        assert _is_bambu_printer("bambox_p1s") is True

    def test_other_printer_not_detected(self):
        assert _is_bambu_printer("Ultimaker 2") is False

    def test_empty_string(self):
        assert _is_bambu_printer("") is False


# ---------------------------------------------------------------------------
# _emit_cura_pin_hint
# ---------------------------------------------------------------------------


class TestEmitCuraPinHint:
    def test_skips_orca_engine(self, tmp_path, monkeypatch):
        """No hint for OrcaSlicer configs — pinning flow is different."""
        calls = []
        monkeypatch.setattr("estampo.ui.warn", lambda msg: calls.append(("warn", msg)))
        monkeypatch.setattr("estampo.ui.info", lambda msg: calls.append(("info", msg)))

        _emit_cura_pin_hint("orca", "Bambu Lab P1S 0.4 nozzle", tmp_path)

        assert calls == []

    def test_skips_when_printer_missing(self, tmp_path, monkeypatch):
        """No hint if the wizard never resolved a printer."""
        calls = []
        monkeypatch.setattr("estampo.ui.warn", lambda msg: calls.append(("warn", msg)))
        monkeypatch.setattr("estampo.ui.info", lambda msg: calls.append(("info", msg)))

        _emit_cura_pin_hint("cura", None, tmp_path)

        assert calls == []

    def test_skips_when_def_reachable(self, tmp_path, monkeypatch):
        """No hint when the cura def is already pinned or bundled."""
        calls = []
        monkeypatch.setattr("estampo.ui.warn", lambda msg: calls.append(("warn", msg)))
        monkeypatch.setattr("estampo.ui.info", lambda msg: calls.append(("info", msg)))
        monkeypatch.setattr("estampo.init._check_cura_def_reachable", lambda *a, **kw: None)

        _emit_cura_pin_hint("cura", "bambox_p1s", tmp_path)

        assert calls == []

    def test_emits_next_step_when_unreachable(self, tmp_path, monkeypatch):
        """Warns and prints a next-step hint when the def is Docker-only."""
        calls = []
        monkeypatch.setattr("estampo.ui.warn", lambda msg: calls.append(("warn", msg)))
        monkeypatch.setattr("estampo.ui.info", lambda msg: calls.append(("info", msg)))
        monkeypatch.setattr(
            "estampo.init._check_cura_def_reachable",
            lambda *a, **kw: "def unreachable",
        )

        _emit_cura_pin_hint("cura", "bambox_p1s", tmp_path)

        assert any(kind == "warn" and "bambox_p1s" in msg for kind, msg in calls)
        assert any(kind == "info" and "estampo profiles pin" in msg for kind, msg in calls)


# ---------------------------------------------------------------------------
# Wizard (non-interactive, mocked input)
# ---------------------------------------------------------------------------


def _empty_profiles(*args, **kwargs):
    return {"machine": [], "process": [], "filament": []}, "none"


class TestWizard:
    def test_wizard_with_mocked_input(self, tmp_path, monkeypatch):
        """Wizard should produce valid TOML when given mocked inputs."""
        from estampo.init import run_wizard

        monkeypatch.chdir(tmp_path)

        # Create a fake STL so it gets discovered
        (tmp_path / "test-part.stl").write_bytes(b"fake stl")

        _mock_ui_inputs(
            monkeypatch,
            [
                "1",  # Engine choice (OrcaSlicer)
                "my-project",  # Project name
                "1",  # Select files
                "1",  # copies
                "flat",  # orient
                "My Printer 0.4 nozzle",  # Printer profile name
                "0.20mm Standard @base",  # Process profile name
                "256",  # plate width
                "256",  # plate depth
                "",  # slicer version (skip)
                "Generic PLA @base",  # Filament name
                "",  # Bed type (skip)
                "1",  # Nozzle type (stainless_steel)
                "n",  # Add slicer overrides? -> no
                "w",  # Write / Go back / Quit
            ],
        )

        # Mock profile discovery to return empty (no slicer installed in CI)
        monkeypatch.setattr("estampo.profiles.discover_profile_names", _empty_profiles)
        # Mock slicer version discovery so we don't hit DockerHub
        monkeypatch.setattr("estampo.orca._fetch_available_versions", lambda: [])
        monkeypatch.setattr("estampo.orca._detect_orca_version", lambda: None)

        result = run_wizard()
        assert "[slicer]" in result
        assert "test-part.stl" in result
        assert 'name = "my-project"' in result
        assert (tmp_path / "estampo.toml").exists()

    def test_wizard_no_write(self, tmp_path, monkeypatch):
        """Wizard should not write if user declines."""
        from estampo.init import run_wizard

        monkeypatch.chdir(tmp_path)

        _mock_ui_inputs(
            monkeypatch,
            [
                "1",  # Engine choice (OrcaSlicer)
                "",  # Project name (use default)
                "my-part.stl",  # Part file path
                "My Printer",  # Printer profile name
                "My Process",  # Process profile name
                "256",  # plate width
                "256",  # plate depth
                "",  # slicer version (skip)
                "My PLA",  # Filament name
                "",  # Bed type (skip)
                "1",  # Nozzle type (stainless_steel)
                "n",  # Add slicer overrides? -> no
                "q",  # Write / Go back / Quit
            ],
        )
        monkeypatch.setattr("estampo.profiles.discover_profile_names", _empty_profiles)
        # Mock slicer version discovery so we don't hit DockerHub
        monkeypatch.setattr("estampo.orca._fetch_available_versions", lambda: [])
        monkeypatch.setattr("estampo.orca._detect_orca_version", lambda: None)

        run_wizard()
        assert not (tmp_path / "estampo.toml").exists()


# ---------------------------------------------------------------------------
# _check_cura_template_gcode tests
# ---------------------------------------------------------------------------


class TestCheckCuraTemplateGcode:
    """Tests for _check_cura_template_gcode (#557)."""

    def _make_cfg(self, tmp_path, *, has_resolve_stage=False):
        """Create a minimal CuraEngine config with pinned definition containing templates."""
        import json

        # Create a pinned definition with template variables in start gcode
        defs_dir = tmp_path / "profiles" / "cura" / "definitions"
        defs_dir.mkdir(parents=True)
        (defs_dir / "bambox_p1s.def.json").write_text(
            json.dumps(
                {
                    "name": "Bambu P1S",
                    "inherits": "fdmprinter",
                    "overrides": {
                        "machine_start_gcode": {
                            "default_value": (
                                "M104 S{material_print_temperature_layer_0}\n"
                                "M140 S{material_bed_temperature_layer_0}\n"
                            ),
                        },
                    },
                }
            )
        )

        # Create a dummy part file so config parses
        dummy_stl = tmp_path / "part.stl"
        dummy_stl.write_bytes(b"solid\nendsolid\n")

        stages = ["load", "arrange", "plate", "slice"]
        toml_lines = [
            "[pipeline]",
            "stages = {}".format(
                json.dumps(stages + (["resolve_templates", "pack"] if has_resolve_stage else []))
            ),
            "",
            "[slicer]",
            'engine = "cura"',
            "",
            "[slicer.cura]",
            'printer = "bambox_p1s"',
            "",
            "[[parts]]",
            'file = "part.stl"',
        ]
        if has_resolve_stage:
            toml_lines += [
                "",
                "[resolve_templates]",
                'command = "cura-p1s resolve {sliced_dir}/plate.gcode --settings {cura_settings}"',
                "docker = true",
                "",
                "[pack]",
                'command = "bambox pack {sliced_dir}/plate.gcode -o {output_dir}/plate.gcode.3mf"',
                'output = "{output_dir}/plate.gcode.3mf"',
                "docker = true",
            ]

        toml_path = tmp_path / "estampo.toml"
        toml_path.write_text("\n".join(toml_lines))

        from estampo.config import load_config

        return load_config(toml_path)

    def test_error_when_no_resolve_stage(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = self._make_cfg(tmp_path, has_resolve_stage=False)
        warnings: list[str] = []
        errors: list[str] = []
        _check_cura_template_gcode(cfg, warnings, errors)
        assert len(errors) == 1
        assert "template variables" in errors[0]
        assert "resolve_templates" in errors[0]
        assert "docker = true" in errors[0]

    def test_no_error_when_resolve_stage_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = self._make_cfg(tmp_path, has_resolve_stage=True)
        warnings: list[str] = []
        errors: list[str] = []
        _check_cura_template_gcode(cfg, warnings, errors)
        assert errors == []

    def test_no_error_when_no_templates(self, tmp_path, monkeypatch):
        """No error when start gcode has no template variables."""
        import json

        monkeypatch.chdir(tmp_path)
        dummy_stl = tmp_path / "part.stl"
        dummy_stl.write_bytes(b"solid\nendsolid\n")
        defs_dir = tmp_path / "profiles" / "cura" / "definitions"
        defs_dir.mkdir(parents=True)
        (defs_dir / "bambox_p1s.def.json").write_text(
            json.dumps(
                {
                    "name": "Bambu P1S",
                    "inherits": "fdmprinter",
                    "overrides": {
                        "machine_start_gcode": {
                            "default_value": "G28\nG1 Z5 F3000\n",
                        },
                    },
                }
            )
        )
        toml_path = tmp_path / "estampo.toml"
        toml_path.write_text(
            '[pipeline]\nstages = ["load", "arrange", "plate", "slice"]\n'
            "[slicer]\n"
            'engine = "cura"\n'
            "[slicer.cura]\n"
            'printer = "bambox_p1s"\n'
            "[[parts]]\n"
            'file = "part.stl"\n'
        )
        from estampo.config import load_config

        cfg = load_config(toml_path)
        warnings: list[str] = []
        errors: list[str] = []
        _check_cura_template_gcode(cfg, warnings, errors)
        assert errors == []


# ---------------------------------------------------------------------------
# build_config_toml tests (#560)
# ---------------------------------------------------------------------------


class TestBuildConfigTomlCommandStages:
    """Tests for auto-generated command stages in build_config_toml."""

    def test_cura_bambu_adds_resolve_and_pack(self):
        toml = build_config_toml(
            engine="cura",
            printer="bambox_p1s",
            filaments=["PLA"],
            parts=["part.stl"],
        )
        assert "resolve_templates" in toml
        assert "cura-p1s resolve" in toml
        assert "bambox pack" in toml
        assert '"resolve_templates", "pack"' in toml
        assert "docker = true" in toml

    def test_orca_bambu_adds_pack_only(self):
        toml = build_config_toml(
            engine="orca",
            printer="Bambu Lab P1S 0.4 nozzle",
            filaments=["PLA"],
            parts=["part.stl"],
        )
        assert "resolve_templates" not in toml
        assert "bambox repack" in toml
        assert '"pack"' in toml
        assert "docker = true" in toml

    def test_non_bambu_no_command_stages(self):
        toml = build_config_toml(
            engine="cura",
            printer="creality_ender3",
            filaments=["PLA"],
            parts=["part.stl"],
        )
        assert "resolve_templates" not in toml
        assert "bambox" not in toml

    def test_explicit_stages_with_pack_not_duplicated(self):
        toml = build_config_toml(
            engine="cura",
            printer="bambox_p1s",
            filaments=["PLA"],
            parts=["part.stl"],
            stages=["load", "arrange", "plate", "slice", "pack"],
        )
        # Should not add a second pack
        assert toml.count('"pack"') == 1

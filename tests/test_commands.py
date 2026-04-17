"""Tests for command stages — external CLI tools as pipeline stages."""

import subprocess
from pathlib import Path

import pytest

from estampo import EstampoError
from estampo.commands import (
    COMMAND_VARIABLES,
    CommandStageConfig,
    build_command_context,
    parse_command_stage,
    run_command_stage,
)
from estampo.config import (
    CuraSlicerConfig,
    EstampoConfig,
    OrcaSlicerConfig,
    PartConfig,
    PipelineConfig,
    PlateConfig,
    SlicerConfig,
    load_config,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _posix(p: Path) -> str:
    return p.as_posix()


# ---------------------------------------------------------------------------
# Contract: COMMAND_VARIABLES matches build_command_context (#390)
# ---------------------------------------------------------------------------


class TestCommandVariablesContract:
    """COMMAND_VARIABLES dict must stay in sync with build_command_context()."""

    def test_context_keys_match_command_variables(self, tmp_path):
        """build_command_context() returns exactly the keys in COMMAND_VARIABLES."""
        cfg = _make_config(tmp_path)
        ctx = build_command_context(cfg, tmp_path / "output", {})
        assert set(ctx.keys()) == set(COMMAND_VARIABLES.keys())

    def test_context_keys_with_full_results(self, tmp_path):
        """Keys remain the same regardless of what stage_results contain."""
        cfg = _make_config(tmp_path)
        results = {
            "plate_3mf_path": tmp_path / "plate.3mf",
            "packaged_output": tmp_path / "output",
            "sliced_output_dir": tmp_path / "sliced",
        }
        ctx = build_command_context(cfg, tmp_path / "output", results)
        assert set(ctx.keys()) == set(COMMAND_VARIABLES.keys())

    def test_all_values_are_strings(self, tmp_path):
        """Every context value is a string (safe for format_map)."""
        cfg = _make_config(tmp_path)
        ctx = build_command_context(cfg, tmp_path / "output", {})
        for key, value in ctx.items():
            assert isinstance(value, str), f"{key} is {type(value)}, expected str"


# ---------------------------------------------------------------------------
# build_command_context values
# ---------------------------------------------------------------------------


class TestBuildCommandContext:
    def test_populates_name_from_config(self, tmp_path):
        cfg = _make_config(tmp_path, name="my-project")
        ctx = build_command_context(cfg, tmp_path / "out", {})
        assert ctx["name"] == "my-project"

    def test_name_empty_when_unset(self, tmp_path):
        cfg = _make_config(tmp_path)
        ctx = build_command_context(cfg, tmp_path / "out", {})
        assert ctx["name"] == ""

    def test_output_dir_is_string(self, tmp_path):
        cfg = _make_config(tmp_path)
        out = tmp_path / "build_output"
        ctx = build_command_context(cfg, out, {})
        assert ctx["output_dir"] == str(out)

    def test_machine_from_active_engine(self, tmp_path):
        cfg = _make_config(tmp_path, printer="Bambu Lab P1S 0.4 nozzle")
        ctx = build_command_context(cfg, tmp_path / "out", {})
        assert ctx["machine"] == "Bambu Lab P1S 0.4 nozzle"

    def test_engine_from_config(self, tmp_path):
        cfg = _make_config(tmp_path)
        ctx = build_command_context(cfg, tmp_path / "out", {})
        assert ctx["engine"] == "orca"

    def test_stage_results_populate_paths(self, tmp_path):
        cfg = _make_config(tmp_path)
        plate = tmp_path / "plate.3mf"
        sliced = tmp_path / "sliced"
        results = {
            "plate_3mf_path": plate,
            "packaged_output": sliced,
            "sliced_output_dir": sliced,
        }
        ctx = build_command_context(cfg, tmp_path / "out", results)
        assert ctx["input_3mf"] == str(plate)
        assert ctx["sliced_3mf"] == str(sliced)
        assert ctx["sliced_dir"] == str(sliced)

    def test_missing_results_default_to_empty(self, tmp_path):
        cfg = _make_config(tmp_path)
        ctx = build_command_context(cfg, tmp_path / "out", {})
        assert ctx["input_3mf"] == ""
        assert ctx["sliced_3mf"] == ""
        assert ctx["sliced_dir"] == ""

    def test_filament_single(self, tmp_path):
        cfg = _make_config(tmp_path, filaments=["Generic PLA @base"])
        ctx = build_command_context(cfg, tmp_path / "out", {})
        assert ctx["filament"] == "Generic PLA @base"
        assert ctx["filaments"] == "Generic PLA @base"

    def test_filament_multiple(self, tmp_path):
        cfg = _make_config(tmp_path, filaments=["Generic PLA @base", "Generic PETG @base"])
        ctx = build_command_context(cfg, tmp_path / "out", {})
        assert ctx["filament"] == "Generic PLA @base"
        assert ctx["filaments"] == "Generic PLA @base,Generic PETG @base"

    def test_filament_empty_when_unset(self, tmp_path):
        cfg = _make_config(tmp_path)
        ctx = build_command_context(cfg, tmp_path / "out", {})
        assert ctx["filament"] == ""
        assert ctx["filaments"] == ""

    def test_filament_from_cura_engine(self, tmp_path):
        cfg = _make_config(tmp_path, engine="cura", filaments=["PLA"])
        ctx = build_command_context(cfg, tmp_path / "out", {})
        assert ctx["filament"] == "PLA"

    def test_cura_settings_populated_when_file_exists(self, tmp_path):
        sliced = tmp_path / "sliced"
        sliced.mkdir()
        settings = sliced / "cura_settings.json"
        settings.write_text("{}")
        cfg = _make_config(tmp_path, engine="cura")
        results = {"sliced_output_dir": sliced}
        ctx = build_command_context(cfg, tmp_path / "out", results)
        assert ctx["cura_settings"] == str(settings)

    def test_cura_settings_empty_for_orca_engine(self, tmp_path):
        sliced = tmp_path / "sliced"
        sliced.mkdir()
        (sliced / "cura_settings.json").write_text("{}")
        cfg = _make_config(tmp_path, engine="orca")
        results = {"sliced_output_dir": sliced}
        ctx = build_command_context(cfg, tmp_path / "out", results)
        assert ctx["cura_settings"] == ""

    def test_cura_settings_empty_when_no_file(self, tmp_path):
        cfg = _make_config(tmp_path, engine="cura")
        ctx = build_command_context(cfg, tmp_path / "out", {})
        assert ctx["cura_settings"] == ""


# ---------------------------------------------------------------------------
# parse_command_stage
# ---------------------------------------------------------------------------


class TestParseCommandStage:
    def test_valid_stage(self):
        raw = {"command": "bambox pack {sliced_3mf}", "output": "{output_dir}/out.3mf"}
        stage = parse_command_stage("pack", raw)
        assert stage.name == "pack"
        assert stage.command == "bambox pack {sliced_3mf}"
        assert stage.output == "{output_dir}/out.3mf"

    def test_command_only_no_output(self):
        raw = {"command": "echo hello"}
        stage = parse_command_stage("greet", raw)
        assert stage.name == "greet"
        assert stage.output is None

    def test_missing_command_raises(self):
        with pytest.raises(EstampoError, match="missing 'command' key"):
            parse_command_stage("bad", {})

    def test_empty_command_raises(self):
        with pytest.raises(EstampoError, match="non-empty string"):
            parse_command_stage("bad", {"command": ""})

    def test_empty_output_raises(self):
        with pytest.raises(EstampoError, match="non-empty string"):
            parse_command_stage("bad", {"command": "echo", "output": ""})


# ---------------------------------------------------------------------------
# run_command_stage
# ---------------------------------------------------------------------------


class TestRunCommandStage:
    def test_successful_command(self, tmp_path):
        stage = CommandStageConfig(name="test", command="echo hello")
        ctx = {"name": "proj", "output_dir": str(tmp_path)}
        result = run_command_stage(stage, ctx)
        assert result is None  # no output defined

    def test_successful_command_with_output(self, tmp_path):
        outfile = tmp_path / "result.txt"
        stage = CommandStageConfig(
            name="test",
            command=f"touch {outfile}",
            output=str(outfile),
        )
        ctx = {}
        result = run_command_stage(stage, ctx)
        assert result == outfile

    def test_substitution_works(self, tmp_path):
        stage = CommandStageConfig(
            name="test",
            command="echo {name}",
        )
        ctx = {"name": "my-project"}
        # Should not raise
        run_command_stage(stage, ctx)

    def test_missing_variable_raises(self):
        stage = CommandStageConfig(name="test", command="echo {nonexistent}")
        ctx = {"name": "proj"}
        with pytest.raises(EstampoError, match="unknown variable.*nonexistent"):
            run_command_stage(stage, ctx)

    def test_missing_variable_in_output_raises(self):
        stage = CommandStageConfig(name="test", command="echo ok", output="{bogus}/file.txt")
        ctx = {"name": "proj"}
        with pytest.raises(EstampoError, match="unknown variable.*bogus"):
            run_command_stage(stage, ctx)

    def test_nonzero_exit_raises(self):
        stage = CommandStageConfig(name="fail", command="false")
        ctx = {}
        with pytest.raises(EstampoError, match="failed.*exit code"):
            run_command_stage(stage, ctx)

    def test_available_variables_in_error_message(self):
        stage = CommandStageConfig(name="test", command="echo {nope}")
        ctx = {"name": "proj", "output_dir": "/tmp"}
        with pytest.raises(EstampoError, match="Available variables:.*name.*output_dir"):
            run_command_stage(stage, ctx)

    def test_timeout(self):
        stage = CommandStageConfig(name="slow", command="sleep 10")
        ctx = {}
        with pytest.raises(subprocess.TimeoutExpired):
            run_command_stage(stage, ctx, timeout=1)


# ---------------------------------------------------------------------------
# TOML parsing integration
# ---------------------------------------------------------------------------


class TestTomlCommandStages:
    def test_command_stage_parsed_from_toml(self, tmp_path):
        toml = tmp_path / "estampo.toml"
        stl = tmp_path / "cube.stl"
        stl.touch()
        toml.write_text(f"""
[pipeline]
stages = ["load", "arrange", "plate", "pack"]

[plate]
size = [256, 256]

[slicer]
engine = "orca"

[pack]
command = "bambox pack {{sliced_3mf}} -o {{output_dir}}"
output = "{{output_dir}}/packed.3mf"

[[parts]]
file = "{_posix(stl)}"
""")
        cfg = load_config(toml)
        assert "pack" in cfg.pipeline.command_stages
        pack = cfg.pipeline.command_stages["pack"]
        assert pack.command == "bambox pack {sliced_3mf} -o {output_dir}"
        assert pack.output == "{output_dir}/packed.3mf"

    def test_unknown_stage_without_command_section_raises(self, tmp_path):
        toml = tmp_path / "estampo.toml"
        stl = tmp_path / "cube.stl"
        stl.touch()
        toml.write_text(f"""
[pipeline]
stages = ["load", "arrange", "plate", "mystery"]

[plate]
size = [256, 256]

[slicer]
engine = "orca"

[[parts]]
file = "{_posix(stl)}"
""")
        with pytest.raises(EstampoError, match="unknown stage 'mystery'"):
            load_config(toml)

    def test_builtin_stages_still_work(self, tmp_path):
        toml = tmp_path / "estampo.toml"
        stl = tmp_path / "cube.stl"
        stl.touch()
        toml.write_text(f"""
[pipeline]
stages = ["load", "arrange", "plate"]

[plate]
size = [256, 256]

[slicer]
engine = "orca"

[[parts]]
file = "{_posix(stl)}"
""")
        cfg = load_config(toml)
        assert cfg.pipeline.command_stages == {}
        assert cfg.pipeline.stages == ["load", "arrange", "plate"]

    def test_mixed_builtin_and_command_stages(self, tmp_path):
        toml = tmp_path / "estampo.toml"
        stl = tmp_path / "cube.stl"
        stl.touch()
        toml.write_text(f"""
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack", "repack"]

[plate]
size = [256, 256]

[slicer]
engine = "orca"

[pack]
command = "bambox pack {{sliced_3mf}}"

[repack]
command = "bambox repack {{sliced_3mf}}"
output = "{{output_dir}}/repacked.3mf"

[[parts]]
file = "{_posix(stl)}"
""")
        cfg = load_config(toml)
        assert len(cfg.pipeline.command_stages) == 2
        assert "pack" in cfg.pipeline.command_stages
        assert "repack" in cfg.pipeline.command_stages


# ---------------------------------------------------------------------------
# resolve_outputs with command stages
# ---------------------------------------------------------------------------


class TestResolveOutputsWithCommandStages:
    def test_command_stages_skipped_in_hamilton_outputs(self):
        from estampo.pipeline import resolve_outputs

        stages = ["load", "arrange", "plate", "pack"]
        outputs = resolve_outputs(stages, command_stages={"pack"})
        assert "loaded_parts" in outputs
        assert "plate_3mf_path" in outputs
        # pack is a command stage, not a Hamilton node

    def test_until_command_stage(self):
        from estampo.pipeline import resolve_outputs

        stages = ["load", "arrange", "plate", "pack"]
        outputs = resolve_outputs(stages, until="pack", command_stages={"pack"})
        assert "plate_3mf_path" in outputs

    def test_only_command_stage_returns_upstream(self):
        from estampo.pipeline import resolve_outputs

        stages = ["load", "arrange", "plate", "pack"]
        outputs = resolve_outputs(stages, only="pack", command_stages={"pack"})
        # Should return the last built-in stage's outputs
        assert "plate_3mf_path" in outputs or "preview_path" in outputs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    tmp_path: Path,
    name: str | None = None,
    printer: str | None = None,
    filaments: list[str] | None = None,
    engine: str = "orca",
) -> EstampoConfig:
    """Create a minimal EstampoConfig for testing."""
    stl = tmp_path / "cube.stl"
    stl.touch()

    return EstampoConfig(
        plate=PlateConfig(),
        slicer=SlicerConfig(
            engine=engine,
            orca=OrcaSlicerConfig(printer=printer, filaments=filaments or []),
            cura=CuraSlicerConfig(filaments=filaments or []),
        ),
        parts=[PartConfig(file=stl)],
        base_dir=tmp_path,
        name=name,
        pipeline=PipelineConfig(),
    )

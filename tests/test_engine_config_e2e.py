"""End-to-end tests for engine-namespaced config → slicer dispatch.

These tests verify the full flow from TOML loading through config parsing,
profile resolution, and slicer dispatch for both OrcaSlicer and CuraEngine,
using the engine-namespaced format.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from estampo import EstampoError
from estampo.config import load_config

FIXTURES = Path(__file__).parent / "fixtures"


def _posix(p: Path) -> str:
    return str(p).replace("\\", "/")


def _write_toml(tmp_path: Path, content: str, create_files: list[str] | None = None) -> Path:
    toml_path = tmp_path / "estampo.toml"
    toml_path.write_text(content)
    for f in create_files or []:
        (tmp_path / f).touch()
    return toml_path


# ---------------------------------------------------------------------------
# Config loading: new format → facade fields
# ---------------------------------------------------------------------------


class TestOrcaConfigE2E:
    """Orca config through the full load → facade → sub-config chain."""

    def test_new_format_full_config(self, tmp_path):
        """Full orca config with all fields in new namespaced format."""
        path = _write_toml(
            tmp_path,
            f"""
name = "test-project"

[plate]
size = [256, 256]

[slicer]
engine = "orca"
version = "2.3.2"
bed_type = "Textured PEI Plate"
profiles_dir = "profiles"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"
filaments = ["Generic PETG", "Generic PLA @base"]

[slicer.orca.overrides]
sparse_infill_density = "30%"
wall_loops = 4

[slicer.orca.machine_overrides]
nozzle_type = "hardened_steel"

[slicer.orca.filament_overrides]
filament_retraction_length = "0.8"

[slicer.orca.slots]
1 = "Generic PETG"
2 = "Generic PLA @base"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        cfg = load_config(path)

        # Common fields
        assert cfg.slicer.engine == "orca"
        assert cfg.slicer.version == "2.3.2"
        assert cfg.slicer.bed_type == "Textured PEI Plate"
        assert cfg.slicer.profiles_dir == "profiles"

        # Active property returns orca sub-config
        assert cfg.slicer.active is cfg.slicer.orca
        assert cfg.slicer.orca.printer == "Bambu Lab P1S 0.4 nozzle"
        assert cfg.slicer.orca.process == "0.20mm Standard @BBL X1C"
        assert cfg.slicer.orca.filaments == ["Generic PETG", "Generic PLA @base"]
        assert cfg.slicer.orca.overrides == {"sparse_infill_density": "30%", "wall_loops": 4}
        assert cfg.slicer.orca.machine_overrides == {"nozzle_type": "hardened_steel"}
        assert cfg.slicer.orca.filament_overrides == {"filament_retraction_length": "0.8"}
        assert cfg.slicer.orca.slots == {1: "Generic PETG", 2: "Generic PLA @base"}

        # Cura sub-config is empty (not configured)
        assert cfg.slicer.cura.overrides == {}

    def test_legacy_format_rejected(self, tmp_path):
        """Legacy flat format is rejected with a clear error."""
        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "orca"
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"
filaments = ["Generic PLA @base"]

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        with pytest.raises(EstampoError, match="no longer supported"):
            load_config(path)

    def test_legacy_minimal_no_warning(self, tmp_path):
        """Minimal config with only engine= does NOT emit deprecation."""
        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "orca"
version = "2.3.2"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        # No deprecation warning when there are no legacy-specific keys
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            cfg = load_config(path)

        assert cfg.slicer.engine == "orca"
        assert cfg.slicer.version == "2.3.2"

    def test_orca_profile_resolution_with_pinned(self, tmp_path):
        """New-format config resolves pinned profiles via facade fields."""
        # Create pinned profile
        profiles = tmp_path / "profiles" / "orca" / "process"
        profiles.mkdir(parents=True)
        (profiles / "MyProcess.json").write_text(
            json.dumps({"type": "process", "layer_height": "0.20", "wall_loops": "3"})
        )

        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "orca"
version = "2.3.2"

[slicer.orca]
process = "MyProcess"

[slicer.orca.overrides]
wall_loops = 5

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        cfg = load_config(path)

        # Verify active engine fields work for profile resolution
        from estampo.profiles import resolve_profile_data

        data = resolve_profile_data(
            cfg.slicer.orca.process,
            cfg.slicer.engine,
            "process",
            cfg.base_dir,
            cfg.slicer.profiles_dir,
        )
        assert data["layer_height"] == "0.20"
        assert data["wall_loops"] == "3"  # pre-override value

    def test_orca_validate_overrides_new_format(self, tmp_path):
        """validate_override_keys works with new-format config facade."""
        profiles = tmp_path / "profiles" / "orca" / "process"
        profiles.mkdir(parents=True)
        (profiles / "MyProcess.json").write_text(
            json.dumps({"type": "process", "layer_height": "0.20", "wall_loops": "3"})
        )

        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "orca"
version = "2.3.2"

[slicer.orca]
process = "MyProcess"

[slicer.orca.overrides]
bogus_key = "42"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        cfg = load_config(path)

        from estampo.profiles import validate_override_keys

        warnings = validate_override_keys(
            cfg.slicer.orca.overrides,
            cfg.slicer.engine,
            cfg.slicer.orca.process,
            project_dir=cfg.base_dir,
        )
        assert any("bogus_key" in w for w in warnings)


class TestCuraConfigE2E:
    """Cura config through the full load → facade → slicer dispatch chain."""

    def test_new_format_full_config(self, tmp_path):
        """Full cura config with overrides in new namespaced format."""
        path = _write_toml(
            tmp_path,
            f"""
name = "cura-test"

[slicer]
engine = "cura"
version = "5.12.0"
bed_type = "Textured PEI Plate"

[slicer.cura.overrides]
infill_sparse_density = 30
support_structure = "tree"
layer_height = 0.12

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        cfg = load_config(path)

        # Common fields
        assert cfg.slicer.engine == "cura"
        assert cfg.slicer.version == "5.12.0"
        assert cfg.slicer.bed_type == "Textured PEI Plate"

        # Active property points to cura sub-config
        assert cfg.slicer.active is cfg.slicer.cura
        assert cfg.slicer.cura.printer is None
        assert cfg.slicer.cura.overrides == {
            "infill_sparse_density": 30,
            "support_structure": "tree",
            "layer_height": 0.12,
        }

    def test_build_cura_config_integration(self, tmp_path):
        """Config → build_cura_config → raw overrides dict passthrough."""
        from estampo.cura import build_cura_config

        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "cura"
version = "5.12.0"
bed_type = "Engineering Plate"

[slicer.cura.overrides]
layer_height = 0.12
wall_line_count = 5
infill_sparse_density = 30

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        cfg = load_config(path)

        overrides, per_extruder = build_cura_config(
            overrides=cfg.slicer.cura.overrides,
            bed_type=cfg.slicer.bed_type,
        )
        assert overrides["layer_height"] == 0.12
        assert overrides["wall_line_count"] == 5
        assert overrides["infill_sparse_density"] == 30
        assert overrides["machine_buildplate_type"] == "engineering_plate"
        assert per_extruder == []

    def test_cura_slice_dispatch(self, tmp_path):
        """Config with engine=cura dispatches to cura.slice_stl."""
        import trimesh

        from estampo.slicer import slice_plate

        input_3mf = tmp_path / "plate.3mf"
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        scene = trimesh.Scene(mesh)
        scene.export(str(input_3mf))
        output_dir = tmp_path / "output"

        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "cura"
version = "5.12.0"
bed_type = "Textured PEI Plate"

[slicer.cura.overrides]
infill_sparse_density = 30

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        cfg = load_config(path)

        with patch("estampo.cura.slice_stl", return_value=output_dir) as mock_slice:
            result = slice_plate(
                input_3mf,
                engine=cfg.slicer.engine,
                output_dir=output_dir,
                overrides=cfg.slicer.cura.overrides or None,
                bed_type=cfg.slicer.bed_type,
                docker_version=cfg.slicer.version,
            )

        assert result == output_dir
        mock_slice.assert_called_once()
        call_kwargs = mock_slice.call_args.kwargs
        overrides = call_kwargs["overrides"]
        assert overrides["infill_sparse_density"] == 30
        assert overrides["machine_buildplate_type"] == "textured_pei_plate"

    def test_cura_settings_flags_from_config(self, tmp_path):
        """Config overrides flow through to CuraEngine -s flags."""
        from estampo.cura import _settings_flags, build_cura_config

        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "cura"
version = "5.12.0"

[slicer.cura.overrides]
layer_height = 0.28
support_enable = true

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        cfg = load_config(path)
        overrides, _ = build_cura_config(overrides=cfg.slicer.cura.overrides)
        flags = _settings_flags(overrides)

        values = flags[1::2]
        flag_dict = {}
        for v in values:
            k, val = v.split("=", 1)
            flag_dict[k] = val

        assert flag_dict["layer_height"] == "0.28"
        assert flag_dict["support_enable"] == "True"


class TestDualEngineConfig:
    """Both engines configured in one TOML — engine field selects active."""

    def test_switch_orca_to_cura(self, tmp_path):
        """Switching engine from orca to cura changes active sub-config."""
        toml_content = """
[slicer]
engine = "{engine}"
version = "2.3.2"
bed_type = "Textured PEI Plate"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"
filaments = ["Generic PETG"]

[slicer.orca.overrides]
sparse_infill_density = "30%"

[slicer.cura.overrides]
infill_sparse_density = 25
support_structure = "tree"

[[parts]]
file = "{part}"
"""
        part = _posix(FIXTURES / "cube_10mm.stl")

        # Load as orca
        path = _write_toml(
            tmp_path,
            toml_content.format(engine="orca", part=part),
        )
        cfg_orca = load_config(path)
        assert cfg_orca.slicer.active is cfg_orca.slicer.orca
        assert cfg_orca.slicer.orca.printer == "Bambu Lab P1S 0.4 nozzle"
        assert cfg_orca.slicer.orca.overrides == {"sparse_infill_density": "30%"}

        # Reload as cura — active switches to cura sub-config
        path.write_text(toml_content.format(engine="cura", part=part))
        cfg_cura = load_config(path)
        assert cfg_cura.slicer.active is cfg_cura.slicer.cura
        assert cfg_cura.slicer.cura.overrides == {
            "infill_sparse_density": 25,
            "support_structure": "tree",
        }

        # Both sub-configs always populated regardless of active engine
        assert cfg_cura.slicer.orca.printer == "Bambu Lab P1S 0.4 nozzle"

    def test_validate_both_engines(self, tmp_path):
        """Validation works correctly for each engine's profile chain."""
        from estampo.init import validate_config

        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "cura"
version = "5.12.0"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"

[slicer.cura.overrides]
infill_sparse_density = 25

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        result = validate_config(path)
        # Cura is active — no profile chain to validate, so no profile warnings
        # (cura doesn't look up printer/process/filament profiles)
        assert not any("printer" in w.lower() and "not found" in w.lower() for w in result.warnings)


class TestLegacyRejection:
    """Legacy flat format is rejected with a clear error."""

    def test_legacy_orca_rejected(self, tmp_path):
        """Legacy flat orca config is rejected."""
        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "orca"
version = "2.3.2"
process = "TestProcess"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        with pytest.raises(EstampoError, match="no longer supported"):
            load_config(path)

    def test_cura_overrides_at_slicer_level_ok(self, tmp_path):
        """engine=cura with [slicer.overrides] (not a legacy key) is fine."""
        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "cura"
version = "5.12.0"

[slicer.cura]

[slicer.cura.overrides]
infill_sparse_density = 25

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        cfg = load_config(path)
        assert cfg.slicer.engine == "cura"

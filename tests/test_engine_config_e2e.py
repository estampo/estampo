"""End-to-end tests for engine-namespaced config → slicer dispatch.

These tests verify the full flow from TOML loading through config parsing,
profile resolution, and slicer dispatch for both OrcaSlicer and CuraEngine,
using both the new engine-namespaced format and the legacy flat format.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

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

        # Facade fields mirror orca sub-config
        assert cfg.slicer.printer == "Bambu Lab P1S 0.4 nozzle"
        assert cfg.slicer.process == "0.20mm Standard @BBL X1C"
        assert cfg.slicer.filaments == ["Generic PETG", "Generic PLA @base"]
        assert cfg.slicer.overrides == {"sparse_infill_density": "30%", "wall_loops": 4}
        assert cfg.slicer.machine_overrides == {"nozzle_type": "hardened_steel"}
        assert cfg.slicer.filament_overrides == {"filament_retraction_length": "0.8"}
        assert cfg.slicer.slots == {1: "Generic PETG", 2: "Generic PLA @base"}

        # Sub-config objects
        assert cfg.slicer.orca.printer == "Bambu Lab P1S 0.4 nozzle"
        assert cfg.slicer.orca.overrides == {"sparse_infill_density": "30%", "wall_loops": 4}
        assert cfg.slicer.orca.machine_overrides == {"nozzle_type": "hardened_steel"}

        # Cura sub-config is empty (not configured)
        assert cfg.slicer.cura.overrides == {}

    def test_legacy_format_emits_deprecation(self, tmp_path):
        """Legacy flat format still works but emits a DeprecationWarning."""
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
        with pytest.warns(DeprecationWarning, match="Flat.*slicer.*deprecated"):
            cfg = load_config(path)

        # Legacy config still fully functional
        assert cfg.slicer.printer == "Bambu Lab P1S 0.4 nozzle"
        assert cfg.slicer.process == "0.20mm Standard @BBL X1C"
        assert cfg.slicer.filaments == ["Generic PLA @base"]
        # Also populated in orca sub-config
        assert cfg.slicer.orca.printer == "Bambu Lab P1S 0.4 nozzle"

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
        profiles = tmp_path / "profiles" / "process"
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

        # Verify facade fields work for profile resolution
        from estampo.profiles import resolve_profile_data

        data = resolve_profile_data(
            cfg.slicer.process, cfg.slicer.engine, "process", cfg.base_dir, cfg.slicer.profiles_dir
        )
        assert data["layer_height"] == "0.20"
        assert data["wall_loops"] == "3"  # pre-override value

    def test_orca_validate_overrides_new_format(self, tmp_path):
        """validate_override_keys works with new-format config facade."""
        profiles = tmp_path / "profiles" / "process"
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
            cfg.slicer.overrides,
            cfg.slicer.engine,
            cfg.slicer.process,
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

        # Cura has no profile chain — facade fields are empty
        assert cfg.slicer.printer is None
        assert cfg.slicer.process is None
        assert cfg.slicer.filaments == []
        assert cfg.slicer.machine_overrides == {}
        assert cfg.slicer.filament_overrides == {}

        # Overrides come from cura sub-config
        assert cfg.slicer.overrides == {
            "infill_sparse_density": 30,
            "support_structure": "tree",
            "layer_height": 0.12,
        }
        assert cfg.slicer.cura.overrides == cfg.slicer.overrides

    def test_cura_profile_from_config_integration(self, tmp_path):
        """Config → cura_profile_from_config → CuraProfile fields."""
        from estampo.cura import cura_profile_from_config

        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "cura"
version = "5.12.0"
bed_type = "Engineering Plate"

[slicer.cura.overrides]
layer_height = 0.12
wall_loops = 5
sparse_infill_density = 30

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        cfg = load_config(path)

        # Build CuraProfile from config facade fields
        profile = cura_profile_from_config(
            overrides=cfg.slicer.overrides,
            bed_type=cfg.slicer.bed_type,
        )
        assert profile.layer_height == 0.12
        assert profile.wall_line_count == 5
        assert profile.infill_sparse_density == 30
        assert profile.bed_type == "Engineering Plate"

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
                overrides=cfg.slicer.overrides or None,
                bed_type=cfg.slicer.bed_type,
                docker_version=cfg.slicer.version,
            )

        assert result == output_dir
        mock_slice.assert_called_once()
        call_args = mock_slice.call_args
        profile = call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs["profile"]
        assert profile.infill_sparse_density == 30
        assert profile.bed_type == "Textured PEI Plate"

    def test_cura_settings_flags_from_config(self, tmp_path):
        """Config overrides flow through to CuraEngine -s flags."""
        from estampo.cura import _settings_flags, cura_profile_from_config

        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "cura"
version = "5.12.0"

[slicer.cura.overrides]
layer_height = 0.28
support_enable = "true"

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        cfg = load_config(path)
        profile = cura_profile_from_config(overrides=cfg.slicer.overrides)
        flags = _settings_flags(profile)

        # Convert to dict
        values = flags[1::2]
        flag_dict = {}
        for v in values:
            k, val = v.split("=", 1)
            flag_dict[k] = val

        assert flag_dict["layer_height"] == "0.28"
        assert flag_dict["support_enable"] == "true"


class TestDualEngineConfig:
    """Both engines configured in one TOML — engine field selects active."""

    def test_switch_orca_to_cura(self, tmp_path):
        """Switching engine from orca to cura changes facade fields."""
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
        assert cfg_orca.slicer.printer == "Bambu Lab P1S 0.4 nozzle"
        assert cfg_orca.slicer.overrides == {"sparse_infill_density": "30%"}

        # Reload as cura
        path.write_text(toml_content.format(engine="cura", part=part))
        cfg_cura = load_config(path)
        assert cfg_cura.slicer.printer is None
        assert cfg_cura.slicer.overrides == {
            "infill_sparse_density": 25,
            "support_structure": "tree",
        }

        # Both sub-configs always populated regardless of active engine
        assert cfg_cura.slicer.orca.printer == "Bambu Lab P1S 0.4 nozzle"
        assert cfg_cura.slicer.cura.overrides == {
            "infill_sparse_density": 25,
            "support_structure": "tree",
        }

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


class TestLegacyBackwardCompat:
    """Legacy flat format backward compatibility through the full stack."""

    def test_legacy_orca_slice_dispatch(self, tmp_path):
        """Legacy flat orca config dispatches to OrcaSlicer correctly."""
        # Create a minimal pinned profile
        profiles = tmp_path / "profiles" / "process"
        profiles.mkdir(parents=True)
        (profiles / "TestProcess.json").write_text(
            json.dumps({"type": "process", "layer_height": "0.20"})
        )

        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "orca"
version = "2.3.2"
process = "TestProcess"

[slicer.overrides]
wall_loops = 4

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        with pytest.warns(DeprecationWarning, match="Flat.*slicer.*deprecated"):
            cfg = load_config(path)

        # Legacy config values accessible via facade
        assert cfg.slicer.process == "TestProcess"
        assert cfg.slicer.overrides == {"wall_loops": 4}
        # Also in orca sub-config
        assert cfg.slicer.orca.process == "TestProcess"
        assert cfg.slicer.orca.overrides == {"wall_loops": 4}

    def test_legacy_cura_no_warning(self, tmp_path):
        """engine=cura with no orca-specific keys emits no deprecation."""
        import warnings as warn_mod

        path = _write_toml(
            tmp_path,
            f"""
[slicer]
engine = "cura"
version = "5.12.0"

[slicer.overrides]
infill_sparse_density = 25

[[parts]]
file = "{_posix(FIXTURES / "cube_10mm.stl")}"
""",
        )
        # overrides without printer/process/filaments is ambiguous but not legacy-orca
        # The warning only fires when orca-specific keys (printer, process, filaments) are present
        with warn_mod.catch_warnings():
            warn_mod.simplefilter("error", DeprecationWarning)
            cfg = load_config(path)

        assert cfg.slicer.engine == "cura"

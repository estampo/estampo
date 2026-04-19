"""Tests for profile discovery, resolution, and pinning."""

import json
from unittest.mock import patch

import pytest

from estampo.profiles import (
    SYSTEM_DIRS,
    _extract_names,
    _resolve_profile_data_from_dir,
    add_profile,
    detect_category,
    discover_profile_names,
    discover_profiles,
    load_bundled_profiles,
    pin_profiles,
    pinned_profiles_version,
    resolve_profile,
    resolve_profile_data,
    validate_override_keys,
)

ORCA_SYSTEM = SYSTEM_DIRS.get("orca")


def _has_orca():
    return ORCA_SYSTEM is not None and ORCA_SYSTEM.is_dir()


@pytest.mark.skipif(not _has_orca(), reason="OrcaSlicer not installed")
def test_discover_orca():
    profiles = discover_profiles("orca")
    assert "machine" in profiles
    assert "process" in profiles
    assert "filament" in profiles
    assert "Bambu Lab P1S 0.4 nozzle" in profiles["machine"]
    assert "0.20mm Standard @BBL X1C" in profiles["process"]


@pytest.mark.skipif(not _has_orca(), reason="OrcaSlicer not installed")
def test_resolve_from_system():
    path = resolve_profile("Bambu Lab P1S 0.4 nozzle", "orca", "machine")
    assert path.exists()
    assert path.name == "Bambu Lab P1S 0.4 nozzle.json"


def test_resolve_path_directly(tmp_path):
    profile = tmp_path / "custom.json"
    profile.write_text("{}")
    path = resolve_profile(str(profile), "orca", "machine")
    assert path == profile


def test_resolve_pinned_first(tmp_path):
    """Pinned profiles should take precedence over system profiles."""
    pinned_dir = tmp_path / "profiles" / "orca" / "machine"
    pinned_dir.mkdir(parents=True)
    pinned = pinned_dir / "MyProfile.json"
    pinned.write_text("{}")
    path = resolve_profile("MyProfile", "orca", "machine", project_dir=tmp_path)
    assert path == pinned


def test_resolve_not_found():
    with pytest.raises(FileNotFoundError, match="not found"):
        resolve_profile("Nonexistent Printer", "orca", "machine")


def test_resolve_path_traversal_rejected():
    """Paths containing '..' should be rejected to prevent traversal."""
    with pytest.raises(ValueError, match="must not contain"):
        resolve_profile("../../etc/passwd", "orca", "machine")


def test_discover_unknown_engine():
    with pytest.raises(ValueError, match="Unknown engine"):
        discover_profiles("nonexistent")


def test_discover_cura_returns_empty():
    """CuraEngine uses inline settings — discover_profiles returns empty dicts."""
    result = discover_profiles("cura")
    assert all(v == {} for v in result.values())


@pytest.mark.skipif(not _has_orca(), reason="OrcaSlicer not installed")
def test_pin_profiles(tmp_path):
    pinned = pin_profiles(
        engine="orca",
        printer="Bambu Lab P1S 0.4 nozzle",
        process="0.20mm Standard @BBL X1C",
        filaments=["Generic PLA @base"],
        project_dir=tmp_path,
    )
    assert len(pinned) == 3
    assert (tmp_path / "profiles" / "orca" / "machine" / "Bambu Lab P1S 0.4 nozzle.json").exists()
    assert (tmp_path / "profiles" / "orca" / "process" / "0.20mm Standard @BBL X1C.json").exists()
    assert (tmp_path / "profiles" / "orca" / "filament" / "Generic PLA @base.json").exists()

    # Verify pinned files are valid JSON
    for p in pinned:
        json.loads(p.read_text())


def test_resolve_profile_data_flattens_inheritance(tmp_path):
    """Verify resolve_profile_data merges the full inheritance chain."""
    # Create a 2-level inheritance chain in a fake system dir
    cat_dir = tmp_path / "profiles" / "process"
    cat_dir.mkdir(parents=True)

    root = {"from": "system", "wall_loops": 2, "enable_support": 0, "infill": "grid"}
    cat_dir.joinpath("root.json").write_text(json.dumps(root))

    child = {"from": "system", "inherits": "root", "wall_loops": 3}
    cat_dir.joinpath("child.json").write_text(json.dumps(child))

    data = resolve_profile_data(str(cat_dir / "child.json"), "orca", "process", tmp_path)
    # Child overrides wall_loops, inherits enable_support and infill from root
    assert data["wall_loops"] == 3
    assert data["enable_support"] == 0
    assert data["infill"] == "grid"
    # inherits key must be stripped
    assert "inherits" not in data


@pytest.mark.skipif(not _has_orca(), reason="OrcaSlicer not installed")
def test_resolve_profile_data_real_process():
    """Verify real OrcaSlicer process profile resolves enable_support."""
    data = resolve_profile_data("0.20mm Standard @BBL X1C", "orca", "process")
    # Must have enable_support from the root of the chain
    assert "enable_support" in data
    # Must not have inherits (fully flattened)
    assert "inherits" not in data
    # Should have many keys from the full chain
    assert len(data) > 50


# ---------------------------------------------------------------------------
# Bundled profiles
# ---------------------------------------------------------------------------


def test_load_bundled_profiles_exact_version(tmp_path):
    """Load bundled profiles when exact version file exists."""
    data = {"machine": ["PrinterA"], "process": ["Fast"], "filament": ["PLA"]}
    bundled = tmp_path / "profiles.orca.2.3.1.json"
    bundled.write_text(json.dumps(data))

    with patch("estampo.profiles._BUNDLED_DIR", tmp_path):
        result = load_bundled_profiles("orca", "2.3.1")
    assert result["machine"] == ["PrinterA"]
    assert result["process"] == ["Fast"]
    assert result["filament"] == ["PLA"]


def test_load_bundled_profiles_fallback_to_highest(tmp_path):
    """When version doesn't match, fall back to highest available."""
    old = {"machine": ["Old"]}
    new = {"machine": ["New"], "process": ["P"]}
    (tmp_path / "profiles.orca.2.2.0.json").write_text(json.dumps(old))
    (tmp_path / "profiles.orca.2.3.1.json").write_text(json.dumps(new))

    with patch("estampo.profiles._BUNDLED_DIR", tmp_path):
        result = load_bundled_profiles("orca", "9.9.9")
    assert result["machine"] == ["New"]


def test_load_bundled_profiles_no_version(tmp_path):
    """When no version given, fall back to highest available."""
    data = {"machine": ["M1"]}
    (tmp_path / "profiles.orca.1.0.0.json").write_text(json.dumps(data))

    with patch("estampo.profiles._BUNDLED_DIR", tmp_path):
        result = load_bundled_profiles("orca")
    assert result["machine"] == ["M1"]


def test_load_bundled_profiles_missing(tmp_path):
    """Return empty dict when no bundled profiles exist."""
    with patch("estampo.profiles._BUNDLED_DIR", tmp_path):
        result = load_bundled_profiles("orca", "2.3.1")
    assert result == {}


def test_bundled_profiles_exist():
    """Real bundled profiles must be shipped with the package."""
    from estampo.profiles import _BUNDLED_DIR

    profiles = sorted(_BUNDLED_DIR.glob("profiles.orca.*.json"))
    assert profiles, f"No bundled profiles found in {_BUNDLED_DIR}"


def test_bundled_profiles_valid():
    """Bundled profile files must be valid JSON with required structure."""
    from estampo.profiles import _BUNDLED_DIR

    for path in sorted(_BUNDLED_DIR.glob("profiles.orca.*.json")):
        data = json.load(open(path))
        assert data.get("engine") == "orca", f"{path.name}: bad engine"
        assert "version" in data, f"{path.name}: missing version"
        for cat in ("machine", "process", "filament"):
            assert cat in data, f"{path.name}: missing {cat}"
            assert isinstance(data[cat], list), f"{path.name}: {cat} not a list"
            assert len(data[cat]) > 0, f"{path.name}: {cat} is empty"


def test_bundled_profiles_loadable():
    """load_bundled_profiles returns real data from shipped profiles."""
    result = load_bundled_profiles("orca")
    assert result, "load_bundled_profiles returned empty — profiles not bundled?"
    assert len(result["machine"]) > 10, "Expected many machine profiles"
    assert len(result["process"]) > 10, "Expected many process profiles"
    assert len(result["filament"]) > 10, "Expected many filament profiles"


# ---------------------------------------------------------------------------
# _extract_names
# ---------------------------------------------------------------------------


def test_extract_names_plain_strings():
    assert _extract_names(["A", "B"]) == ["A", "B"]


def test_extract_names_cura_dicts_include_id():
    """CuraEngine manifests with id field should include both name and id."""
    items = [{"name": "Bambu Lab P1S (bambox)", "id": "bambox_p1s"}]
    names = _extract_names(items)
    assert "Bambu Lab P1S (bambox)" in names
    assert "bambox_p1s" in names


def test_extract_names_skips_duplicate_id():
    """When id equals name, don't duplicate."""
    items = [{"name": "same", "id": "same"}]
    assert _extract_names(items) == ["same"]


def test_extract_names_mixed():
    """Handles a mix of strings and dicts."""
    items = ["plain", {"name": "Display", "id": "def_id"}]
    names = _extract_names(items)
    assert names == ["plain", "Display", "def_id"]


# ---------------------------------------------------------------------------
# discover_profile_names
# ---------------------------------------------------------------------------


def test_discover_profile_names_system_first():
    """System profiles take priority when available."""
    fake_system = {"machine": {"Printer": {}}, "process": {}, "filament": {}}
    with patch("estampo.profiles.discover_profiles", return_value=fake_system):
        names, source = discover_profile_names("orca")
    assert source == "system"
    assert "Printer" in names["machine"]


def test_discover_profile_names_pinned_fallback(tmp_path):
    """Falls back to pinned profiles when system is empty."""
    pinned_dir = tmp_path / "profiles" / "orca" / "machine"
    pinned_dir.mkdir(parents=True)
    (pinned_dir / "MyPrinter.json").write_text("{}")

    with patch("estampo.profiles.discover_profiles", return_value={}):
        names, source = discover_profile_names("orca", project_dir=tmp_path)
    assert source == "pinned"
    assert "MyPrinter" in names["machine"]


def test_discover_profile_names_pinned_cura_includes_id(tmp_path):
    """Pinned CuraEngine definitions include both display name and def ID."""
    defs_dir = tmp_path / "profiles" / "cura" / "definitions"
    defs_dir.mkdir(parents=True)
    (defs_dir / "bambox_p1s.def.json").write_text(
        json.dumps({"name": "Bambu Lab P1S (bambox)", "overrides": {}})
    )

    with patch("estampo.profiles.discover_profiles", return_value={}):
        names, source = discover_profile_names("cura", project_dir=tmp_path)
    assert source == "pinned"
    assert "Bambu Lab P1S (bambox)" in names["machine"]
    assert "bambox_p1s" in names["machine"]


def test_discover_profile_names_bundled_fallback(tmp_path):
    """Falls back to bundled profiles when no system or pinned."""
    bundled = {"machine": ["Bundled"], "process": [], "filament": []}
    with (
        patch("estampo.profiles.discover_profiles", return_value={}),
        patch("estampo.profiles.load_bundled_profiles", return_value=bundled),
    ):
        names, source = discover_profile_names("orca", version="2.3.1")
    assert source == "bundled"
    assert names["machine"] == ["Bundled"]


def test_discover_profile_names_none(tmp_path):
    """Returns 'none' when no profiles found anywhere."""
    with (
        patch("estampo.profiles.discover_profiles", return_value={}),
        patch("estampo.profiles.load_bundled_profiles", return_value={}),
    ):
        names, source = discover_profile_names("orca", version="2.3.1")
    assert source == "none"
    assert all(v == [] for v in names.values())


# ---------------------------------------------------------------------------
# _resolve_profile_data_from_dir
# ---------------------------------------------------------------------------


def test_resolve_profile_data_from_dir_simple(tmp_path):
    """Resolve a single profile with no inheritance."""
    cat_dir = tmp_path / "process"
    cat_dir.mkdir()
    (cat_dir / "Fast.json").write_text(json.dumps({"layer_height": 0.3}))

    data = _resolve_profile_data_from_dir("Fast", "process", tmp_path)
    assert data["layer_height"] == 0.3


def test_resolve_profile_data_from_dir_inheritance(tmp_path):
    """Resolve a profile chain: child inherits from parent."""
    cat_dir = tmp_path / "process"
    cat_dir.mkdir()
    (cat_dir / "Base.json").write_text(json.dumps({"layer_height": 0.2, "wall_loops": 2}))
    (cat_dir / "Child.json").write_text(json.dumps({"inherits": "Base", "wall_loops": 4}))

    data = _resolve_profile_data_from_dir("Child", "process", tmp_path)
    assert data["layer_height"] == 0.2  # inherited
    assert data["wall_loops"] == 4  # overridden
    assert "inherits" not in data


def test_resolve_profile_data_from_dir_cycle(tmp_path):
    """Circular inheritance doesn't loop forever."""
    cat_dir = tmp_path / "process"
    cat_dir.mkdir()
    (cat_dir / "A.json").write_text(json.dumps({"inherits": "B", "a": 1}))
    (cat_dir / "B.json").write_text(json.dumps({"inherits": "A", "b": 2}))

    data = _resolve_profile_data_from_dir("A", "process", tmp_path)
    assert data["a"] == 1
    assert data["b"] == 2


def test_resolve_profile_data_from_dir_not_found(tmp_path):
    """Missing profile raises FileNotFoundError."""
    (tmp_path / "process").mkdir()
    with pytest.raises(FileNotFoundError, match="not found"):
        _resolve_profile_data_from_dir("Nope", "process", tmp_path)


def test_resolve_profile_data_from_dir_base_dir_fallback(tmp_path):
    """Parent in base_dir/category is found via fallback when not a sibling."""
    cat_dir = tmp_path / "process"
    cat_dir.mkdir()
    (cat_dir / "Parent.json").write_text(
        json.dumps({"use_relative_e_distances": "0", "layer_height": 0.2})
    )
    (cat_dir / "Child.json").write_text(json.dumps({"inherits": "Parent", "layer_height": 0.3}))

    data = _resolve_profile_data_from_dir("Child", "process", tmp_path)
    assert data["layer_height"] == 0.3  # child override
    assert data["use_relative_e_distances"] == "0"  # inherited from parent
    assert "inherits" not in data


def test_resolve_profile_data_from_dir_warns_missing_parent(tmp_path, caplog):
    """Warning is logged when parent profile is not found."""
    import logging

    cat_dir = tmp_path / "process"
    cat_dir.mkdir()
    (cat_dir / "Orphan.json").write_text(
        json.dumps({"inherits": "MissingParent", "layer_height": 0.2})
    )

    with caplog.at_level(logging.WARNING):
        data = _resolve_profile_data_from_dir("Orphan", "process", tmp_path)
    assert data["layer_height"] == 0.2
    assert "MissingParent" in caplog.text


def test_resolve_profile_data_docker_dir_fallback(tmp_path):
    """Parent profile is found in docker_profile_dir during chain walk."""
    # Set up: child in project pinned profiles, parent only in docker dir
    project = tmp_path / "project"
    pinned = project / "profiles" / "orca" / "process"
    pinned.mkdir(parents=True)
    (pinned / "Child.json").write_text(json.dumps({"inherits": "DockerParent", "wall_loops": 4}))

    docker_dir = tmp_path / "docker"
    docker_process = docker_dir / "process"
    docker_process.mkdir(parents=True)
    (docker_process / "DockerParent.json").write_text(
        json.dumps({"wall_loops": 2, "use_relative_e_distances": "0"})
    )

    data = resolve_profile_data(
        "Child",
        "orca",
        "process",
        project_dir=project,
        docker_profile_dir=docker_dir,
    )
    assert data["wall_loops"] == 4  # child override
    assert data["use_relative_e_distances"] == "0"  # inherited via docker fallback
    assert "inherits" not in data


def test_resolve_profile_data_warns_missing_parent(tmp_path, caplog):
    """Warning is logged when parent is not found in any location."""
    import logging

    project = tmp_path / "project"
    pinned = project / "profiles" / "orca" / "process"
    pinned.mkdir(parents=True)
    (pinned / "Lonely.json").write_text(json.dumps({"inherits": "Ghost", "layer_height": 0.2}))

    with caplog.at_level(logging.WARNING):
        data = resolve_profile_data("Lonely", "orca", "process", project_dir=project)
    assert data["layer_height"] == 0.2
    assert "Ghost" in caplog.text


# ---------------------------------------------------------------------------
# detect_category
# ---------------------------------------------------------------------------


def test_detect_category_machine():
    data = {"printer_model": "P1S", "machine_start_gcode": "G28"}
    assert detect_category(data) == "machine"


def test_detect_category_process():
    data = {"layer_height": 0.2, "wall_loops": 3, "sparse_infill_density": "15%"}
    assert detect_category(data) == "process"


def test_detect_category_filament():
    data = {"filament_type": "PLA", "filament_density": 1.24}
    assert detect_category(data) == "filament"


def test_detect_category_unknown():
    data = {"random_key": 42}
    assert detect_category(data) is None


# ---------------------------------------------------------------------------
# add_profile
# ---------------------------------------------------------------------------


def test_add_profile_from_file(tmp_path):
    """Import a local JSON file into profiles/."""
    src = tmp_path / "my_process.json"
    src.write_text(json.dumps({"layer_height": 0.15, "wall_loops": 3}))

    project = tmp_path / "project"
    project.mkdir()

    dest = add_profile(str(src), project, category="process")
    assert dest.exists()
    assert dest.parent.name == "process"
    assert json.loads(dest.read_text())["layer_height"] == 0.15


def test_add_profile_auto_detect_category(tmp_path):
    """Category is auto-detected from JSON keys."""
    src = tmp_path / "pla.json"
    src.write_text(json.dumps({"filament_type": "PLA", "filament_density": 1.24}))

    dest = add_profile(str(src), tmp_path)
    assert dest.parent.name == "filament"


def test_add_profile_custom_name(tmp_path):
    """Custom name overrides filename."""
    src = tmp_path / "generic.json"
    src.write_text(json.dumps({"filament_type": "PETG"}))

    dest = add_profile(str(src), tmp_path, category="filament", name="MyPETG")
    assert dest.name == "MyPETG.json"


def test_add_profile_invalid_json(tmp_path):
    """Invalid JSON raises EstampoError."""
    src = tmp_path / "bad.json"
    src.write_text("not json")

    from estampo import EstampoError

    with pytest.raises(EstampoError, match="Invalid JSON"):
        add_profile(str(src), tmp_path, category="process")


def test_add_profile_not_found(tmp_path):
    from estampo import EstampoError

    with pytest.raises(EstampoError, match="not found"):
        add_profile("/nonexistent/file.json", tmp_path, category="process")


def test_add_profile_invalid_category(tmp_path):
    src = tmp_path / "p.json"
    src.write_text(json.dumps({"x": 1}))

    from estampo import EstampoError

    with pytest.raises(EstampoError, match="Invalid category"):
        add_profile(str(src), tmp_path, category="bogus")


def test_add_profile_warns_on_unresolved_inherits(tmp_path, caplog):
    """Warns when imported profile inherits from a missing parent."""
    src = tmp_path / "child.json"
    src.write_text(json.dumps({"inherits": "MissingParent", "layer_height": 0.2}))

    import logging

    with caplog.at_level(logging.WARNING):
        add_profile(str(src), tmp_path, category="process")
    assert "MissingParent" in caplog.text


# ---------------------------------------------------------------------------
# pin_profiles Docker fallback (mocked)
# ---------------------------------------------------------------------------


def test_pin_profiles_docker_fallback(tmp_path):
    """Docker fallback is invoked when local resolution fails."""
    # Set up a fake Docker-extracted directory
    docker_dir = tmp_path / "docker_profiles"
    machine_dir = docker_dir / "machine"
    machine_dir.mkdir(parents=True)
    (machine_dir / "DockerPrinter.json").write_text(
        json.dumps({"printer_model": "test", "nozzle_diameter": [0.4]})
    )

    project = tmp_path / "project"
    project.mkdir()

    with patch("estampo.profiles.extract_docker_profiles", return_value=docker_dir):
        pinned = pin_profiles(
            engine="orca",
            printer="DockerPrinter",
            process=None,
            filaments=[],
            project_dir=project,
            docker_version="2.3.1",
        )

    assert len(pinned) == 1
    assert pinned[0].name == "DockerPrinter.json"
    data = json.loads(pinned[0].read_text())
    assert data["printer_model"] == "test"


def test_pin_profiles_docker_overrides_system(tmp_path, monkeypatch):
    """Docker-extracted profiles take priority over local system profiles."""
    # Set up a fake system profile dir with a "stale" layer_change_gcode
    system_dir = tmp_path / "system" / "machine"
    system_dir.mkdir(parents=True)
    (system_dir / "TestPrinter.json").write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "TestPrinter",
                "from": "system",
                "layer_change_gcode": "stale gcode from local install",
            }
        )
    )
    monkeypatch.setattr("estampo.profiles.SYSTEM_DIRS", {"orca": system_dir.parent})

    # Set up Docker-extracted profiles with the correct gcode
    docker_dir = tmp_path / "docker_profiles"
    docker_machine = docker_dir / "machine"
    docker_machine.mkdir(parents=True)
    (docker_machine / "TestPrinter.json").write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "TestPrinter",
                "from": "system",
                "layer_change_gcode": "correct gcode with G92 E0",
            }
        )
    )

    project = tmp_path / "project"
    project.mkdir()

    with patch("estampo.profiles.extract_docker_profiles", return_value=docker_dir):
        pinned = pin_profiles(
            engine="orca",
            printer="TestPrinter",
            process=None,
            filaments=[],
            project_dir=project,
            docker_version="2.3.1",
        )

    assert len(pinned) == 1
    data = json.loads(pinned[0].read_text())
    # Must use Docker profile, NOT the stale system profile
    assert data["layer_change_gcode"] == "correct gcode with G92 E0"


def test_pin_profiles_docker_flattens_inheritance(tmp_path):
    """Docker pinning walks the full inheritance chain and flattens correctly.

    Regression test: a truncated chain produced pinned profiles missing
    layer_change_gcode (with G92 E0), causing OrcaSlicer validation errors.
    """
    docker_dir = tmp_path / "docker_profiles"
    machine_dir = docker_dir / "machine"
    machine_dir.mkdir(parents=True)

    # Root profile — base settings, no layer_change_gcode
    (machine_dir / "base_common.json").write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "base_common",
                "from": "system",
                "gcode_flavor": "marlin",
            }
        )
    )

    # Mid-chain profile — adds layer_change_gcode with G92 E0
    (machine_dir / "mid_common.json").write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "mid_common",
                "from": "system",
                "inherits": "base_common",
                "layer_change_gcode": "M622 J1\nG92 E0\nM623\nM73 L{layer_num+1}",
            }
        )
    )

    # Leaf profile — overrides layer_change_gcode (still has G92 E0)
    (machine_dir / "MyPrinter 0.4 nozzle.json").write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "MyPrinter 0.4 nozzle",
                "from": "system",
                "inherits": "mid_common",
                "printer_model": "MyPrinter",
                "layer_change_gcode": "M622 J1\nG92 E0\nG1 X65\nM623\nM73 L{layer_num+1}",
            }
        )
    )

    project = tmp_path / "project"
    project.mkdir()

    with patch("estampo.profiles.extract_docker_profiles", return_value=docker_dir):
        pinned = pin_profiles(
            engine="orca",
            printer="MyPrinter 0.4 nozzle",
            process=None,
            filaments=[],
            project_dir=project,
            docker_version="2.3.1",
        )

    assert len(pinned) == 1
    data = json.loads(pinned[0].read_text())

    # Leaf values override parents
    assert data["printer_model"] == "MyPrinter"
    assert "G92 E0" in data["layer_change_gcode"]
    assert "G1 X65" in data["layer_change_gcode"]  # leaf-specific addition
    # Root values inherited
    assert data["gcode_flavor"] == "marlin"
    # Inheritance key must be stripped
    assert "inherits" not in data


def test_pin_profiles_repin_overwrites_stale(tmp_path):
    """Re-pinning replaces an existing stale pinned profile with Docker data."""
    # Pre-existing stale pinned profile (missing G92 E0)
    project = tmp_path / "project"
    pinned_dir = project / "profiles" / "machine"
    pinned_dir.mkdir(parents=True)
    (pinned_dir / "Printer.json").write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "Printer",
                "from": "system",
                "layer_change_gcode": "stale — no G92 E0",
            }
        )
    )

    # Docker profiles with correct data
    docker_dir = tmp_path / "docker_profiles"
    docker_machine = docker_dir / "machine"
    docker_machine.mkdir(parents=True)
    (docker_machine / "Printer.json").write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "Printer",
                "from": "system",
                "layer_change_gcode": "G92 E0\nM73 L{layer_num+1}",
            }
        )
    )

    with patch("estampo.profiles.extract_docker_profiles", return_value=docker_dir):
        pinned = pin_profiles(
            engine="orca",
            printer="Printer",
            process=None,
            filaments=[],
            project_dir=project,
            docker_version="2.3.1",
        )

    assert len(pinned) == 1
    data = json.loads(pinned[0].read_text())
    # Docker profile must replace the stale pinned data
    assert "G92 E0" in data["layer_change_gcode"]


def test_pin_profiles_no_docker_version_raises(tmp_path):
    """Without docker_version, missing profiles raise EstampoError."""
    project = tmp_path / "project"
    project.mkdir()

    from estampo import EstampoError

    with pytest.raises(EstampoError, match="not found locally"):
        pin_profiles(
            engine="orca",
            printer="NonexistentPrinter",
            process=None,
            filaments=[],
            project_dir=project,
        )


def test_pin_profiles_cura_no_profiles_returns_empty(tmp_path):
    """pin_profiles returns [] for cura when no profiles are specified."""
    project = tmp_path / "project"
    project.mkdir()

    with patch("estampo.profiles.extract_docker_profiles") as mock_docker:
        mock_docker.return_value = None
        result = pin_profiles(
            engine="cura",
            printer=None,
            process=None,
            filaments=[],
            project_dir=project,
            docker_version="5.12.0",
        )

    assert result == []


# ---------------------------------------------------------------------------
# CuraEngine definition detection and pinning
# ---------------------------------------------------------------------------


def test_is_cura_definition():
    """Detect CuraEngine .def.json format."""
    from estampo.profiles import is_cura_definition

    assert is_cura_definition(
        {
            "version": 2,
            "name": "Test Printer",
            "metadata": {"visible": True},
            "overrides": {"machine_width": {"value": 200}},
        }
    )
    # Missing overrides — not a def.json
    assert not is_cura_definition({"version": 2, "metadata": {}})
    # OrcaSlicer machine profile — not a def.json
    assert not is_cura_definition({"type": "machine", "name": "Bambu Lab P1S"})


def test_detect_category_cura_def():
    """CuraEngine .def.json is always detected as machine."""
    assert (
        detect_category(
            {
                "version": 2,
                "name": "Test",
                "metadata": {},
                "overrides": {},
            }
        )
        == "machine"
    )


def test_deep_merge_cura_overrides():
    """Child setting values override parent at the sub-dict level."""
    from estampo.profiles import _deep_merge_cura_overrides

    base = {
        "layer_height": {"value": 0.4, "default_value": 0.4},
        "speed_print": {"value": 60},
    }
    child = {
        "layer_height": {"value": 0.2},
        "wall_count": {"value": 3},
    }
    merged = _deep_merge_cura_overrides(base, child)
    # Child overrides value but preserves parent's default_value
    assert merged["layer_height"] == {"value": 0.2, "default_value": 0.4}
    # Parent-only key preserved
    assert merged["speed_print"] == {"value": 60}
    # Child-only key added
    assert merged["wall_count"] == {"value": 3}


def test_squash_cura_def(tmp_path):
    """Squashing walks inheritance and deep-merges overrides."""
    from estampo.profiles import _squash_cura_def

    # Create a chain: child → parent
    parent = {
        "version": 2,
        "name": "Parent",
        "metadata": {"visible": False, "author": "test"},
        "overrides": {
            "machine_width": {"value": 200},
            "speed_print": {"value": 60, "default_value": 60},
        },
    }
    child = {
        "version": 2,
        "name": "Child Printer",
        "inherits": "parent",
        "metadata": {"visible": True},
        "overrides": {
            "machine_width": {"value": 256},
            "machine_depth": {"value": 256},
        },
    }
    (tmp_path / "parent.def.json").write_text(json.dumps(parent))
    (tmp_path / "child.def.json").write_text(json.dumps(child))

    squashed = _squash_cura_def("child", tmp_path)
    # Both definitions are local — fully resolved, no inherits
    assert "inherits" not in squashed
    assert squashed["name"] == "Child Printer"
    # Child overrides parent; literal ``value`` is promoted to ``default_value`` (#587)
    assert squashed["overrides"]["machine_width"] == {"default_value": 256}
    # Parent-only setting preserved — existing ``default_value`` blocks promotion
    assert squashed["overrides"]["speed_print"] == {"value": 60, "default_value": 60}
    # Child-only setting added (also promoted)
    assert squashed["overrides"]["machine_depth"] == {"default_value": 256}
    # Metadata merged (child visible overrides parent)
    assert squashed["metadata"]["visible"] is True
    assert squashed["metadata"]["author"] == "test"


def test_squash_cura_def_keeps_unresolved_parent(tmp_path):
    """Squashing preserves inherits when the root parent is not available locally."""
    from estampo.profiles import _squash_cura_def

    # child → base → fdmprinter (not available locally)
    base = {
        "version": 2,
        "name": "Base",
        "inherits": "fdmprinter",
        "metadata": {"visible": False},
        "overrides": {
            "speed_print": {"value": 100},
            "acceleration_infill": {"value": "acceleration_print"},
        },
    }
    child = {
        "version": 2,
        "name": "My Printer",
        "inherits": "base",
        "metadata": {"visible": True},
        "overrides": {"machine_width": {"value": 256}},
    }
    (tmp_path / "base.def.json").write_text(json.dumps(base))
    (tmp_path / "child.def.json").write_text(json.dumps(child))

    squashed = _squash_cura_def("child", tmp_path)
    # fdmprinter is not local — keep inherits so CuraEngine resolves at runtime
    assert squashed["inherits"] == "fdmprinter"
    assert squashed["name"] == "My Printer"
    # Literal ``value`` entries are promoted to ``default_value`` at pin-time (#587)
    assert squashed["overrides"]["machine_width"] == {"default_value": 256}
    assert squashed["overrides"]["speed_print"] == {"default_value": 100}
    # Expression left intact — depends on another setting
    assert squashed["overrides"]["acceleration_infill"] == {"value": "acceleration_print"}


def test_add_profile_cura_def(tmp_path):
    """Adding a CuraEngine .def.json writes to profiles/cura/definitions/."""
    def_data = {
        "version": 2,
        "name": "My Printer",
        "metadata": {"visible": True},
        "overrides": {"machine_width": {"value": 300}},
    }
    src = tmp_path / "my_printer.def.json"
    src.write_text(json.dumps(def_data))

    dest = add_profile(str(src), tmp_path, engine="cura")
    assert dest.parent.name == "definitions"
    assert dest.name == "my_printer.def.json"
    assert dest.exists()

    loaded = json.loads(dest.read_text())
    assert loaded["name"] == "My Printer"


def test_pin_cura_definitions_from_bundled(tmp_path):
    """Pinning a bundled CuraEngine definition squashes it."""
    from estampo.profiles import pin_cura_definitions

    result = pin_cura_definitions(
        printer="Ultimaker 2",
        project_dir=tmp_path,
    )
    assert len(result) == 1
    dest = result[0]
    assert dest.name == "ultimaker2.def.json"
    assert dest.parent.name == "definitions"

    squashed = json.loads(dest.read_text())
    # fdmprinter is not bundled — kept so CuraEngine resolves at runtime
    assert squashed.get("inherits") == "fdmprinter"
    assert squashed["name"] == "Ultimaker 2"
    assert "machine_width" in squashed["overrides"]
    assert "machine_heated_bed" in squashed["overrides"]


def test_pin_cura_definitions_from_project_dir(tmp_path):
    """pin finds a def added to profiles/cura/definitions/ via 'profiles add'."""
    from estampo.profiles import pin_cura_definitions

    defs_dir = tmp_path / "profiles" / "cura" / "definitions"
    defs_dir.mkdir(parents=True)
    parent = {
        "version": 2,
        "name": "My Base",
        "inherits": "fdmprinter",
        "metadata": {"visible": False},
        "overrides": {"machine_width": {"value": 200}},
    }
    child = {
        "version": 2,
        "name": "My AMS Variant",
        "inherits": "my_base",
        "metadata": {"visible": True},
        "overrides": {"machine_depth": {"value": 256}},
    }
    (defs_dir / "my_base.def.json").write_text(json.dumps(parent))
    (defs_dir / "my_ams.def.json").write_text(json.dumps(child))

    # No docker_version — must resolve entirely from the project dir.
    result = pin_cura_definitions(printer="my_ams", project_dir=tmp_path)
    assert len(result) == 1
    dest = result[0]
    assert dest.name == "my_ams.def.json"

    squashed = json.loads(dest.read_text())
    assert squashed["name"] == "My AMS Variant"
    # Literal ``value`` is promoted to ``default_value`` at pin-time (#587)
    assert squashed["overrides"]["machine_width"] == {"default_value": 200}
    assert squashed["overrides"]["machine_depth"] == {"default_value": 256}
    assert squashed["inherits"] == "fdmprinter"


def test_pin_profiles_delegates_to_cura(tmp_path):
    """pin_profiles delegates to pin_cura_definitions for engine='cura'."""
    result = pin_profiles(
        engine="cura",
        printer="Ultimaker 2",
        process=None,
        filaments=[],
        project_dir=tmp_path,
    )
    assert len(result) == 1
    assert result[0].name == "ultimaker2.def.json"


def test_discover_profile_names_cura_pinned(tmp_path):
    """Discover pinned CuraEngine definitions."""
    defs_dir = tmp_path / "profiles" / "cura" / "definitions"
    defs_dir.mkdir(parents=True)
    (defs_dir / "my_printer.def.json").write_text(
        json.dumps(
            {
                "version": 2,
                "name": "My Printer",
                "metadata": {},
                "overrides": {},
            }
        )
    )

    names, source = discover_profile_names("cura", project_dir=tmp_path)
    assert source == "pinned"
    assert "My Printer" in names["machine"]


def test_load_cura_definition_map():
    """Load name→id mapping from bundled manifest."""
    from estampo.profiles import load_cura_definition_map

    def_map = load_cura_definition_map()
    assert def_map.get("Ultimaker 2") == "ultimaker2"


# ---------------------------------------------------------------------------
# validate_override_keys
# ---------------------------------------------------------------------------


def test_validate_override_keys_valid(tmp_path):
    """Known keys produce no warnings."""
    profiles = tmp_path / "profiles" / "orca" / "process"
    profiles.mkdir(parents=True)
    (profiles / "Fast.json").write_text(
        json.dumps({"type": "process", "layer_height": "0.3", "wall_loops": "2"})
    )
    warnings = validate_override_keys(
        {"layer_height": "0.2", "wall_loops": "4"},
        engine="orca",
        process="Fast",
        project_dir=tmp_path,
    )
    assert warnings == []


def test_validate_override_keys_unknown(tmp_path):
    """Unknown keys produce warnings."""
    profiles = tmp_path / "profiles" / "orca" / "process"
    profiles.mkdir(parents=True)
    (profiles / "Fast.json").write_text(json.dumps({"type": "process", "layer_height": "0.3"}))
    warnings = validate_override_keys(
        {"layer_height": "0.2", "bogus_key": "1"},
        engine="orca",
        process="Fast",
        project_dir=tmp_path,
    )
    assert len(warnings) == 1
    assert "bogus_key" in warnings[0]


def test_validate_override_keys_no_process_valid_key():
    """No process profile but valid engine key produces no warnings."""
    assert validate_override_keys({"layer_height": "0.2"}, engine="orca", process=None) == []


def test_validate_override_keys_no_process_unknown_key():
    """No process profile with unknown key still warns (checked against engine settings)."""
    warnings = validate_override_keys({"bogus_xyz": "v"}, engine="orca", process=None)
    assert len(warnings) == 1
    assert "bogus_xyz" in warnings[0]


def test_validate_override_keys_no_overrides():
    """Empty overrides produce no warnings."""
    assert validate_override_keys({}, engine="orca", process="Fast") == []


def test_validate_override_keys_unresolvable_profile():
    """Unresolvable profile with valid engine key still passes."""
    warnings = validate_override_keys(
        {"layer_height": "0.2"},
        engine="orca",
        process="NonexistentProfile",
        project_dir=None,
    )
    assert warnings == []


def test_validate_override_keys_cross_engine_orca_in_cura():
    """Using OrcaSlicer key in CuraEngine config should suggest the CuraEngine equivalent."""
    warnings = validate_override_keys(
        {"wall_loops": "3"},
        engine="cura",
        process=None,
    )
    assert len(warnings) == 1
    assert "OrcaSlicer" in warnings[0]
    assert "wall_line_count" in warnings[0]


def test_validate_override_keys_cross_engine_cura_in_orca():
    """Using CuraEngine key in OrcaSlicer config should suggest the OrcaSlicer equivalent."""
    warnings = validate_override_keys(
        {"infill_sparse_density": 20},
        engine="orca",
        process=None,
    )
    assert len(warnings) == 1
    assert "CuraEngine" in warnings[0]
    assert "sparse_infill_density" in warnings[0]


def test_validate_override_keys_did_you_mean():
    """Typo in override key should suggest closest match."""
    warnings = validate_override_keys(
        {"wall_loop": "3"},  # missing 's'
        engine="orca",
        process=None,
    )
    assert len(warnings) == 1
    assert "wall_loops" in warnings[0]


# --- pinned_profiles_version ---


def test_pinned_profiles_version_reads_marker(tmp_path):
    """Reads version from .slicer-version marker file."""
    profiles = tmp_path / "profiles" / "orca"
    profiles.mkdir(parents=True)
    (profiles / ".slicer-version").write_text("2.3.2\n")
    assert pinned_profiles_version(tmp_path, engine="orca") == "2.3.2"


def test_pinned_profiles_version_returns_none_without_marker(tmp_path):
    """Returns None when no marker file exists."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    assert pinned_profiles_version(tmp_path) is None


def test_pinned_profiles_version_returns_none_without_dir(tmp_path):
    """Returns None when profiles dir doesn't exist."""
    assert pinned_profiles_version(tmp_path) is None


# ---------------------------------------------------------------------------
# Engine-namespaced profile directories
# ---------------------------------------------------------------------------


class TestEngineNamespacedProfiles:
    """Tests for profiles/<engine>/<category>/ directory layout."""

    def test_discover_names_engine_namespaced(self, tmp_path):
        """Pinned profiles found under profiles/<engine>/<category>/."""
        orca_machine = tmp_path / "profiles" / "orca" / "machine"
        orca_machine.mkdir(parents=True)
        (orca_machine / "MyPrinter.json").write_text('{"type": "machine"}')

        with patch.dict("estampo.profiles.SYSTEM_DIRS", {}, clear=True):
            names, source = discover_profile_names("orca", project_dir=tmp_path)

        assert source == "pinned"
        assert "MyPrinter" in names.get("machine", [])

    def test_discover_names_no_legacy_fallback(self, tmp_path):
        """Profiles in legacy profiles/<category>/ (without engine subdir) are NOT found."""
        legacy_machine = tmp_path / "profiles" / "machine"
        legacy_machine.mkdir(parents=True)
        (legacy_machine / "OldPrinter.json").write_text('{"type": "machine"}')

        with (
            patch.dict("estampo.profiles.SYSTEM_DIRS", {}, clear=True),
            patch(
                "estampo.profiles.load_bundled_profiles",
                return_value={"machine": [], "process": [], "filament": []},
            ),
        ):
            names, source = discover_profile_names("orca", project_dir=tmp_path)

        assert source == "none"

    def test_resolve_profile_engine_namespaced(self, tmp_path):
        """resolve_profile finds profiles in profiles/<engine>/<category>/."""
        orca_process = tmp_path / "profiles" / "orca" / "process"
        orca_process.mkdir(parents=True)
        expected = orca_process / "MyProcess.json"
        expected.write_text('{"type": "process", "layer_height": "0.2"}')

        result = resolve_profile("MyProcess", "orca", "process", tmp_path)
        assert result == expected

    def test_resolve_profile_no_legacy_fallback(self, tmp_path):
        """resolve_profile does NOT fall back to legacy profiles/<category>/."""
        legacy_process = tmp_path / "profiles" / "process"
        legacy_process.mkdir(parents=True)
        (legacy_process / "OldProcess.json").write_text('{"type": "process"}')

        with pytest.raises(FileNotFoundError):
            resolve_profile("OldProcess", "orca", "process", tmp_path)

    def test_pin_profiles_writes_engine_namespaced(self, tmp_path):
        """pin_profiles writes to profiles/<engine>/<category>/."""
        # Create a system profile to pin
        sys_machine = tmp_path / "sys" / "machine"
        sys_machine.mkdir(parents=True)
        (sys_machine / "TestPrinter.json").write_text(
            json.dumps({"type": "machine", "bed_size": "256x256"})
        )

        with patch.dict("estampo.profiles.SYSTEM_DIRS", {"orca": tmp_path / "sys"}, clear=True):
            pinned = pin_profiles(
                engine="orca",
                printer="TestPrinter",
                process=None,
                filaments=[],
                project_dir=tmp_path,
            )

        assert len(pinned) == 1
        # Written to engine-namespaced path
        assert pinned[0] == tmp_path / "profiles" / "orca" / "machine" / "TestPrinter.json"
        assert pinned[0].exists()
        data = json.loads(pinned[0].read_text())
        assert data["bed_size"] == "256x256"

    def test_pin_profiles_version_marker_engine_namespaced(self, tmp_path):
        """Version marker written to profiles/<engine>/.slicer-version."""
        sys_machine = tmp_path / "sys" / "machine"
        sys_machine.mkdir(parents=True)
        (sys_machine / "TestPrinter.json").write_text('{"type": "machine"}')

        # Mock Docker extraction — returns a dir with the same profiles
        docker_dir = tmp_path / "docker_profiles"
        docker_machine = docker_dir / "machine"
        docker_machine.mkdir(parents=True)
        (docker_machine / "TestPrinter.json").write_text('{"type": "machine"}')

        with (
            patch.dict("estampo.profiles.SYSTEM_DIRS", {"orca": tmp_path / "sys"}, clear=True),
            patch("estampo.profiles.extract_docker_profiles", return_value=docker_dir),
        ):
            pin_profiles(
                engine="orca",
                printer="TestPrinter",
                process=None,
                filaments=[],
                project_dir=tmp_path,
                docker_version="2.3.2",
            )

        marker = tmp_path / "profiles" / "orca" / ".slicer-version"
        assert marker.exists()
        assert marker.read_text().strip() == "2.3.2"

    def test_pinned_profiles_version_engine_namespaced(self, tmp_path):
        """pinned_profiles_version reads from profiles/<engine>/.slicer-version."""
        engine_dir = tmp_path / "profiles" / "orca"
        engine_dir.mkdir(parents=True)
        (engine_dir / ".slicer-version").write_text("2.3.2\n")

        assert pinned_profiles_version(tmp_path, engine="orca") == "2.3.2"

    def test_pinned_profiles_version_no_legacy_fallback(self, tmp_path):
        """pinned_profiles_version does NOT fall back to profiles/.slicer-version."""
        profiles = tmp_path / "profiles"
        profiles.mkdir(parents=True)
        (profiles / ".slicer-version").write_text("2.3.1\n")

        assert pinned_profiles_version(tmp_path, engine="orca") is None

    def test_pinned_profiles_version_engine_over_legacy(self, tmp_path):
        """Engine-namespaced version marker takes precedence."""
        profiles = tmp_path / "profiles"
        profiles.mkdir(parents=True)
        (profiles / ".slicer-version").write_text("2.3.1\n")

        engine_dir = profiles / "orca"
        engine_dir.mkdir()
        (engine_dir / ".slicer-version").write_text("2.3.2\n")

        assert pinned_profiles_version(tmp_path, engine="orca") == "2.3.2"

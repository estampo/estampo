"""Tests for the SlicerEngine protocol conformance."""

from estampo import cura, orca


def _check_protocol_attrs(module: object) -> list[str]:
    """Return protocol attribute names missing from the module."""
    required = [
        "ENGINE_NAME",
        "ENGINE_KEY",
        "find_binary",
        "docker_image",
    ]
    return [name for name in required if not hasattr(module, name)]


def test_orca_has_constants():
    assert orca.ENGINE_NAME == "OrcaSlicer"
    assert orca.ENGINE_KEY == "orca"


def test_cura_has_constants():
    assert cura.ENGINE_NAME == "CuraEngine"
    assert cura.ENGINE_KEY == "cura"


def test_orca_has_protocol_attrs():
    missing = _check_protocol_attrs(orca)
    assert missing == [], f"orca.py missing: {missing}"


def test_cura_has_protocol_attrs():
    missing = _check_protocol_attrs(cura)
    assert missing == [], f"cura.py missing: {missing}"


def test_orca_docker_image():
    assert orca.docker_image("2.3.1") == "estampo/estampo:orca-2.3.1"
    assert orca.docker_image() == "estampo/estampo:latest"


def test_cura_docker_image():
    assert cura.cura_docker_image("5.12.0") == "estampo/estampo:cura-5.12.0"
    assert "cura-" in cura.cura_docker_image()

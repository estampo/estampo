"""Generic command stages — run external CLI tools as pipeline stages.

See ADR-007 for design rationale.  The ``COMMAND_VARIABLES`` dict is the
single source of truth for the template variables available in command
strings.  A test enforces that ``build_command_context()`` produces
exactly these keys.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from estampo import EstampoError

if TYPE_CHECKING:
    from estampo.config import EstampoConfig

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Variable contract
# ---------------------------------------------------------------------------

#: Template variables available in command stage ``command`` and ``output``
#: strings.  Keys are the ``{placeholder}`` names; values are descriptions
#: used for documentation generation and error messages.
COMMAND_VARIABLES: dict[str, str] = {
    "name": "Project name from TOML config (empty string if unset)",
    "output_dir": "Output directory path",
    "machine": "Active printer/machine name (empty string if unset)",
    "engine": "Active slicer engine name (orca or cura)",
    "filament": "First filament profile name (empty string if unset)",
    "filaments": "All filament profiles, comma-separated (empty string if unset)",
    "input_3mf": "Plate 3MF path (available after plate stage)",
    "sliced_3mf": "Packaged 3MF after slicing (available after slice stage)",
    "sliced_dir": "Slicer output directory (available after slice stage)",
    "cura_settings": "CuraEngine settings JSON path (after slice, cura only)",
    "slicer_image": "Docker image tag for the active slicer engine",
}


def build_command_context(
    config: EstampoConfig,
    output_dir: Path,
    stage_results: dict[str, object],
) -> dict[str, str]:
    """Build the flat variable dict for command string substitution.

    *stage_results* maps Hamilton node names to their computed values
    (populated as stages complete).  Only variables whose upstream data
    is available are populated; the rest default to empty string.

    The returned dict always has exactly the keys in ``COMMAND_VARIABLES``.
    """
    engine_cfg = config.slicer.orca if config.slicer.engine == "orca" else config.slicer.cura
    fils = engine_cfg.filaments

    # Resolve slicer Docker image tag
    slicer_image = ""
    if config.slicer.engine == "orca":
        from estampo.orca import docker_image as orca_docker_image

        slicer_image = orca_docker_image(config.slicer.version)
    elif config.slicer.engine == "cura":
        from estampo.cura import cura_docker_image

        slicer_image = cura_docker_image(config.slicer.version)

    ctx: dict[str, str] = {
        "name": config.name or "",
        "output_dir": str(output_dir),
        "machine": config.slicer.active.printer or "",
        "engine": config.slicer.engine,
        "filament": fils[0] if fils else "",
        "filaments": ",".join(fils) if fils else "",
        "input_3mf": str(stage_results.get("plate_3mf_path", "")),
        "sliced_3mf": str(stage_results.get("packaged_output", "")),
        "sliced_dir": str(stage_results.get("sliced_output_dir", "")),
        "cura_settings": "",
        "slicer_image": slicer_image,
    }
    sliced_dir = stage_results.get("sliced_output_dir")
    if sliced_dir and config.slicer.engine == "cura":
        settings_path = Path(str(sliced_dir)) / "cura_settings.json"
        if settings_path.exists():
            ctx["cura_settings"] = str(settings_path)
    return ctx


# ---------------------------------------------------------------------------
# Command stage config
# ---------------------------------------------------------------------------


@dataclass
class CommandStageConfig:
    """Parsed ``[stage_name]`` section from TOML with a ``command`` key."""

    name: str
    command: str
    output: str | None = None
    docker: bool = False
    image: str | None = None


def parse_command_stage(name: str, raw: dict) -> CommandStageConfig:
    """Parse a TOML section into a ``CommandStageConfig``.

    Raises ``EstampoError`` if the section has a ``command`` key but it
    is invalid.
    """
    command = raw.get("command")
    if command is None:
        raise EstampoError(f"[{name}]: missing 'command' key")
    if not isinstance(command, str) or not command.strip():
        raise EstampoError(f"[{name}].command must be a non-empty string")
    output = raw.get("output")
    if output is not None:
        if not isinstance(output, str) or not output.strip():
            raise EstampoError(f"[{name}].output must be a non-empty string")
    docker = raw.get("docker", False)
    if not isinstance(docker, bool):
        raise EstampoError(f"[{name}].docker must be true or false")
    image = raw.get("image")
    if image is not None:
        if not isinstance(image, str) or not image.strip():
            raise EstampoError(f"[{name}].image must be a non-empty string")
    return CommandStageConfig(
        name=name, command=command.strip(), output=output, docker=docker, image=image
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _wrap_docker_command(
    cmd: list[str],
    image: str,
    output_dir: str,
) -> list[str]:
    """Wrap a command in ``docker run`` with volume mounts.

    Mounts the output directory at ``/work/output`` and rewrites any
    arguments that reference the host output_dir to use the container path.
    """
    import os

    abs_output = str(Path(output_dir).resolve())
    container_output = "/work/output"

    # Rewrite host paths to container paths in arguments
    rewritten = []
    for arg in cmd:
        rewritten.append(arg.replace(abs_output, container_output))

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "-v",
        f"{abs_output}:{container_output}",
        "--workdir",
        container_output,
    ]
    # Match host user so output files are owned correctly (skip on Windows)
    if os.name != "nt":
        docker_cmd.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    docker_cmd.extend(["--entrypoint", rewritten[0], image])
    docker_cmd.extend(rewritten[1:])
    return docker_cmd


def _is_inside_container() -> bool:
    """Detect if we are already running inside a Docker container."""
    return Path("/.dockerenv").exists()


def run_command_stage(
    stage: CommandStageConfig,
    context: dict[str, str],
    *,
    timeout: int = 600,
) -> Path | None:
    """Substitute variables and execute a command stage.

    Returns the resolved ``output`` path if the stage defines one,
    otherwise ``None``.

    Raises ``EstampoError`` on missing variables or non-zero exit code.
    """
    try:
        rendered_command = stage.command.format_map(context)
    except KeyError as exc:
        available = ", ".join(sorted(context))
        raise EstampoError(
            f"[{stage.name}].command: unknown variable {exc}. Available variables: {available}"
        ) from None

    output_path: Path | None = None
    if stage.output:
        try:
            rendered_output = stage.output.format_map(context)
        except KeyError as exc:
            available = ", ".join(sorted(context))
            raise EstampoError(
                f"[{stage.name}].output: unknown variable {exc}. Available variables: {available}"
            ) from None
        output_path = Path(rendered_output)

    cmd = shlex.split(rendered_command)

    # When docker=true and we're not already inside a container,
    # wrap the command in docker run with volume mounts.
    use_docker = stage.docker and not _is_inside_container()
    if use_docker:
        image = stage.image or context.get("slicer_image", "")
        if not image:
            raise EstampoError(
                f"[{stage.name}]: docker=true but no image specified and "
                f"no slicer image available. "
                f"Set [{stage.name}].image or configure a slicer engine."
            )
        cmd = _wrap_docker_command(cmd, image, context.get("output_dir", ""))

    log.info("Running command stage '%s': %s", stage.name, shlex.join(cmd))

    from estampo import ui

    with ui.status(f"Running {stage.name}"):
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    if result.returncode != 0:
        log.error("Command stage '%s' stderr:\n%s", stage.name, result.stderr)
        raise EstampoError(
            f"Command stage '{stage.name}' failed (exit code {result.returncode}):\n"
            f"{result.stderr[:500]}"
        )

    if result.stdout:
        log.info("Command stage '%s' stdout:\n%s", stage.name, result.stdout.rstrip())

    return output_path

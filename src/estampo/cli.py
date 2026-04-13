"""CLI entry point for estampo."""

import logging
import sys
from pathlib import Path
from typing import Annotated

import click
import typer

from estampo import EstampoError, __version__
from estampo.config import load_config

log = logging.getLogger(__name__)

app = typer.Typer(
    name="estampo",
    help="The build system for reproducible 3D prints.",
    no_args_is_help=True,
)

profiles_app = typer.Typer(help="List or pin slicer profiles.")
app.add_typer(profiles_app, name="profiles")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        print(f"estampo {__version__}")
        raise typer.Exit()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )


def _resolve_config_path(config: Path | None) -> Path:
    """Resolve config path, defaulting to ./estampo.toml."""
    if config is not None:
        return config
    candidate = Path("estampo.toml")
    if not candidate.exists():
        raise EstampoError(
            "No config file specified and no estampo.toml found in the current directory.\n"
            "Usage: estampo <command> [config.toml]"
        )
    return candidate


# ---------------------------------------------------------------------------
# Hamilton driver helpers
# ---------------------------------------------------------------------------


def _build_driver(verbose: bool = False):
    """Build a Hamilton driver wired to the estampo pipeline."""
    import os

    # Disable Hamilton telemetry before first import
    os.environ["HAMILTON_TELEMETRY_ENABLED"] = "false"

    # Silence all Hamilton loggers (pandera warnings, tracebacks, error boxes)
    logging.getLogger("hamilton").setLevel(logging.CRITICAL + 1)

    from hamilton import driver

    from estampo import adapters, pipeline

    builder = driver.Builder().with_modules(pipeline)
    if verbose:
        builder = builder.with_adapters(adapters.ProgressAdapter(), adapters.TimingAdapter())
    else:
        builder = builder.with_adapters(adapters.ProgressAdapter())
    return builder.build()


def _gather_inputs(
    *,
    config: Path,
    output_dir: Path,
    output_3mf: Path,
    scale: float | None,
    local: bool,
    docker_version: str | None,
    filament_type: str | None,
    filament_slot: int,
) -> dict:
    """Build the full set of Hamilton driver inputs."""
    return {
        "config_path": config,
        "global_scale": scale,
        "output_3mf": output_3mf,
        "output_dir": output_dir,
        "slicer_local": local,
        "docker_version": docker_version,
        "filament_type_override": filament_type,
        "filament_slot_override": filament_slot,
    }


# ---------------------------------------------------------------------------
# Version callback (top-level)
# ---------------------------------------------------------------------------


@app.callback()
def _app_callback(
    version: Annotated[
        bool, typer.Option("--version", callback=_version_callback, is_eager=True)
    ] = False,
) -> None:
    pass


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


@app.command()
def run(
    config: Annotated[Path | None, typer.Argument(help="Path to config file")] = None,
    output_dir: Annotated[
        Path | None, typer.Option("-o", "--output-dir", help="Output directory")
    ] = None,
    until: Annotated[
        str | None, typer.Option(help="Run pipeline up to and including this stage")
    ] = None,
    only: Annotated[
        str | None,
        typer.Option(help="Run only this stage (fail if required artifacts don't exist)"),
    ] = None,
    scale: Annotated[
        float | None,
        typer.Option(help="Scale all parts by this factor (multiplies per-part scale)"),
    ] = None,
    local: Annotated[
        bool, typer.Option("--local", help="Force local slicer (fail if not installed)")
    ] = False,
    docker_version: Annotated[
        str | None,
        typer.Option(help="Use a specific slicer Docker image version (e.g. 2.3.1)"),
    ] = None,
    filament_type: Annotated[
        str | None,
        typer.Option(help="Override filament profile name (e.g. 'Generic PLA @base')"),
    ] = None,
    filament_slot: Annotated[int, typer.Option(help="Slot number for --filament-type")] = 1,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Enable debug logging")] = False,
) -> None:
    """Run the pipeline defined in estampo.toml."""
    _setup_logging(verbose)

    if until and only:
        raise ValueError("Cannot use both --until and --only")

    resolved_config = _resolve_config_path(config)
    _run_pipeline(
        config=resolved_config,
        output_dir=output_dir,
        until=until,
        only=only,
        local=local,
        docker_version=docker_version,
        verbose=verbose,
        scale=scale,
        filament_type=filament_type,
        filament_slot=filament_slot,
    )


@app.command()
def watch(
    config: Annotated[Path | None, typer.Argument(help="Path to config file")] = None,
    output_dir: Annotated[
        Path | None, typer.Option("-o", "--output-dir", help="Output directory")
    ] = None,
    until: Annotated[
        str | None, typer.Option(help="Run pipeline up to and including this stage")
    ] = None,
    local: Annotated[
        bool, typer.Option("--local", help="Force local slicer (fail if not installed)")
    ] = False,
    docker_version: Annotated[
        str | None,
        typer.Option(help="Use a specific slicer Docker image version"),
    ] = None,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Enable debug logging")] = False,
) -> None:
    """Watch input files and re-run the pipeline on changes."""
    _setup_logging(verbose)
    try:
        from watchfiles import watch as watchfiles_watch
    except ImportError:
        raise SystemExit(
            "watchfiles is required for watch mode. Install with: pip install watchfiles"
        )

    resolved_config = _resolve_config_path(config)
    cfg = load_config(resolved_config)

    # Collect files to watch: config + all part files
    watch_paths: set[Path] = {resolved_config.resolve()}
    for part in cfg.parts:
        watch_paths.add(part.file.resolve())

    from estampo import ui

    ui.info(f"Watching {len(watch_paths)} file(s) for changes (Ctrl-C to stop):")
    for p in sorted(watch_paths):
        ui.info(f"  {p}")
    ui.console.print()

    # Initial run
    _run_pipeline(resolved_config, output_dir, until, None, local, docker_version, verbose)

    # Watch loop
    try:
        for changes in watchfiles_watch(*watch_paths):
            changed_names = ", ".join(Path(c[1]).name for c in changes)
            ui.console.print(f"\n--- {changed_names} changed, re-running ---\n")
            # Reload config in case it changed
            resolved_config = _resolve_config_path(config)
            try:
                _run_pipeline(
                    resolved_config, output_dir, until, None, local, docker_version, verbose
                )
            except Exception as e:
                ui.error(f"{e}")
    except KeyboardInterrupt:
        ui.console.print()


def _run_pipeline(
    config: Path,
    output_dir: Path | None,
    until: str | None,
    only: str | None,
    local: bool,
    docker_version: str | None,
    verbose: bool,
    scale: float | None = None,
    filament_type: str | None = None,
    filament_slot: int = 1,
) -> None:
    """Execute the pipeline (shared by run and watch commands)."""
    from estampo.pipeline import resolve_outputs, resolve_overrides

    cfg = load_config(config)
    stages = cfg.pipeline.stages

    # Warn about unrecognised slicer override keys early
    active = cfg.slicer.active
    if active.overrides:
        from estampo.profiles import validate_override_keys

        orca = cfg.slicer.orca if cfg.slicer.engine == "orca" else None
        override_warnings = validate_override_keys(
            active.overrides,
            cfg.slicer.engine,
            orca.process if orca else None,
            project_dir=cfg.base_dir,
        )
        if override_warnings:
            from estampo import ui

            for w in override_warnings:
                ui.warn(w)

    if output_dir:
        out_dir = output_dir
    elif cfg.output_dir != "estampo_output":
        out_dir = cfg.base_dir / cfg.output_dir
    elif cfg.name:
        out_dir = cfg.base_dir / "estampo_output" / cfg.name
    else:
        out_dir = cfg.base_dir / "estampo_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    output_3mf = out_dir / "plate.3mf"

    outputs = resolve_outputs(
        stages,
        until=until,
        only=only,
        command_stages=set(cfg.pipeline.command_stages),
    )

    overrides = {}
    if only:
        overrides = resolve_overrides(only, out_dir)

    dr = _build_driver(verbose=verbose)
    inputs = _gather_inputs(
        config=config,
        output_dir=out_dir,
        output_3mf=output_3mf,
        scale=scale,
        local=local,
        docker_version=docker_version,
        filament_type=filament_type,
        filament_slot=filament_slot,
    )

    from estampo import ui

    ui.info(f"Output → [bold]{out_dir}[/bold]")
    hamilton_results = dr.execute(outputs, inputs=inputs, overrides=overrides)

    # Run command stages (external CLI tools defined in TOML)
    command_stages = cfg.pipeline.command_stages
    if command_stages:
        from estampo.commands import build_command_context, run_command_stage

        # Determine which stages to run based on --until / --only
        if only and only in command_stages:
            stages_to_run = [only]
        elif until:
            cut = stages[: stages.index(until) + 1]
            stages_to_run = [s for s in cut if s in command_stages]
        else:
            stages_to_run = [s for s in stages if s in command_stages]

        # Build context from Hamilton results + config
        stage_results = dict(hamilton_results)
        stage_results.update(overrides)
        context = build_command_context(cfg, out_dir, stage_results)

        for stage_name in stages_to_run:
            stage_cfg = command_stages[stage_name]
            output_path = run_command_stage(stage_cfg, context)
            # Feed output back into context for downstream command stages
            if output_path is not None:
                context[stage_name] = str(output_path)


# ---------------------------------------------------------------------------
# init / validate commands
# ---------------------------------------------------------------------------


@app.command()
def init(
    template: Annotated[
        bool, typer.Option("--template", help="Dump a commented template to stdout (no wizard)")
    ] = False,
    from_3mf: Annotated[
        Path | None,
        typer.Option("--from-3mf", help="Generate config from a slicer .3mf project file"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="Output file path (default: ./estampo.toml)"),
    ] = None,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Enable debug logging")] = False,
) -> None:
    """Create a new estampo.toml config file.

    The interactive wizard requires a Unix terminal (Linux, macOS, or WSL).
    On Windows, use --template to generate a config file manually.
    Use --from-3mf to extract settings from an OrcaSlicer project.
    """
    _setup_logging(verbose)

    if from_3mf:
        from estampo.init import extract_from_3mf

        toml = extract_from_3mf(from_3mf)
        dest = output or Path("estampo.toml")
        if dest.exists():
            from estampo import ui

            ui.warn(f"{dest} already exists — printing to stdout")
            print(toml, end="")
        else:
            from estampo import ui

            dest.write_text(toml)
            ui.success(f"Wrote {dest}")
            ui.info("Review the file and add your [[parts]] entries.")
    elif template:
        from estampo.init import dump_template

        print(dump_template(), end="")
    else:
        from estampo.init import run_wizard

        run_wizard(output=output)


@app.command()
def validate(
    config: Annotated[Path | None, typer.Argument(help="Path to config file")] = None,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Enable debug logging")] = False,
) -> None:
    """Check an estampo.toml for issues."""
    _setup_logging(verbose)
    from estampo import ui
    from estampo.init import validate_config

    resolved_config = _resolve_config_path(config)
    ui.heading(f"Validating {resolved_config.name}")
    result = validate_config(resolved_config)
    for p in result.passes:
        ui.success(p)
    for w in result.warnings:
        ui.warn(w)
    ui.console.print()
    if result.warnings:
        n = len(result.warnings)
        ui.console.print(f"  [yellow]{n}[/yellow] warning{'s' if n != 1 else ''} found.")
    else:
        ui.success("All checks passed.")


# ---------------------------------------------------------------------------
# profiles subcommands
# ---------------------------------------------------------------------------


@profiles_app.command("list")
def profiles_list(
    engine: Annotated[str, typer.Option(help="Slicer engine")] = "orca",
    category: Annotated[
        str | None, typer.Option(help="Filter by category (machine, process, filament)")
    ] = None,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Enable debug logging")] = False,
) -> None:
    """List available profiles."""
    _setup_logging(verbose)
    from estampo.profiles import (
        _INLINE_ENGINES,
        CATEGORIES,
        discover_profiles,
    )

    if engine in _INLINE_ENGINES:
        from estampo import ui

        ui.info(f"Engine '{engine}' uses inline settings — no extractable profiles.")
        raise typer.Exit(0)

    from estampo import ui

    profiles = discover_profiles(engine)
    categories = [category] if category else list(CATEGORIES)
    for cat in categories:
        names = profiles.get(cat, {})
        ui.console.print(f"\n{cat} ({len(names)} profiles):")
        for name in names:
            ui.console.print(f"  {name}")


@profiles_app.command("pin")
def profiles_pin(
    config: Annotated[Path | None, typer.Argument(help="Path to config file")] = None,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Enable debug logging")] = False,
) -> None:
    """Pin profiles from config into local profiles/ dir.

    Extracts profiles from Docker if the slicer is not installed locally.
    """
    _setup_logging(verbose)
    import tomllib

    from estampo.profiles import _INLINE_ENGINES, pin_profiles

    resolved_config = _resolve_config_path(config)
    cfg = load_config(resolved_config)
    profiles_dir = cfg.slicer.profiles_dir

    from estampo import ui

    if cfg.slicer.engine in _INLINE_ENGINES:
        ui.info(f"Engine '{cfg.slicer.engine}' uses inline settings — no profiles to pin.")
        raise typer.Exit(0)

    # If pinned output already exists, ask what to do.
    # Only check engine-specific subdirectories — user-added files in the
    # top-level profiles dir (e.g. from 'profiles add') should not trigger
    # the overwrite prompt.
    target = cfg.base_dir / profiles_dir
    engine_subdir = target / cfg.slicer.engine
    if engine_subdir.exists() and any(engine_subdir.iterdir()):
        ui.warn(f"Pinned profiles already exist in '{profiles_dir}/{cfg.slicer.engine}/'.")
        choice = input("  [o]verwrite, use [d]ifferent directory, or [c]ancel? ").strip().lower()
        if choice.startswith("d"):
            profiles_dir = input("  New directory name: ").strip()
            if not profiles_dir:
                ui.info("Cancelled.")
                raise typer.Exit(1)
        elif choice.startswith("c"):
            ui.info("Cancelled.")
            raise typer.Exit(0)
        # else: overwrite

    active = cfg.slicer.active
    orca = cfg.slicer.orca if cfg.slicer.engine == "orca" else None
    pinned = pin_profiles(
        engine=cfg.slicer.engine,
        printer=active.printer,
        process=orca.process if orca else None,
        filaments=orca.filaments if orca else [],
        project_dir=cfg.base_dir,
        docker_version=cfg.slicer.version,
        profiles_dir=profiles_dir,
    )
    ui.success(f"Pinned {len(pinned)} profile(s) to {profiles_dir}/")
    for p in pinned:
        ui.info(f"  {p}")

    # Update estampo.toml if needed
    toml_text = resolved_config.read_text()
    raw = tomllib.loads(toml_text)
    existing_dir = raw.get("slicer", {}).get("profiles_dir")

    if existing_dir == profiles_dir:
        pass  # already correct
    elif existing_dir is not None and existing_dir != profiles_dir:
        # Different value exists — ask
        update = (
            input(
                f'\n  estampo.toml has profiles_dir = "{existing_dir}". '
                f'Update to "{profiles_dir}"? [y/n] '
            )
            .strip()
            .lower()
        )
        if update.startswith("y"):
            toml_text = toml_text.replace(
                f'profiles_dir = "{existing_dir}"',
                f'profiles_dir = "{profiles_dir}"',
            )
            resolved_config.write_text(toml_text)
            ui.success(f"Updated profiles_dir in {resolved_config.name}")
    elif profiles_dir != "profiles":
        # Non-default dir, need to add it to TOML
        if "[slicer]" in toml_text:
            toml_text = toml_text.replace(
                "[slicer]",
                f'[slicer]\nprofiles_dir = "{profiles_dir}"',
            )
        resolved_config.write_text(toml_text)
        ui.success(f'Added profiles_dir = "{profiles_dir}" to {resolved_config.name}')
    else:
        ui.info("Using default profiles directory — no config change needed")


@profiles_app.command("add")
def profiles_add(
    source: Annotated[str, typer.Argument(help="Local file path or URL to a profile JSON")],
    category: Annotated[
        str | None,
        typer.Option(help="Profile category (machine/process/filament). Auto-detected if omitted."),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option(help="Profile name (default: filename or JSON 'name' field)"),
    ] = None,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Enable debug logging")] = False,
) -> None:
    """Import a profile JSON file into the project's profiles/ directory."""
    _setup_logging(verbose)
    import tomllib

    from estampo.profiles import add_profile

    project_dir = Path.cwd()
    engine = "orca"
    try:
        config_path = _resolve_config_path(None)
        raw = tomllib.loads(config_path.read_text())
        engine = raw.get("slicer", {}).get("engine", "orca")
    except (EstampoError, OSError, tomllib.TOMLDecodeError, KeyError):
        pass
    dest = add_profile(source, project_dir, category=category, name=name, engine=engine)
    from estampo import ui

    ui.success(f"Added profile: {dest}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Entry point for estampo CLI."""
    try:
        app(argv, standalone_mode=False)
    except click.exceptions.NoArgsIsHelpError:
        sys.exit(1)
    except SystemExit as e:
        if e.code:
            sys.exit(e.code)
    except EstampoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)

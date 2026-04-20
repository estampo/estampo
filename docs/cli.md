# CLI reference

estampo provides commands for creating configs (`init`, `validate`), inspecting valid config values (`info`), running the pipeline (`run`), and managing slicer profiles (`profiles`).

## Top-level options

| Option                  | Description                                              |
|-------------------------|----------------------------------------------------------|
| `--version`             | Print estampo version and exit                           |
| `--install-completion`  | Install shell completion for the current shell           |
| `--show-completion`     | Print the completion script (bash/zsh/fish/pwsh) to stdout |
| `--help`                | Show help and exit                                       |

### Shell completion

After running `estampo --install-completion`, restart your shell. You will get
tab completion on commands, flags, and stage names. To inspect or customize
the installed script, run `estampo --show-completion`.

## `estampo init`

Create a new `estampo.toml` config file.

```
estampo init [--template] [--workflow] [-o OUTPUT] [--engine ENGINE]
             [--printer PRINTER] [--process PROCESS]
             [--filament FILAMENT]... [--part PART]... [--from-3mf FILE]
```

| Option         | Description                                         |
|----------------|-----------------------------------------------------|
| `--template`   | Dump a commented template to stdout (skip wizard)   |
| `--workflow`   | Generate a GitHub Actions slice workflow (`.github/workflows/slice.yml`) |
| `-o, --output` | Output file path (default: `./estampo.toml`)       |
| `--engine`     | Slicer engine: `orca` or `cura` (non-interactive)  |
| `--printer`    | Printer profile name (non-interactive)              |
| `--process`    | Process/quality profile name (non-interactive, OrcaSlicer only) |
| `--filament`   | Filament profile (repeatable, non-interactive)      |
| `--part`       | Part file path (repeatable, non-interactive)        |
| `--from-3mf`   | Extract settings from an OrcaSlicer project file    |

**Non-interactive mode:** pass `--engine`, `--filament`, and `--part` to generate
a config without the wizard. Use `--printer` and `--process` for OrcaSlicer.

**Interactive wizard** (default when non-interactive flags are omitted):
1. Discovers installed slicer profiles (printer, process, filament) with search/filter
3. Detects printer capabilities from the selected machine profile (plate size, multi-material support)
4. Queries AMS tray contents in the background and auto-suggests matching filament profiles
5. Auto-discovers CAD files (STL, 3MF, STEP) in the current directory
6. Prompts for per-part copies, orientation, and filament slot assignment
7. Detects installed OrcaSlicer version and offers to pin it for reproducibility
8. Previews the generated TOML before writing

### Examples

```bash
estampo init                              # interactive wizard
estampo init --template                   # print commented template
estampo init --template > estampo.toml   # save template to file
estampo init -o myproject.toml            # wizard writes to custom path
estampo init --engine orca --printer "Bambu Lab P1S 0.4 nozzle" \
  --filament "Generic PLA @base" --part bracket.stl   # non-interactive
estampo init --from-3mf project.3mf       # extract from OrcaSlicer project
estampo init --workflow                   # wizard + generate GitHub Actions workflow
estampo init --template --workflow        # template + workflow file
```

## `estampo validate`

Check an `estampo.toml` for issues and print actionable warnings.

```
estampo validate [config]
```

If `config` is omitted, looks for `estampo.toml` in the current directory.

Checks for:
- Missing `slicer.version` (reproducibility)
- Profile names not matching installed slicer profiles (with "did you mean?" suggestions)
- Cross-engine detection — catches CuraEngine setting names used with OrcaSlicer and vice versa
- Absolute part file paths (portability)
- Unknown pipeline stages
- Unknown override keys (with suggestions for typos)

**Note:** The validation warning "slicer profile names could not be validated"
is expected when profiles are not installed locally. This is not an error —
profiles are resolved at runtime via Docker. The warning can be safely ignored.

**Safety note:** Validation checks config structure and setting names. It does
not verify that override values are safe for your printer — for example, it
will not catch dangerously high temperatures or missing supports. Always review
sliced output before sending to a printer.

### Examples

```bash
estampo validate                  # check ./estampo.toml
estampo validate myproject.toml   # check a specific file
```

## `estampo info`

Print the enumerated values that estampo understands in configs — useful
for humans checking what's valid, and for AI assistants grounding
suggestions without scraping source.

```
estampo info [--json]
```

Reports:

- Valid pipeline stages (`load`, `arrange`, `plate`, `slice`, `gcode-info`, `resolve_templates`, `pack`)
- Valid slicer engines (`orca`, `cura`)
- Valid `orient` values for `[[parts]]`
- Recognised bed type values
- Recognised mesh file extensions (`.stl`, `.step`, `.3mf`, ...)
- Command-stage substitution variables (`{sliced_3mf}`, `{output_dir}`, ...)

Pass `--json` for machine-readable output — this is what the AI setup
prompt uses to stay in sync with the installed version.

### Examples

```bash
estampo info                  # human-readable output
estampo info --json           # JSON for tooling
```

## `estampo setup` *(deprecated — removed in v0.4.0)*

> **Use [bambox](https://github.com/estampo/bambox) instead.** estampo is
> printer-agnostic — printer setup and credentials are managed by bambox.
> Run `bambox login` to authenticate with Bambu Cloud. Credentials are
> saved to `~/.config/bambox/credentials.toml`.

## `estampo run`

Run all or part of the pipeline.

```
estampo run [config] [options]
```

If `config` is omitted, estampo looks for `estampo.toml` in the current directory.

| Option              | Description                                          |
|---------------------|------------------------------------------------------|
| `[config]`          | Path to config file (default: `./estampo.toml`)     |
| `-o, --output-dir`  | Output directory (default: `estampo_output/` or `estampo_output/{name}/`) |
| `--until STAGE`     | Run pipeline up to and including this stage           |
| `--only STAGE`      | Run only this stage (fails if prerequisites missing)  |
| `--scale FACTOR`    | Scale all parts (multiplies per-part scale)           |
| `--local`           | Force local slicer (fail if not installed)            |
| `--docker-version`  | Pin OrcaSlicer Docker image version (e.g. `2.3.1`)   |
| `--filament-type`   | Override filament profile name                        |
| `--filament-slot`   | AMS slot for `--filament-type` (default: 1)           |
| `-v, --verbose`     | Enable debug logging with per-stage timing            |

### Pipeline stages

The default pipeline runs these stages in order:

| Stage       | What it does                                      | Output                    |
|-------------|---------------------------------------------------|---------------------------|
| `load`      | Load meshes, apply orientation and scaling         | Part summary              |
| `arrange`   | Bin-pack parts onto the build plate                | Placements                |
| `plate`     | Export arranged plate as 3MF (+ preview)           | `plate.3mf`, `plate_preview.3mf` |
| `slice`     | Slice via OrcaSlicer or CuraEngine (Docker or local) | gcode in output dir     |
| `gcode-info`| Parse print time and filament usage from gcode     | Stats summary             |
| `print`     | *(deprecated)* Send sliced gcode to printer        | Print job                 |

In addition to built-in stages, you can define **command stages** — custom
pipeline stages that run external CLI tools. See the
[config reference](config.md#command-stages) for details.

**Tip:** Add `gcode-info` after `slice` to see print time and filament usage:
```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "gcode-info"]
```

### Examples

```bash
# Full pipeline: arrange, slice, and print (uses ./estampo.toml)
estampo run

# Stop after plating (no slicer needed)
estampo run --until plate

# Only slice (requires plate.3mf already in output/)
estampo run --only slice

# Slice with a specific Docker image version
estampo run --until slice --docker-version 2.3.1

# Verbose mode — shows per-stage timing
estampo run -v

# Explicit config path
estampo run myproject.toml --until plate
```

### `--until` vs `--only`

- **`--until plate`** runs `load -> arrange -> plate`, computing everything from scratch.
- **`--only slice`** runs *just* the slice stage. It expects `output/plate.3mf` to already exist on disk (e.g. from a previous `--until plate` run). Fails with an error if the prerequisite is missing.

You cannot combine `--until` and `--only`.

## `estampo profiles`

Manage slicer profiles.

```
estampo profiles list [--engine orca|cura]
                      [--category machine|process|filament]
                      [--printer NAME] [--json]
estampo profiles pin [config]
```

- **`list`** — show available profiles from your slicer installation.
  - `--printer NAME` (OrcaSlicer only) filters `process` and `filament`
    lists to entries whose `compatible_printers` includes *NAME*. Prefer
    this over manually scanning the full list — incompatible
    process/printer combos fail silently at slice time (exit 239).
- **`pin`** — copy the profiles referenced in your config into a local `profiles/` directory. Commit this to git for reproducible builds across machines.

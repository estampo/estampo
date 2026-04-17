# CLI reference

estampo provides commands for creating configs (`init`, `validate`), setting up printers (`setup`), running the pipeline (`run`), and managing printers (`status`, `profiles`).

## `estampo init`

Create a new `estampo.toml` config file.

```
estampo init [--template] [-o OUTPUT]
```

| Option        | Description                                         |
|---------------|-----------------------------------------------------|
| `--template`  | Dump a commented template to stdout (skip wizard)   |
| `-o, --output`| Output file path (default: `./estampo.toml`)       |

Without `--template`, runs an interactive wizard that:
1. Checks for configured printers (offers to run `estampo setup` if none found)
2. Discovers installed OrcaSlicer profiles (printer, process, filament) with search/filter
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
```

## `estampo validate`

Check an `estampo.toml` for issues and print actionable warnings.

```
estampo validate [config]
```

If `config` is omitted, looks for `estampo.toml` in the current directory.

Checks for:
- Missing `slicer.version` (reproducibility)
- Profile names not matching installed slicer profiles (with suggestions)
- Printer name not found in credentials file
- Absolute part file paths (portability)
- Unknown pipeline stages

### Examples

```bash
estampo validate                  # check ./estampo.toml
estampo validate myproject.toml   # check a specific file
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
| `--dry-run`         | Do everything except send to printer                  |
| `--upload-only`     | Upload gcode but don't start printing                 |
| `--experimental`    | Enable experimental printer modes                     |
| `--no-ams-mapping`  | Skip AMS mapping (diagnostic)                         |
| `-v, --verbose`     | Enable debug logging with per-stage timing            |

### Pipeline stages

The default pipeline runs these stages in order:

| Stage       | What it does                                      | Output                    |
|-------------|---------------------------------------------------|---------------------------|
| `load`      | Load meshes, apply orientation and scaling         | Part summary              |
| `arrange`   | Bin-pack parts onto the build plate                | Placements                |
| `plate`     | Export arranged plate as 3MF (+ preview)           | `plate.3mf`, `plate_preview.3mf` |
| `slice`     | Slice via OrcaSlicer (Docker or local)             | gcode in output dir       |
| `gcode-info`| Parse print time and filament usage from gcode     | Stats summary             |
| `print`     | Send sliced gcode to printer                       | Print job                 |

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

# Dry run — do everything except actually send to printer
estampo run --dry-run

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
estampo profiles list [--category machine|process|filament]
estampo profiles pin [config]
```

- **`list`** — show available profiles from your slicer installation.
- **`pin`** — copy the profiles referenced in your config into a local `profiles/` directory. Commit this to git for reproducible builds across machines.

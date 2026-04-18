# Add estampo to a 3D printing project

> **What this is:** A prompt you can paste as-is into any AI assistant (Claude,
> ChatGPT, Copilot, etc.) to add estampo support to a GitHub project that
> contains 3D-printable models. No editing needed — just copy, paste, and the
> AI will ask you the questions it needs answered.

---

## The prompt

````markdown
I want to add **estampo** to this project so that 3D printing is automated and
reproducible. estampo is a declarative build system for 3D prints — you write a
TOML config file and it handles the full pipeline: load meshes, arrange on the
build plate, slice with OrcaSlicer or CuraEngine, and optionally run
post-processing command stages.

### What I need you to do

1. Look at this project and find the 3D model files (STL, STEP, 3MF).
2. Ask me the questions listed below to fill in the details you can't determine
   from the repo.
3. Install estampo (add it to the project's dev dependencies or document the
   install command).
4. Create an `estampo.toml` config file in the repo root.
5. Validate the config with `estampo validate`.
6. Optionally add a GitHub Actions workflow (`estampo init --workflow` or create manually).

### What to ask me

Before creating the config, ask me these questions (skip any you can infer from
the repo context):

1. **Which slicer engine?** — `orca` (OrcaSlicer) or `cura` (CuraEngine).
   Default to `orca` if I have a Bambu Lab printer.
2. **Which printer?** — e.g. `Bambu Lab P1S 0.4 nozzle` (OrcaSlicer) or
   `bambox_p1s` (CuraEngine). Run `estampo profiles list --engine orca --category machine`
   to see available profiles.
3. **Which quality preset?** — OrcaSlicer only, e.g. `0.20mm Standard @BBL X1C`.
   Run `estampo profiles list --engine orca --category process` to see options.
4. **Which filament(s)?** — e.g. `Generic PLA @base`, `Generic PETG @base`.
   Run `estampo profiles list --engine orca --category filament` to see options.
5. **Print goals?** — e.g. "strong functional part", "fast draft", "smooth
   surface", "dimensional accuracy". This determines which override recipe to
   apply.
6. **Do you want a GitHub Actions workflow?** — slices on every push and posts
   build metrics as a PR comment.
7. **Is this a Bambu Lab printer?** — if yes, a `pack` stage is required to
   produce the `.gcode.3mf` format Bambu printers need.

### How to install

```bash
# Option A: pipx (recommended for CLI tools)
pipx install estampo

# Option B: pip
pip install estampo

# Option C: uv
uv tool install estampo
```

### How to create the config

Use the non-interactive init command (substitute the answers from above):

```bash
estampo init \
  --engine ENGINE \
  --printer "PRINTER" \
  --filament "FILAMENT" \
  --part MODEL_FILE_1 \
  --part MODEL_FILE_2
```

Or create `estampo.toml` directly. Here is the structure:

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice"]

[plate]
size = [256, 256]        # bed size in mm [width, depth]

[slicer]
engine = "orca"          # or "cura"
version = "2.3.1"        # "2.3.1" for orca, "5.12.0" for cura

# --- OrcaSlicer config ---
[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"
filaments = ["Generic PLA @base"]

# --- OR CuraEngine config ---
[slicer.cura]
printer = "bambox_p1s"
filaments = ["PLA"]

[[parts]]
file = "model.stl"

# Add overrides to tune print settings:
# [slicer.orca.overrides]
# layer_height = "0.2"
# sparse_infill_density = "20%"
# wall_loops = "3"
```

#### Additional config features

These are optional — skip them for simple setups:

- **`output_dir`** (top-level) — output directory, default `"estampo_output"`.
- **`gcode-info`** stage — add to pipeline to see print time and filament usage after slicing.
- **`bed_type`** in `[slicer]` — bed surface (e.g. `"Textured PEI Plate"`).
- **`profiles_dir`** in `[slicer]` — directory for pinned profiles (default `"profiles"`).
- **`machine_overrides`** / **`filament_overrides`** in `[slicer.orca]` — override machine or filament profile settings (separate from process `overrides`).
- **`[slicer.orca.slots]`** — explicit AMS slot-to-filament mapping:
  ```toml
  [slicer.orca.slots]
  1 = "Generic PLA @base"
  3 = "Generic PETG-CF @base"
  ```
- **`[filaments]`** — material alias table, decoupling parts from specific profiles:
  ```toml
  [filaments]
  structural = "Generic PETG-CF @BBL P1S"
  decorative = "Generic PLA @BBL P1S"
  ```
- **`scale`** on `[[parts]]` — uniform scale factor (default 1.0). Also available as `--scale` CLI flag.
- **`object`** on `[[parts]]` — select a named object from a multi-object 3MF file.
- **`sequence`** on `[[parts]]` — print order for sequential printing.
- **Per-object filament overrides** via `[parts.filaments]`:
  ```toml
  [[parts]]
  file = "widget.3mf"
  filament = "Generic PETG-CF @base"
  [parts.filaments]
  inlay = "Bambu PLA Basic @BBL X1C"
  ```
- **`estampo profiles pin`** — copies referenced profiles into a local `profiles/` directory for reproducible builds across machines.
- **Code-CAD workflow** — estampo works with OpenSCAD, build123d, and CadQuery. Generate STL/3MF from code-CAD scripts, then configure estampo to slice the output.

### Discovering available profiles

```bash
# List all printer profiles
estampo profiles list --engine orca --category machine

# List quality presets
estampo profiles list --engine orca --category process

# List filament profiles
estampo profiles list --engine orca --category filament
```

### Validating the config

```bash
estampo validate estampo.toml
```

This checks: file exists, parts exist, profiles are valid, override keys are
recognized (with "did you mean?" suggestions for typos and cross-engine
detection if you accidentally use CuraEngine setting names with OrcaSlicer or
vice versa).

**Note:** The validation warning "slicer profile names could not be validated"
is expected when profiles are not installed locally. This is not an error —
profiles are resolved at runtime via Docker or the bambox package. The warning
can be safely ignored.

### Common override recipes

Choose overrides based on the print goals:

**Strong functional part (PETG):**
```toml
[slicer.orca.overrides]
wall_loops = "5"
sparse_infill_density = "40%"
sparse_infill_pattern = "gyroid"
top_shell_layers = "6"
bottom_shell_layers = "6"
```

**Fast draft:**
```toml
[slicer.orca.overrides]
sparse_infill_density = "10%"
wall_loops = "2"
enable_support = "0"
```

**Smooth top surface:**
```toml
[slicer.orca.overrides]
ironing_type = "top surface only"
top_shell_layers = "6"
```

**Dimensional accuracy (engineering parts):**
```toml
[slicer.orca.overrides]
xy_hole_compensation = "0.1"
xy_contour_compensation = "-0.05"
outer_wall_speed = "30"
```

**Tree supports for complex overhangs:**
```toml
[slicer.orca.overrides]
enable_support = "1"
support_type = "tree(auto)"
support_threshold_angle = "45"
```

### Setting name reference

OrcaSlicer and CuraEngine use **different names** for the same settings. Use the
correct names for your engine. Key mappings:

| Setting | OrcaSlicer | CuraEngine |
|---------|-----------|------------|
| Layer height | `layer_height` | `layer_height` |
| Wall count | `wall_loops` | `wall_line_count` |
| Top layers | `top_shell_layers` | `top_layers` |
| Bottom layers | `bottom_shell_layers` | `bottom_layers` |
| Infill density | `sparse_infill_density` | `infill_sparse_density` |
| Infill pattern | `sparse_infill_pattern` | `infill_pattern` |
| Supports | `enable_support` | `support_enable` |
| Support type | `support_type` | — |
| Support angle | `support_threshold_angle` | `support_angle` |
| Brim type | `brim_type` | `adhesion_type` |
| Brim width | `brim_width` | `brim_width` |
| First layer speed | `initial_layer_speed` | `speed_layer_0` |
| First layer infill speed | `initial_layer_infill_speed` | — |
| Outer wall speed | `outer_wall_speed` | `speed_wall_0` |
| Inner wall speed | `inner_wall_speed` | `speed_wall_x` |
| Travel speed | `travel_speed` | `speed_travel` |
| Fan min speed | `fan_min_speed` | `cool_fan_speed_min` |
| Fan max speed | `fan_max_speed` | `cool_fan_speed_max` |
| Disable fan for first N layers | `close_fan_the_first_x_layers` | `cool_fan_full_layer` |
| Retraction dist | `retraction_length` | `retraction_amount` |
| Nozzle temp | `nozzle_temperature` | `material_print_temperature` |
| First layer nozzle temp | `nozzle_temperature_initial_layer` | `material_print_temperature_layer_0` |
| Bed temp | `bed_temperature` | `material_bed_temperature` |
| Ironing | `ironing_type` | `ironing_enabled` |
| Seam position | `seam_position` | `z_seam_type` |
| XY hole compensation | `xy_hole_compensation` | `hole_xy_offset` |

**CRITICAL: Setting names differ between slicers.** OrcaSlicer uses `initial_layer_speed`,
not `first_layer_speed`. OrcaSlicer uses `wall_loops`, not `wall_line_count`. Using the
wrong engine's setting name will be **silently ignored** — the slicer never sees it.
Always look up the correct name from this table or the JSON files below.

For the complete list of all settings:
- OrcaSlicer: 263 settings in [`orca-settings.json`](https://github.com/estampo/estampo/blob/main/docs/orca-settings.json)
- CuraEngine: 711 settings in [`cura-settings.json`](https://github.com/estampo/estampo/blob/main/docs/cura-settings.json)
- Full reference: [`llm.md`](https://github.com/estampo/estampo/blob/main/docs/llm.md)
- JSON Schema for TOML validation: [`estampo.schema.json`](https://github.com/estampo/estampo/blob/main/docs/estampo.schema.json)

### GitHub Actions (optional)

estampo provides a GitHub Action that works with both OrcaSlicer and CuraEngine.
It reads the engine and version from your `estampo.toml` and pulls the correct
Docker image automatically. The image includes the slicer, bambox, and printer
definitions — no extra installation needed.

```yaml
name: Slice
on: [push]

jobs:
  slice:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: estampo/estampo/action@v1
        with:
          config: estampo.toml
```

The action runs the full pipeline, uploads artifacts, and posts build metrics
(print time, filament usage) as a PR comment. **Do not install estampo as a bare
pip/pipx tool on the runner** — use the action instead, which has all
dependencies pre-installed in Docker.

### Post-processing for Bambu Lab printers

If the printer is a Bambu Lab printer (P1S, X1C, A1, etc.), you **must** add a
`pack` stage to produce the `.gcode.3mf` file that Bambu printers require. Use
[bambox](https://github.com/estampo/bambox) for this. **The pack stage is not
optional** — without it, the output is plain G-code that Bambu printers cannot
use.

The command differs by slicer engine:

**CuraEngine** (creates `.gcode.3mf` from plain G-code):
```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[pack]
command = "bambox pack {sliced_dir}/plate.gcode -o {output_dir}/plate.gcode.3mf"
output = "{output_dir}/plate.gcode.3mf"
```

**OrcaSlicer** (patches the existing `.gcode.3mf` for Bambu Connect compatibility):
```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[pack]
command = "bambox repack {sliced_3mf}"
output = "{sliced_3mf}"
```

Both `bambox pack` and `bambox repack` are pre-installed in the Docker images,
so no extra installation is needed when using the GitHub Action or `docker run`
approach above.

### Cloud printing for Bambu Lab printers (optional)

To send the `.gcode.3mf` directly to a Bambu printer, use `bambox print`.
**Do not add a print stage to `estampo.toml`** — printing should be an
explicit manual action, not something that runs on every `estampo run` or
CI push.

**Local printing** (after `estampo run` produces the `.gcode.3mf`):
```bash
bambox print estampo_output/plate.gcode.3mf -y
```

If only one printer is configured, bambox uses it automatically — no
`-d DEVICE_SERIAL` needed.

**Setup requirements:**
1. Run `bambox login` once to authenticate with Bambu Cloud — credentials are
   saved to `~/.config/bambox/credentials.toml`
2. The bridge is required: native binary on Linux x86_64, Docker on all other
   platforms (macOS, Windows, Linux ARM64)

**For CI:** add a separate manually-triggered workflow (not the slice
workflow) so printing only happens when explicitly requested:

```yaml
# .github/workflows/print.yml
name: Print

on:
  workflow_dispatch:

jobs:
  print:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Write credentials
        run: |
          mkdir -p ~/.config/bambox
          echo "$BAMBOX_CREDENTIALS" > ~/.config/bambox/credentials.toml
        env:
          BAMBOX_CREDENTIALS: ${{ secrets.BAMBOX_CREDENTIALS }}
      - uses: estampo/estampo/action@v1
        with:
          config: estampo.toml
          comment: "false"
      - name: Print
        run: |
          docker run --rm \
            -v "${{ github.workspace }}:/project" \
            -v "$HOME/.config/bambox:/home/estampo/.config/bambox:ro" \
            --workdir /project \
            --entrypoint bambox \
            ghcr.io/estampo/estampo:cura-5.12.0 \
            print estampo_output/plate.gcode.3mf -y
```

To set up the secret: run `bambox login` locally, then copy the contents of
`~/.config/bambox/credentials.toml` into a GitHub repository secret named
`BAMBOX_CREDENTIALS`.

### Important rules

- **Do not invent setting names.** Only use keys from the setting name
  reference table above or from the JSON files. OrcaSlicer and CuraEngine
  use completely different names — guessing from PrusaSlicer or general
  slicer knowledge will produce wrong keys that are **silently ignored**.
  When in doubt, search the JSON file for the setting you need.
- **Do not force slicer settings** that conflict with the printer's machine
  profile (e.g. `use_relative_e_distances`). Let the profile chain decide.
- **Use string values** for OrcaSlicer overrides (they are passed as CLI
  arguments): `layer_height = "0.2"`, not `layer_height = 0.2`.
- **Pin the slicer version** for reproducibility.
- estampo runs slicers inside Docker by default. GitHub Actions runners have
  Docker available, so `estampo run` works out of the box in CI.

### Verifying the config

After creating or modifying the config, always verify:

```bash
# 1. Validate — must exit 0 with no errors
estampo validate

# 2. Test slice — catches profile and override issues
estampo run --until slice
```

`estampo validate` exits non-zero if any override keys are invalid. Fix all
errors before proceeding — invalid keys are silently dropped by the slicer,
so the print won't match what the user asked for.

### Command stage variables

Command stages use `{variable}` placeholders that are substituted at runtime.
Only use these exact variable names — estampo will error on unknown variables.

| Variable | Available after | Description |
|----------|----------------|-------------|
| `{name}` | always | Project name from TOML config (empty if unset) |
| `{output_dir}` | always | Output directory path |
| `{engine}` | always | Slicer engine name (`orca` or `cura`) |
| `{machine}` | always | Printer/machine profile name (empty if unset) |
| `{filament}` | always | First filament profile name (empty if unset) |
| `{filaments}` | always | All filament profiles, comma-separated |
| `{slicer_image}` | always | Docker image tag for the active slicer |
| `{input_3mf}` | `plate` | Plate 3MF file path |
| `{sliced_3mf}` | `slice` | Sliced output file (`.gcode.3mf` for OrcaSlicer, `.gcode` for CuraEngine) |
| `{sliced_dir}` | `slice` | Slicer output directory |
| `{cura_settings}` | `slice` | CuraEngine settings JSON path (CuraEngine only, empty for OrcaSlicer) |

Command stage outputs are also available as variables to downstream stages.
For example, if a `resolve_templates` stage has `output = "..."`, the next
stage can reference `{resolve_templates}`.
````

---

## How to use this prompt

1. Copy the prompt above (everything between the ```` ``` ```` fences).
2. Paste it into your AI assistant — no editing needed.
3. The AI will scan your project for model files, ask you a few questions
   (printer, filament, print goals), then create the config and validate it.

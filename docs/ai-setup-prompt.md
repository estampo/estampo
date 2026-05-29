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
   **Rule: use `orca` for Bambu Lab printers, `cura` for everything else.**
   estampo ships 35 bundled Orca machine profiles (all Bambu Lab: A1, P1P,
   P1S, X1, X1 Carbon, X1E) and 643 bundled Cura profiles (Creality, Prusa,
   Voron, Ultimaker, Anycubic, Elegoo, and hundreds more). Picking `orca`
   for a non-BBL printer means no bundled machine profile — the user would
   have to supply their own.
2. **Which printer?** — e.g. `Bambu Lab P1S 0.4 nozzle` (OrcaSlicer) or
   `bambox_p1s` (CuraEngine). Run `estampo profiles list --engine orca --category machine`
   to see available profiles.
3. **Which quality preset?** — OrcaSlicer only, e.g. `0.20mm Standard @BBL X1C`.
   **Always pass `--printer` to narrow the list** to processes that actually work
   with the chosen printer — OrcaSlicer silently fails at slice time (exit 239)
   if the process and printer are incompatible:
   ```bash
   estampo profiles list --engine orca --category process --printer "Bambu Lab P1S 0.4 nozzle"
   ```
4. **Which filament(s)?** — e.g. `Generic PLA @base`, `Generic PETG @base`.
   Same guidance: pass `--printer` to filter filaments to ones compatible with
   the printer:
   ```bash
   estampo profiles list --engine orca --category filament --printer "Bambu Lab P1S 0.4 nozzle"
   ```

   **Default to `Generic <type> @base` unless the user explicitly tells you
   they are loading that vendor's own filament.** Vendor-branded profiles
   (`Bambu PLA Basic`, `Polymaker PolyTerra PLA`, `eSUN ...`, etc.) bake in a
   high `filament_max_volumetric_speed` (often 21 mm³/s) that only the
   vendor's actual filament can sustain. Picking `Bambu PLA Basic` when the
   user has loaded any other PLA causes severe under-extrusion (wavy walls,
   missed features, failed in-place parts) — the slicer plans a flow rate
   the hotend can't physically deliver. Match the profile to the *real
   filament in the printer*, not just the printer brand. When unsure, ask
   the user "is this filament made by <printer vendor>, or is it
   generic/third-party?" and pick `Generic ...` for anything that isn't a
   confirmed match.
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
bed_type = "Textured PEI Plate"   # required for Bambu printers — see note below

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
file = "model.stl"       # .stl, .3mf, or .step / .stp — all three are accepted directly

# Add overrides to tune print settings:
# [slicer.orca.overrides]
# layer_height = "0.2"
# sparse_infill_density = "20%"
# wall_loops = "3"
```

**STEP files are loaded natively** — estampo uses [build123d](https://github.com/gumyr/build123d) to
convert STEP to a mesh at the start of the pipeline. Do **not** tell the user to pre-convert STEP
to STL/3MF; point a `[[parts]]` entry directly at the `.step` or `.stp` file.

#### Orientation — `orient` and `rotate`

Every part is placed with Z pointing up (Z is bed-normal). After any rotation,
estampo automatically drops the part so its lowest point sits on the bed
(`z = 0`) — never add manual Z translation.

There are **two** orientation fields on `[[parts]]`:

- **`orient`** — a named preset (string). One of:
  - `"flat"` *(default)* — auto-rotate so the **smallest** extent is along Z.
    The part ends up resting on its largest face. Use this for functional
    parts where you want minimum supports and maximum bed adhesion.
  - `"upright"` — **no rotation**; keep the mesh's native orientation from
    the source file. Use this for STEP files from CAD and for code-CAD
    output (build123d / CadQuery / OpenSCAD), where the author already
    oriented the part. Also the right choice for parts that only make sense
    one way up — bottles, figurines, brackets with a designed mating face.
  - `"side"` — rotate 90° about X. For meshes authored Y-up.
  - `"upside-down"` — rotate 180° about X. Flips the part so its top is on
    the bed.

- **`rotate = [rx, ry, rz]`** — an arbitrary rotation in **degrees** about the
  X, Y, and Z axes (applied in that order). Use when no preset fits. Examples:
  - `[0, 0, 45]` — yaw 45° on the bed (diagonal fit).
  - `[180, 0, 0]` — flip upside-down.
  - `[90, 0, 0]` — tip onto the front face.

**Rules:**

- If `rotate` is set, it **fully overrides** `orient`. Don't set both — the
  `orient` value becomes dead config.
- Default to `orient = "upright"` for parts generated from STEP or code-CAD
  (the author already oriented them). Default to `orient = "flat"` only when
  the mesh orientation is unknown or the goal is auto-lay-flat.
- Do not invent other preset names. The full set of valid `orient` values is
  exactly: `"flat"`, `"upright"`, `"side"`, `"upside-down"`. Any other string
  fails validation.

**Always set `bed_type` for Bambu Lab printers.** The OrcaSlicer machine profile
for Bambu printers defaults to `"Cool Plate"`, but the plate that physically ships
with a P1S / P1P / A1 / A1 mini / X1C is the **Textured PEI Plate**, which sits
higher than the Cool Plate. If you leave `bed_type` unset and print a slice
calibrated for Cool Plate on a physical PEI plate, the nozzle's first-layer Z is
too low and can crash into the plate, damaging the hotend or the plate surface.
Ask the user which plate is actually installed if unsure; do not rely on the
profile default.

#### Additional config features

These are optional — skip them for simple setups:

- **`output_dir`** (top-level) — output directory, default `"estampo_output"`.
- **`gcode-info`** stage — add to pipeline to see print time and filament usage after slicing.
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
  inlay = "Generic PLA @base"
  ```
- **`estampo profiles pin`** — copies referenced profiles into a local `profiles/` directory for reproducible builds across machines.
- **Code-CAD workflow** — estampo works with OpenSCAD, build123d, and CadQuery. Either emit STL/3MF from the code-CAD script, or emit STEP and let estampo load it directly via build123d — no pre-conversion required.

### Discovering available profiles

```bash
# List all printer profiles
estampo profiles list --engine orca --category machine

# List only the quality presets compatible with a specific printer.
# IMPORTANT: prefer this over listing all processes — picking an
# incompatible process/printer combo fails silently at slice time with
# exit 239. The --printer flag filters by the resolved compatible_printers
# field so the result is correctness-preserving.
estampo profiles list --engine orca --category process \
  --printer "Bambu Lab P1S 0.4 nozzle"

# Same pattern for filament — compatible_printers applies there too.
estampo profiles list --engine orca --category filament \
  --printer "Bambu Lab P1S 0.4 nozzle"

# --printer works with --json for parsable output.
estampo profiles list --engine orca --category process \
  --printer "Bambu Lab P1S 0.4 nozzle" --json
```

`--printer` is OrcaSlicer only. CuraEngine uses inline settings with no
process/filament concept, so the flag errors for `--engine cura`.

### Validating the config

```bash
estampo validate estampo.toml
```

This checks: file exists, parts exist, profiles are valid, override keys are
recognized (with "did you mean?" suggestions for typos and cross-engine
detection if you accidentally use CuraEngine setting names with OrcaSlicer or
vice versa).

**Note:** If validation warns that profile names could not be validated, it
means no profiles are available locally. Run `estampo profiles pin` to extract
them from the Docker image. Profiles are also resolved at runtime via Docker,
so this warning is non-blocking.

### Pinning profiles for reproducibility

After creating the config, pin the referenced slicer profiles into the project
so builds are reproducible across machines and CI — regardless of what's
installed locally:

```bash
estampo profiles pin
```

This extracts profiles from the Docker image (using the `slicer.version` in your
config), squashes the inheritance chain, and writes standalone definition files
to `profiles/`. **Commit the `profiles/` directory to git.**

For CuraEngine configs using custom printer definitions (e.g. `bambox_p1s`),
pinning is **required for non-bundled printers** — the definition file only
exists inside the Docker image and is not bundled in the pip package. Without
pinning, `estampo run --local` will fail, and teammates who clone the repo
will see an empty `profiles/` directory.

### Common override recipes

Choose overrides based on the print goals:

**Strong functional part (PETG):**
```toml
[slicer.orca.overrides]
wall_loops = "5"           # starting point — increase to 6–8 for thin-walled structural parts
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
on:
  push:
    branches: [main]
  pull_request:

jobs:
  slice:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      # If STL/STEP files are generated by a build script (not committed to git):
      # - name: Build models
      #   run: python build.py  # or: make, ./generate.sh, uv run build.py, etc.
      - uses: estampo/estampo/action@v0
        with:
          config: estampo.toml
```

The action runs the full pipeline, uploads artifacts, and posts build metrics
(print time, filament usage) as a PR comment. **Do not install estampo as a bare
pip/pipx tool on the runner** — use the action instead, which has all
dependencies pre-installed in Docker.

To generate just the workflow file for an existing project:
```bash
estampo init --workflow-only
```
This requires an existing `estampo.toml` — it will error if the config file is missing.

#### Projects with build scripts (code-CAD)

If the project generates mesh files (STL, 3MF, or STEP) from OpenSCAD,
build123d, or CadQuery via a build script, and the generated files are
`.gitignore`d, the CI runner won't have them. Add a build step before the
estampo action. (If the STEP files are committed to the repo, skip this — estampo loads STEP directly.)

```yaml
    steps:
      - uses: actions/checkout@v4
      - name: Build models
        run: python build.py  # or make, ./generate.sh, etc.
      - uses: estampo/estampo/action@v0
        with:
          config: estampo.toml
```

### Post-processing for Bambu Lab printers

If the printer is a Bambu Lab printer (P1S, X1C, A1, etc.), you **must** add a
`pack` stage to produce the `.gcode.3mf` file that Bambu printers require. Use
[bambox](https://github.com/estampo/bambox) for this. **The pack stage is not
optional** — without it, the output is plain G-code that Bambu printers cannot
use.

The command differs by slicer engine:

**CuraEngine** (resolve template gcode variables, then pack):

CuraEngine printer definitions (e.g. `bambox_p1s`) use template variables like
`{material_bed_temperature_layer_0}` in their start/end G-code. These **must** be
resolved before packing — otherwise the printer receives literal template strings
instead of actual values, which causes temperature errors or dangerous behavior.

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "resolve_templates", "pack"]

[resolve_templates]
command = "cura-p1s resolve {sliced_dir}/plate.gcode --settings {cura_settings}"
docker = true

[pack]
command = "bambox pack {sliced_dir}/plate.gcode -o {output_dir}/plate.gcode.3mf"
output = "{output_dir}/plate.gcode.3mf"
docker = true
```

**The `resolve_templates` stage is required for CuraEngine + Bambu printers.**
Without it, `estampo validate` will report an error. The `cura-p1s` and `bambox`
tools are pre-installed in the Docker images — `docker = true` runs the command
inside the slicer container so they don't need to be installed locally.

**OrcaSlicer** (patches the existing `.gcode.3mf` for Bambu Connect compatibility):
```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[pack]
command = "bambox repack {sliced_3mf}"
output = "{sliced_3mf}"
docker = true
```

`docker = true` runs the command inside the slicer Docker image where `bambox`
is pre-installed. This is the default for locally generated configs — no extra
host-side installation needed.

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
- **Pin profiles** with `estampo profiles pin` and commit the `profiles/`
  directory. This makes builds reproducible without depending on locally
  installed slicer profiles or Docker image contents.
- estampo runs slicers inside Docker by default. GitHub Actions runners have
  Docker available, so `estampo run` works out of the box in CI.

### Safety

estampo generates G-code but does not verify that settings are safe for the
user's printer. When suggesting or modifying overrides:

- **Never set temperatures above the filament manufacturer's recommendations.**
  Excessive nozzle or bed temperatures can damage the printer or create a fire
  hazard.
- **Always recommend supports for overhangs** unless the user explicitly says
  otherwise. Unsupported overhangs can cause print failures and wasted material.
- **Warn the user to review the sliced output** before sending to a printer,
  especially when using AI-generated settings for the first time.
- **`estampo validate` checks config correctness, not print safety.** A config
  that passes validation can still produce unsafe G-code if the override values
  are wrong for the hardware.

### Verifying the config

After creating or modifying the config, always verify:

```bash
# 1. Validate — must exit 0 with no errors
estampo validate

# 2. Pin profiles for reproducibility
estampo profiles pin

# 3. Full run — executes every pipeline stage, producing the final artifact
estampo run
```

Run the full pipeline, not `estampo run --until slice`. `--until slice` stops
**before** the `pack` stage (and before `resolve_templates` for CuraEngine),
so it will not surface:

- malformed `bambox` invocations in `[pack]`
- a missing `docker = true` on the pack stage
- template-resolution errors in the CuraEngine → `resolve_templates` → `pack` flow

A full `estampo run` does not touch any printer — the output is a `.gcode.3mf`
(or equivalent) on disk. It is safe to run as a verification step.

`estampo validate` exits non-zero if any override keys are invalid. Fix all
errors before proceeding — invalid keys are silently dropped by the slicer,
so the print won't match what the user asked for.

**Running locally:** use the installed `estampo` CLI directly — do not add
estampo to the user's project dependencies. If the user has a pre-release
version installed (e.g. `0.4.0b4.dev`), that is the one to use; don't try to
pin estampo itself in the project's `pyproject.toml`.

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

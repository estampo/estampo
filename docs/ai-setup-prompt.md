# Add estampo to a 3D printing project

> **What this is:** A prompt template you can give to an AI assistant (Claude,
> ChatGPT, Copilot, etc.) to add estampo support to a GitHub project that
> contains 3D-printable models. Replace the `{PLACEHOLDERS}` with your
> project-specific values and paste the whole thing as a prompt.

---

## The prompt

````markdown
I want to add **estampo** to this project so that 3D printing is automated and
reproducible. estampo is a declarative build system for 3D prints — you write a
TOML config file and it handles the full pipeline: load meshes, arrange on the
build plate, slice with OrcaSlicer or CuraEngine, and optionally run
post-processing command stages.

### What I need you to do

1. Install estampo (add it to the project's dev dependencies or document the
   install command).
2. Create an `estampo.toml` config file in the repo root.
3. Validate the config.
4. Optionally add a GitHub Actions workflow that slices on every push.

### My project details

- **Model files:** `{MODEL_FILES}`
  (e.g. `bracket.stl`, `housing.step`, `parts/*.3mf`)
- **Slicer engine:** `{ENGINE}`
  (`orca` for OrcaSlicer, or `cura` for CuraEngine)
- **Printer:** `{PRINTER}`
  (e.g. `Bambu Lab P1S 0.4 nozzle` for OrcaSlicer, `bambox_p1s` for CuraEngine)
- **Quality preset:** `{PROCESS}`
  (e.g. `0.20mm Standard @BBL X1C` — OrcaSlicer only, omit for CuraEngine)
- **Filament(s):** `{FILAMENTS}`
  (e.g. `Generic PLA @base`, `Generic PETG @base`)
- **Print goals:** `{GOALS}`
  (e.g. "strong functional part", "fast draft", "smooth top surface",
  "flexible TPU part", "multi-color decorative")

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

Use the non-interactive init command:

```bash
estampo init \
  --engine {ENGINE} \
  --printer "{PRINTER}" \
  --filament "{FILAMENT_1}" \
  --part {MODEL_FILE_1} \
  --part {MODEL_FILE_2}
```

Or create `estampo.toml` directly. Here is the structure:

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice"]

[plate]
size = [256, 256]        # bed size in mm [width, depth]

[slicer]
engine = "{ENGINE}"
version = "{VERSION}"    # "2.3.1" for orca, "5.12.0" for cura

# --- OrcaSlicer config ---
[slicer.orca]
printer = "{PRINTER}"
process = "{PROCESS}"
filaments = ["{FILAMENT_1}"]

# --- OR CuraEngine config ---
[slicer.cura]
printer = "{PRINTER}"
filaments = ["{FILAMENT_1}"]

[[parts]]
file = "{MODEL_FILE}"

# Add overrides to tune print settings:
# [slicer.orca.overrides]
# layer_height = "0.2"
# sparse_infill_density = "20%"
# wall_loops = "3"
```

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
| Infill density | `sparse_infill_density` | `infill_sparse_density` |
| Infill pattern | `sparse_infill_pattern` | `infill_pattern` |
| Supports | `enable_support` | `support_enable` |
| Support angle | `support_threshold_angle` | `support_angle` |
| Travel speed | `travel_speed` | `speed_travel` |
| Retraction dist | `retraction_length` | `retraction_amount` |
| Nozzle temp | `nozzle_temperature` | `material_print_temperature` |
| Bed temp | `bed_temperature` | `material_bed_temperature` |

For the complete list of all settings:
- OrcaSlicer: 263 settings in [`orca-settings.json`](https://github.com/estampo/estampo/blob/main/docs/orca-settings.json)
- CuraEngine: 711 settings in [`cura-settings.json`](https://github.com/estampo/estampo/blob/main/docs/cura-settings.json)
- Full reference: [`llm.md`](https://github.com/estampo/estampo/blob/main/docs/llm.md)
- JSON Schema for TOML validation: [`estampo.schema.json`](https://github.com/estampo/estampo/blob/main/docs/estampo.schema.json)

### GitHub Actions (optional)

Add this workflow to `.github/workflows/slice.yml` to slice on every push:

```yaml
name: Slice
on: [push]

jobs:
  slice:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv tool install estampo
      - run: estampo validate
      - run: estampo run --local -v
      - uses: actions/upload-artifact@v4
        with:
          name: sliced
          path: output/
```

### Post-processing for Bambu Lab printers

If sending to a Bambu Lab printer, add a `pack` stage using
[bambox](https://github.com/estampo/bambox):

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[pack]
command = "bambox repack {output_dir}/plate_sliced.gcode.3mf"
output = "{output_dir}/plate_sliced.gcode.3mf"
```

### Important rules

- **Do not invent setting names.** Only use keys from the setting lists above
  or from the JSON files. estampo validates overrides and will reject unknown
  keys.
- **Do not force slicer settings** that conflict with the printer's machine
  profile (e.g. `use_relative_e_distances`). Let the profile chain decide.
- **Use string values** for OrcaSlicer overrides (they are passed as CLI
  arguments): `layer_height = "0.2"`, not `layer_height = 0.2`.
- **Pin the slicer version** for reproducibility.
- estampo runs slicers inside Docker by default. In CI (GitHub Actions), use
  `--local` since the runner already has the slicer installed via the Docker
  image.
````

---

## How to use this prompt

1. Copy the prompt above (everything between the ```` ``` ```` fences).
2. Replace the `{PLACEHOLDERS}` with your project details.
3. Paste into your AI assistant.
4. The AI will create the config, validate it, and optionally set up CI.

### Example: filled-in prompt for a Bambu P1S with PLA

> - **Model files:** `case.stl`, `lid.stl`
> - **Slicer engine:** `orca`
> - **Printer:** `Bambu Lab P1S 0.4 nozzle`
> - **Quality preset:** `0.20mm Standard @BBL X1C`
> - **Filament(s):** `Generic PLA @base`
> - **Print goals:** strong functional part with tree supports

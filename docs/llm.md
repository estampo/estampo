# estampo reference

> This file is a concise reference for both humans and AI assistants.
> For the full JSON Schema, see [`estampo.schema.json`](estampo.schema.json).

estampo is a declarative build system for reproducible 3D prints. You write
an `estampo.toml` config file, and estampo handles the pipeline: load meshes,
arrange on the build plate, slice with OrcaSlicer or CuraEngine, and run
post-processing command stages (e.g. repack for Bambu Lab printers).

## Quick reference

```toml
name = "my-project"                    # optional, prefixes output dir

[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[plate]
size = [256, 256]                      # bed size in mm [width, depth]
padding = 5.0                          # gap between parts in mm

[slicer]
engine = "orca"                        # "orca" or "cura"
version = "2.3.1"                      # pin for reproducibility

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"
filaments = ["Generic PLA @base"]

[[parts]]
file = "model.stl"

[pack]
command = "bambox repack {output_dir}/plate_sliced.gcode.3mf"
output = "{output_dir}/plate_sliced.gcode.3mf"
```

## Config structure

| Section | Purpose |
|---------|---------|
| Top-level `name`, `output_dir` | Project metadata |
| `[pipeline]` | Which stages to run, in order |
| `[plate]` | Build plate dimensions |
| `[slicer]` | Engine choice, version, bed type |
| `[slicer.orca]` | OrcaSlicer profiles and overrides |
| `[slicer.cura]` | CuraEngine printer definition and overrides |
| `[filaments]` | Material aliases (short name -> profile name) |
| `[[parts]]` | Mesh files to print (at least one required) |
| `[stagename]` | Custom command stages (e.g. `[pack]`, `[resolve_templates]`) |

## Slicer engines

### OrcaSlicer (`engine = "orca"`)

Uses a profile chain: **printer** (machine) -> **process** (quality) -> **filament(s)**.

```toml
[slicer]
engine = "orca"
version = "2.3.1"                      # current stable

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"   # machine profile
process = "0.20mm Standard @BBL X1C"   # quality preset
filaments = ["Generic PLA @base"]      # one per AMS slot
```

Run `estampo profiles list --engine orca` to discover available profiles.

Common override keys (OrcaSlicer names):

| Setting | Key | Example |
|---------|-----|---------|
| Infill density | `sparse_infill_density` | `"20%"` |
| Infill pattern | `sparse_infill_pattern` | `"gyroid"` |
| Wall count | `wall_loops` | `3` |
| Layer height | `layer_height` | `0.2` |
| Supports | `enable_support` | `1` |
| Support angle | `support_threshold_angle` | `45` |
| Seam position | `seam_position` | `"random"` |
| Top layers | `top_shell_layers` | `5` |
| Bottom layers | `bottom_shell_layers` | `4` |
| Ironing | `ironing_type` | `"top surface only"` |
| Brim | `brim_type` | `"outer_only"` |
| Print speed | `outer_wall_speed` | `60` |
| Travel speed | `travel_speed` | `400` |
| Temperature | `nozzle_temperature` | `"220"` |

### CuraEngine (`engine = "cura"`)

Uses printer definition files (`.def.json`). Different setting names from OrcaSlicer.

```toml
[slicer]
engine = "cura"
version = "5.12.0"                     # current stable

[slicer.cura]
printer = "bambox_p1s"                 # definition name or ID
```

Common override keys (CuraEngine names):

| Setting | Key | Example |
|---------|-----|---------|
| Infill density | `infill_sparse_density` | `20` |
| Infill pattern | `infill_pattern` | `"gyroid"` |
| Wall count | `wall_line_count` | `3` |
| Layer height | `layer_height` | `0.2` |
| Supports | `support_enable` | `true` |
| Support angle | `support_angle` | `45` |
| Print speed | `speed_print` | `60` |
| Top layers | `top_layers` | `5` |
| Bottom layers | `bottom_layers` | `4` |

## Parts

```toml
[[parts]]
file = "model.stl"          # required — .stl, .3mf, .step, .stp, .obj
copies = 2                   # default: 1
orient = "upright"           # "flat" (default), "upright", "side", "upside-down"
rotate = [0, 0, 45]          # [rx, ry, rz] degrees — overrides orient
filament = 1                 # slot number (1-indexed) or profile name/alias
scale = 1.5                  # uniform scale factor, default: 1.0
```

For multi-object 3MF files, assign filaments per object:

```toml
[[parts]]
file = "assembly.3mf"
filament = 1
[parts.filaments]
inlay = 2                    # object "inlay" uses filament slot 2
```

## Multi-filament

Option 1 — filaments list (order = slot assignment):

```toml
[slicer.orca]
filaments = ["Generic PLA @base", "Generic PETG @base"]

[[parts]]
file = "body.stl"
filament = 1                 # first filament (PLA)

[[parts]]
file = "accent.stl"
filament = 2                 # second filament (PETG)
```

Option 2 — named aliases:

```toml
[filaments]
structural = "Generic PETG-CF @base"
decorative = "Generic PLA @base"

[slicer.orca]
filaments = ["Generic PLA @base", "Generic PETG-CF @base"]

[[parts]]
file = "body.stl"
filament = "structural"

[[parts]]
file = "cap.stl"
filament = "decorative"
```

## Command stages

Custom pipeline stages that run external CLI tools. Add the stage name to
`[pipeline].stages` and define a matching TOML section with a `command` key.

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[pack]
command = "bambox repack {output_dir}/plate_sliced.gcode.3mf"
output = "{output_dir}/plate_sliced.gcode.3mf"
```

### Available variables

| Variable | Description | Available |
|----------|-------------|-----------|
| `{name}` | Project name (empty if unset) | Always |
| `{output_dir}` | Output directory path | Always |
| `{machine}` | Printer name (empty if unset) | Always |
| `{engine}` | `"orca"` or `"cura"` | Always |
| `{filament}` | First filament profile | Always |
| `{filaments}` | All filaments, comma-separated | Always |
| `{input_3mf}` | Plate 3MF path | After `plate` |
| `{sliced_3mf}` | Packaged 3MF after slicing | After `slice` |
| `{sliced_dir}` | Slicer output directory | After `slice` |
| `{cura_settings}` | CuraEngine settings JSON | After `slice` (cura only) |
| `{slicer_image}` | Docker image tag | Always |

### Docker wrapping

Run a command inside the slicer Docker container:

```toml
[resolve_templates]
command = "cura-p1s resolve {sliced_dir}/plate.gcode --settings {cura_settings}"
docker = true
```

## Common recipes

### OrcaSlicer + Bambu Lab (most common)

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[plate]
size = [256, 256]
padding = 5.0

[slicer]
engine = "orca"
version = "2.3.1"
bed_type = "Textured PEI Plate"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"
filaments = ["Generic PLA @base"]

[[parts]]
file = "model.stl"

[pack]
command = "bambox repack {output_dir}/plate_sliced.gcode.3mf"
output = "{output_dir}/plate_sliced.gcode.3mf"
```

### CuraEngine + Bambu Lab

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "resolve_templates", "pack"]

[plate]
size = [256, 256]
padding = 5.0

[slicer]
engine = "cura"
version = "5.12.0"

[slicer.cura]
printer = "bambox_p1s"
filaments = ["PLA"]

[slicer.cura.overrides]
infill_sparse_density = 20
layer_height = 0.2

[[parts]]
file = "model.stl"

[resolve_templates]
command = "cura-p1s resolve {sliced_dir}/plate.gcode --settings {cura_settings}"

[pack]
command = "bambox pack {sliced_dir}/plate.gcode -o {output_dir}/plate.gcode.3mf"
output = "{output_dir}/plate.gcode.3mf"
```

### Strength-optimized PETG

```toml
[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"
filaments = ["Generic PETG @base"]

[slicer.orca.overrides]
wall_loops = "5"
sparse_infill_density = "40%"
sparse_infill_pattern = "gyroid"
top_shell_layers = "6"
bottom_shell_layers = "6"
```

### Speed-optimized draft

```toml
[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.28mm Draft @BBL X1C"
filaments = ["Generic PLA @base"]

[slicer.orca.overrides]
sparse_infill_density = "10%"
wall_loops = "2"
enable_support = "0"
```

## CLI commands

```
estampo run [config]              # run the pipeline
estampo run config.toml --until plate   # stop before slicing
estampo run config.toml --local   # force local slicer (no Docker)
estampo run config.toml -v        # verbose output

estampo init                      # interactive wizard
estampo init --template           # print commented template to stdout
estampo validate config.toml      # check config for errors

estampo profiles list --engine orca              # list available profiles
estampo profiles list --engine orca --category machine  # just printers
estampo profiles pin config.toml                 # pin profiles for reproducibility
```

## Running in CI

```yaml
- uses: estampo/estampo/action@main
  with:
    config: estampo.toml
    comment: "true"
```

Or with Docker directly:

```bash
docker run --rm -v "$PWD:/project" --workdir /project \
  ghcr.io/estampo/estampo:orca-2.3.1 \
  run estampo.toml --local -v
```

## Setting name differences

OrcaSlicer and CuraEngine use different names for the same settings.
Use the correct names in `[slicer.orca.overrides]` or `[slicer.cura.overrides]`.

| Concept | OrcaSlicer key | CuraEngine key |
|---------|---------------|----------------|
| Infill density | `sparse_infill_density` | `infill_sparse_density` |
| Infill pattern | `sparse_infill_pattern` | `infill_pattern` |
| Wall count | `wall_loops` | `wall_line_count` |
| Layer height | `layer_height` | `layer_height` |
| Enable supports | `enable_support` | `support_enable` |
| Support angle | `support_threshold_angle` | `support_angle` |
| Top solid layers | `top_shell_layers` | `top_layers` |
| Bottom solid layers | `bottom_shell_layers` | `bottom_layers` |
| Print speed | `outer_wall_speed` | `speed_print` |
| Seam position | `seam_position` | `z_seam_type` |
| Brim | `brim_type` | `adhesion_type` |
| Retraction distance | `retraction_length` | `retraction_amount` |

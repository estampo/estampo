# estampo reference

> This file is a concise reference for both humans and AI assistants.
> For the full JSON Schema, see [`estampo.schema.json`](estampo.schema.json).
> For complete slicer setting lists, see [`orca-settings.json`](orca-settings.json)
> (263 settings) and [`cura-settings.json`](cura-settings.json) (711 settings).

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

Common override keys (OrcaSlicer names) — for all 113 process settings, see
[`orca-settings.json`](orca-settings.json):

| Setting | Key | Example |
|---------|-----|---------|
| **Quality** | | |
| Layer height | `layer_height` | `0.2` |
| First layer height | `initial_layer_print_height` | `0.28` |
| Line width | `line_width` | `0.42` |
| Outer wall line width | `outer_wall_line_width` | `0.42` |
| **Walls & surfaces** | | |
| Wall count | `wall_loops` | `3` |
| Top layers | `top_shell_layers` | `5` |
| Bottom layers | `bottom_shell_layers` | `4` |
| Detect thin walls | `detect_thin_wall` | `1` |
| One wall on top | `only_one_wall_top` | `1` |
| Seam position | `seam_position` | `"random"` |
| Ironing | `ironing_type` | `"top surface only"` |
| **Infill** | | |
| Infill density | `sparse_infill_density` | `"20%"` |
| Infill pattern | `sparse_infill_pattern` | `"gyroid"` |
| Min sparse area | `minimum_sparse_infill_area` | `15` |
| **Speed** | | |
| Outer wall speed | `outer_wall_speed` | `60` |
| Inner wall speed | `inner_wall_speed` | `80` |
| Infill speed | `sparse_infill_speed` | `100` |
| Travel speed | `travel_speed` | `400` |
| Bridge speed | `bridge_speed` | `25` |
| Overhang speed | `overhang_speed_classic` | `20` |
| **Supports** | | |
| Enable supports | `enable_support` | `1` |
| Support type | `support_type` | `"tree(auto)"` |
| Support angle | `support_threshold_angle` | `45` |
| **Adhesion** | | |
| Brim | `brim_type` | `"outer_only"` |
| Brim width | `brim_width` | `"5mm"` |
| Skirt loops | `skirt_loops` | `0` |
| Elephant foot comp. | `elefant_foot_compensation` | `0.1` |
| **Retraction** | | |
| Retraction distance | `retraction_length` | `"0.8"` |
| Retraction speed | `retraction_speed` | `"30"` |
| Z hop | `z_hop` | `"0.4"` |
| **Cooling** | | |
| Min fan speed | `fan_min_speed` | `35` |
| Max fan speed | `fan_max_speed` | `100` |
| Overhang fan speed | `overhang_fan_speed` | `100` |
| **Compensation** | | |
| XY hole compensation | `xy_hole_compensation` | `0` |
| XY contour compensation | `xy_contour_compensation` | `0` |
| **Temperature** (filament overrides) | | |
| Nozzle temperature | `nozzle_temperature` | `"220"` |
| Bed temperature | `bed_temperature` | `"55"` |
| Filament flow ratio | `filament_flow_ratio` | `"0.98"` |
| Max volumetric speed | `filament_max_volumetric_speed` | `"15"` |

### CuraEngine (`engine = "cura"`)

Uses printer definition files (`.def.json`). Different setting names from OrcaSlicer.

```toml
[slicer]
engine = "cura"
version = "5.12.0"                     # current stable

[slicer.cura]
printer = "bambox_p1s"                 # definition name or ID
```

Common override keys (CuraEngine names) — for all 711 settings, see
[`cura-settings.json`](cura-settings.json):

| Setting | Key | Example |
|---------|-----|---------|
| **Quality** | | |
| Layer height | `layer_height` | `0.2` |
| First layer height | `layer_height_0` | `0.28` |
| Line width | `line_width` | `0.4` |
| Outer wall line width | `wall_line_width_0` | `0.4` |
| **Walls & surfaces** | | |
| Wall count | `wall_line_count` | `3` |
| Top layers | `top_layers` | `5` |
| Bottom layers | `bottom_layers` | `4` |
| Fill gaps between walls | `fill_outline_gaps` | `true` |
| Z seam alignment | `z_seam_type` | `"sharpest_corner"` |
| Ironing | `ironing_enabled` | `true` |
| Ironing pattern | `ironing_pattern` | `"zigzag"` |
| **Infill** | | |
| Infill density | `infill_sparse_density` | `20` |
| Infill pattern | `infill_pattern` | `"gyroid"` |
| **Speed** | | |
| Print speed | `speed_print` | `60` |
| Travel speed | `speed_travel` | `150` |
| Outer wall speed | `speed_wall_0` | `30` |
| Inner wall speed | `speed_wall_x` | `60` |
| Infill speed | `speed_infill` | `80` |
| Top/bottom speed | `speed_topbottom` | `30` |
| First layer speed | `speed_layer_0` | `20` |
| **Supports** | | |
| Enable supports | `support_enable` | `true` |
| Support structure | `support_structure` | `"tree"` |
| Support angle | `support_angle` | `45` |
| Tree support angle | `support_tree_angle` | `45` |
| **Adhesion** | | |
| Adhesion type | `adhesion_type` | `"brim"` |
| Brim width | `brim_width` | `5` |
| Skirt line count | `skirt_line_count` | `3` |
| Raft margin | `raft_margin` | `5` |
| **Retraction** | | |
| Retraction distance | `retraction_amount` | `0.8` |
| Retraction speed | `retraction_speed` | `30` |
| Z hop enabled | `retraction_hop_enabled` | `true` |
| Z hop height | `retraction_hop` | `0.4` |
| **Cooling** | | |
| Min fan speed | `cool_fan_speed_min` | `100` |
| Max fan speed | `cool_fan_speed_max` | `100` |
| Min layer time | `cool_min_layer_time` | `5` |
| **Material** | | |
| Print temperature | `material_print_temperature` | `215` |
| Bed temperature | `material_bed_temperature` | `55` |
| First layer temp | `material_print_temperature_layer_0` | `220` |
| **Compensation** | | |
| XY offset | `xy_offset` | `0` |
| Hole XY offset | `hole_xy_offset` | `0` |
| Mesh union | `meshfix_union_all` | `true` |

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
| **Quality** | | |
| Layer height | `layer_height` | `layer_height` |
| First layer height | `initial_layer_print_height` | `layer_height_0` |
| Line width | `line_width` | `line_width` |
| **Walls** | | |
| Wall count | `wall_loops` | `wall_line_count` |
| Top solid layers | `top_shell_layers` | `top_layers` |
| Bottom solid layers | `bottom_shell_layers` | `bottom_layers` |
| Detect thin walls | `detect_thin_wall` | `fill_outline_gaps` |
| Seam position | `seam_position` | `z_seam_type` |
| Ironing | `ironing_type` | `ironing_enabled` |
| **Infill** | | |
| Infill density | `sparse_infill_density` | `infill_sparse_density` |
| Infill pattern | `sparse_infill_pattern` | `infill_pattern` |
| **Speed** | | |
| Print speed | `outer_wall_speed` | `speed_print` |
| Inner wall speed | `inner_wall_speed` | `speed_wall_x` |
| Infill speed | `sparse_infill_speed` | `speed_infill` |
| Travel speed | `travel_speed` | `speed_travel` |
| Bridge speed | `bridge_speed` | `speed_wall_0_roofing` |
| First layer speed | `initial_layer_speed` | `speed_layer_0` |
| **Supports** | | |
| Enable supports | `enable_support` | `support_enable` |
| Support angle | `support_threshold_angle` | `support_angle` |
| Tree supports | `support_type` = `"tree(auto)"` | `support_structure` = `"tree"` |
| **Adhesion** | | |
| Brim | `brim_type` | `adhesion_type` |
| Brim width | `brim_width` | `brim_width` |
| Elephant foot | `elefant_foot_compensation` | *(no direct equivalent)* |
| **Retraction** | | |
| Retraction distance | `retraction_length` | `retraction_amount` |
| Retraction speed | `retraction_speed` | `retraction_speed` |
| Z hop | `z_hop` | `retraction_hop` |
| **Cooling** | | |
| Min fan speed | `fan_min_speed` | `cool_fan_speed_min` |
| Max fan speed | `fan_max_speed` | `cool_fan_speed_max` |
| **Temperature** | | |
| Nozzle temp | `nozzle_temperature` | `material_print_temperature` |
| Bed temp | `bed_temperature` | `material_bed_temperature` |
| **Compensation** | | |
| XY hole compensation | `xy_hole_compensation` | `hole_xy_offset` |
| XY contour compensation | `xy_contour_compensation` | `xy_offset` |
| **Flow** | | |
| Flow ratio | `filament_flow_ratio` | *(per-material)* |
| Max volumetric speed | `filament_max_volumetric_speed` | *(no equivalent)* |

For the complete setting lists: [`orca-settings.json`](orca-settings.json) (263 settings)
and [`cura-settings.json`](cura-settings.json) (711 settings with descriptions).

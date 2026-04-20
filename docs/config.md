# Configuration reference

estampo is configured with a single TOML file (typically `estampo.toml`). This page documents every section and field.

## Full example

```toml
name = "benchy"

[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[plate]
size = [256, 256]
padding = 5.0

[slicer]
engine = "orca"
version = "2.3.1"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"

[slicer.orca.overrides]
enable_support = 1
curr_bed_type = "Textured PEI Plate"

[[parts]]
file = "frame.stl"
copies = 1
rotate = [180, 0, 0]
filament = "Generic PETG-CF @base"

[[parts]]
file = "wheel.stl"
copies = 5
orient = "upright"
filament = "Generic PETG-CF @base"
```

## `name`

Optional project name. When set, outputs go into `estampo_output/{name}/` by default (e.g. `estampo_output/benchy/plate.3mf`). This keeps outputs from different configs separated. Explicit `-o` overrides this.

| Key    | Type     | Default | Description                              |
|--------|----------|---------|------------------------------------------|
| `name` | `string` | —       | Project name, used for output directory  |

```toml
name = "benchy"
```

## `output_dir`

Directory for build outputs, relative to the config file. CLI `--output-dir` / `-o` overrides this.

| Key          | Type     | Default            | Description              |
|--------------|----------|--------------------|--------------------------|
| `output_dir` | `string` | `"estampo_output"` | Output directory path    |

```toml
output_dir = "build/output"
```

## `[pipeline]`

Controls which stages run and in what order. Optional — defaults to the full pipeline.

| Key      | Type       | Default                                           | Description                |
|----------|------------|---------------------------------------------------|----------------------------|
| `stages` | `[string]` | `["load", "arrange", "plate", "slice"]`  | Ordered list of stages     |

Built-in stage names: `load`, `arrange`, `plate`, `slice`, `gcode-info`.

You can also add custom [command stages](#command-stages) to the pipeline — any
stage name that has a corresponding `[stage_name]` section with a `command` key.

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "gcode-info", "pack"]
```

## `[printer]` *(deprecated — removed in v0.4.0)*

> **Use [bambox](https://github.com/estampo/bambox) instead.** estampo is
> printer-agnostic — printing and packaging are handled by external tools
> configured as [command stages](#command-stages). See the
> [AI setup prompt](ai-setup-prompt.md) for examples of `bambox pack`,
> `bambox repack`, and `bambox print`.
>
> Credentials are managed by bambox: run `bambox login` to authenticate,
> credentials are saved to `~/.config/bambox/credentials.toml`.

## `[plate]`

Build plate dimensions for bin-packing.

| Key       | Type     | Default    | Description              |
|-----------|----------|------------|--------------------------|
| `size`    | `[w, h]` | `[256, 256]` | Build plate size in mm |
| `padding` | `float`  | `5.0`      | Gap between parts in mm  |

## `[slicer]`

Top-level slicer settings. Engine-specific fields go in `[slicer.orca]` or `[slicer.cura]`.

| Key            | Type       | Default      | Description                                                |
|----------------|------------|--------------|-------------------------------------------------------------|
| `engine`       | `string`   | `"orca"`     | Slicer engine: `"orca"` or `"cura"`                       |
| `version`      | `string`   | —            | Required slicer version (e.g. `"2.3.1"`, `"5.12.0"`)      |
| `bed_type`     | `string`   | —            | Bed surface (e.g. `"Textured PEI Plate"`)                  |
| `profiles_dir` | `string`   | `"profiles"` | Directory for pinned profiles (relative to config file)    |

### `[slicer.orca]`

OrcaSlicer-specific settings — profile chain and overrides.

| Key                  | Type       | Default | Description                                           |
|----------------------|------------|---------|-------------------------------------------------------|
| `printer`            | `string`   | —       | Machine profile name                                  |
| `process`            | `string`   | —       | Process profile name                                  |
| `filaments`          | `[string]` | —       | Filament profiles (auto-derived from parts if omitted)|
| `overrides`          | `{k = v}`  | —       | Process profile overrides                             |
| `machine_overrides`  | `{k = v}`  | —       | Machine profile overrides                             |
| `filament_overrides` | `{k = v}`  | —       | Filament profile overrides                            |

### `[slicer.orca.slots]`

Explicit AMS slot-to-filament mapping:

```toml
[slicer.orca.slots]
1 = "Generic PLA @base"
3 = "Generic PETG-CF @base"
5 = "Generic TPU @base"        # direct feed (bypass AMS)
```

Parts can reference slots by number (`filament = 3`) or by name (`filament = "Generic PLA @base"`).

### `[slicer.cura]`

CuraEngine-specific settings — printer definition and overrides.

| Key         | Type       | Default | Description                      |
|-------------|------------|---------|----------------------------------|
| `printer`   | `string`   | —       | CuraEngine printer definition ID |
| `filaments` | `[string]` | —       | Filament/material profile names  |
| `overrides` | `{k = v}`  | —       | Flat key-value setting overrides |

### `[slicer.orca.overrides]` / `[slicer.cura.overrides]`

Key-value pairs applied on top of the engine's default settings:

```toml
[slicer.orca.overrides]
enable_support = 1
wall_loops = 4
curr_bed_type = "Textured PEI Plate"
```

For OrcaSlicer, keys are the slicer's internal names — you can find them in any OrcaSlicer process profile JSON. Here are the most commonly used overrides:

| Key | Type | Description |
|-----|------|-------------|
| `curr_bed_type` | string | Bed surface: `"Cool Plate"`, `"Engineering Plate"`, `"High Temp Plate"`, `"Textured PEI Plate"` |
| `enable_support` | 0/1 | Enable auto-generated supports |
| `support_type` | string | `"normal(auto)"` or `"tree(auto)"` |
| `wall_loops` | int | Number of perimeter walls |
| `sparse_infill_density` | string | Infill percentage, e.g. `"15%"`, `"100%"` |
| `sparse_infill_pattern` | string | `"grid"`, `"gyroid"`, `"rectilinear"`, `"crosshatch"`, etc. |
| `brim_type` | string | `"no_brim"`, `"outer_only"`, `"inner_only"`, `"auto_brim"` |
| `layer_height` | float | Layer height in mm |
| `initial_layer_print_height` | float | First layer height in mm |
| `top_shell_layers` | int | Number of solid top layers |
| `bottom_shell_layers` | int | Number of solid bottom layers |
| `ironing_type` | string | `"no ironing"`, `"top"`, `"topmost"`, `"all solid layer"` |
| `print_sequence` | string | `"by layer"` or `"by object"` |
| `timelapse_type` | int | 0 = off, 1 = traditional |

## `[filaments]`

Optional top-level table for material aliases. Maps human-readable names to slicer profile names, decoupling parts from specific profiles:

```toml
[filaments]
structural = "Generic PETG-CF @BBL P1S"
decorative = "Generic PLA @BBL P1S"
flexible = "Generic TPU @base"

[[parts]]
file = "body.stl"
filament = "structural"

[[parts]]
file = "cap.stl"
filament = "decorative"
```

Aliases are resolved at config load time before slot assignment. Parts can still use direct profile names or integer slot indices.

## `[[parts]]`

Each `[[parts]]` entry defines a mesh to include on the build plate. At least one is required.

| Key        | Type          | Default  | Description                                          |
|------------|---------------|----------|------------------------------------------------------|
| `file`     | `string`      | —        | Path to mesh file (STL, 3MF, or STEP)               |
| `copies`   | `int`         | `1`      | Number of copies                                     |
| `orient`   | `string`      | `"flat"` | `"flat"`, `"upright"`, or `"side"`                   |
| `rotate`   | `[x, y, z]`   | —        | Custom rotation in degrees (overrides `orient`)      |
| `filament` | `int\|string` | `1`      | Material alias, profile name, or slot index          |
| `scale`    | `float`       | `1.0`    | Uniform scale factor                                 |
| `object`   | `string`      | —        | Select a named object from a multi-object 3MF        |
| `sequence` | `int`         | `1`      | Print order for sequential printing                  |

### Per-object filament overrides

For multi-object 3MF files, assign different filaments to individual objects:

```toml
[[parts]]
file = "widget.3mf"
filament = "Generic PETG-CF @base"       # default for unlisted objects

[parts.filaments]
inlay = "Bambu PLA Basic @BBL X1C"       # override for object named "inlay"
```

Objects from the same file are grouped as a single unit for bin packing.

### Sequential printing

For workflows that require printing one layer/object before another (e.g. bottom inlay):

```toml
[[parts]]
file = "widget.3mf"
object = "inlay"
filament = "Generic PLA @base"
sequence = 1

[[parts]]
file = "widget.3mf"
object = "body"
filament = "Generic PETG-CF @base"
sequence = 2
```

Both objects come from the same 3MF, so estampo guarantees identical bed positioning.

## Command stages

Command stages run external CLI tools as pipeline stages. Any stage name in
`[pipeline].stages` that has a matching TOML section with a `command` key is
treated as a command stage.

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[pack]
command = "bambox repack {sliced_3mf}"
output = "{sliced_3mf}"
```

| Key       | Type     | Default | Description                                           |
|-----------|----------|---------|-------------------------------------------------------|
| `command` | `string` | —       | Shell command with `{variable}` placeholders          |
| `output`  | `string` | —       | Output path (makes it available to downstream stages) |
| `docker`  | `bool`   | `false` | Run inside the slicer Docker container                |
| `image`   | `string` | —       | Docker image override (default: slicer image)         |

When `docker = true`, the command runs inside a Docker container with the
output directory mounted at `/work/output`. This is useful for tools bundled
in the slicer Docker image (like `bambox`).

### Template variables

Command strings use `{variable}` placeholders substituted at runtime.
estampo will error on unknown variable names.

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
| `{sliced_3mf}` | `slice` | Sliced output file (`.gcode.3mf` or `.gcode`) |
| `{sliced_dir}` | `slice` | Slicer output directory |
| `{cura_settings}` | `slice` | CuraEngine settings JSON path (CuraEngine only) |

### Example: Bambu Lab pack stage

**OrcaSlicer** (patches existing `.gcode.3mf` for Bambu Connect compatibility):
```toml
[pack]
command = "bambox repack {sliced_3mf}"
output = "{sliced_3mf}"
```

**CuraEngine** (creates `.gcode.3mf` from plain G-code):
```toml
[pack]
command = "bambox pack {sliced_dir}/plate.gcode -o {output_dir}/plate.gcode.3mf"
output = "{output_dir}/plate.gcode.3mf"
```

## Common override recipes

Choose overrides based on your print goals:

**Strong functional part (PETG):**
```toml
[slicer.orca.overrides]
wall_loops = 5
sparse_infill_density = "40%"
sparse_infill_pattern = "gyroid"
top_shell_layers = 6
bottom_shell_layers = 6
```

**Fast draft:**
```toml
[slicer.orca.overrides]
sparse_infill_density = "10%"
wall_loops = 2
enable_support = 0
```

**Smooth top surface:**
```toml
[slicer.orca.overrides]
ironing_type = "topmost"
top_shell_layers = 6
```

**Dimensional accuracy (engineering parts):**
```toml
[slicer.orca.overrides]
xy_hole_compensation = 0.1
xy_contour_compensation = -0.05
outer_wall_speed = 30
```

**Tree supports for complex overhangs:**
```toml
[slicer.orca.overrides]
enable_support = 1
support_type = "tree(auto)"
support_threshold_angle = 45
```

## Important rules

- **Do not invent setting names.** Only use keys from the override tables above
  or from the JSON setting files. estampo validates overrides and will reject
  unknown keys with "did you mean?" suggestions.
- **Do not force slicer settings** that conflict with the printer's machine
  profile (e.g. `use_relative_e_distances`). Let the profile chain decide.
- **Values use their natural TOML type** — `enable_support = 1` (int),
  `layer_height = 0.2` (float), `curr_bed_type = "Textured PEI Plate"`
  (string). estampo handles conversion to the slicer CLI format.
- **Pin the slicer version** in `[slicer].version` for reproducible builds.
- **OrcaSlicer and CuraEngine use different setting names** for the same
  concepts. See the [AI setup prompt](ai-setup-prompt.md) for a mapping table.

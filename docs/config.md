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

Valid stage names: `load`, `arrange`, `plate`, `slice`, `gcode-info`, `print`.

If your workflow doesn't need printing, omit `print`:

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice"]
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
```

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

| Key         | Type      | Default | Description                      |
|-------------|-----------|---------|----------------------------------|
| `printer`   | `string`  | —       | CuraEngine printer definition ID |
| `overrides` | `{k = v}` | —      | Flat key-value setting overrides |

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

Both objects come from the same 3MF, so estampo guarantees identical bed positioning. Run each sequence separately:

```bash
estampo run estampo.toml --only print   # after slicing sequence 1
```

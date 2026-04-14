# CuraEngine + Bambu P1S

CuraEngine slicing with a Bambu Lab P1S printer definition from bambox,
packed into a `.gcode.3mf` ready for the printer.

## Prerequisites

- Docker running (CuraEngine image pulled automatically)
- bambox installed (`pipx install bambox`)

## Setup — importing the printer definition

The Bambu P1S printer definition is provided by the bambox package. To set up
a new project from scratch, import the definitions with `estampo profiles add`:

```sh
# Find where bambox installed its definitions
bambox cura-defs --path

# Import the P1S AMS definition and its extruder files
estampo profiles add "$(bambox cura-defs --path)/bambox_p1s_ams.def.json"
estampo profiles add "$(bambox cura-defs --path)/bambox_p1s_ams_extruder_0.def.json"
estampo profiles add "$(bambox cura-defs --path)/bambox_p1s_ams_extruder_1.def.json"
estampo profiles add "$(bambox cura-defs --path)/bambox_p1s_ams_extruder_2.def.json"
estampo profiles add "$(bambox cura-defs --path)/bambox_p1s_ams_extruder_3.def.json"
```

This example has the definitions pre-committed in `profiles/cura/definitions/`
so it works without running the above steps.

## Run

```sh
estampo run examples/cura-p1s/estampo.toml
```

Output: `estampo_output/plate.gcode.3mf` — ready to send to the printer.

## Printing

Send the output to your printer with bambox:

```sh
bambox print estampo_output/plate.gcode.3mf
```

If you have multiple printers in your bambox credentials, pass the name:

```sh
bambox print estampo_output/plate.gcode.3mf --printer workshop
```

To automate this as a pipeline stage, add a `[print]` section to
`estampo.toml`:

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack", "print"]

[print]
command = "bambox print {output_dir}/plate.gcode.3mf"
```

## What it demonstrates

- CuraEngine with a third-party printer definition (from bambox)
- Importing printer definitions via `estampo profiles add`
- `filaments` — single-filament PLA on AMS slot 1
- `[slicer.cura.overrides]` — infill, walls, speed, layer height
- `[pack]` command stage — `bambox pack` converts CuraEngine G-code to Bambu `.gcode.3mf`
- Pinned profiles committed to the repo for reproducibility

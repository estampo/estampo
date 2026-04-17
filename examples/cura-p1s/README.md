# CuraEngine + Bambu P1S

CuraEngine slicing with a Bambu Lab P1S printer definition from cura-p1s,
packed into a `.gcode.3mf` ready for the printer.

## Prerequisites

- Docker running (CuraEngine image pulled automatically)
- cura-p1s installed (`pipx install cura-p1s`) — resolves G-code template variables
- bambox installed (`pipx install bambox`) — packs G-code into `.gcode.3mf`

## Setup — importing the printer definition

The Bambu P1S printer definition is provided by the cura-p1s package. To set
up a new project from scratch, import the definitions with `estampo profiles add`:

```sh
# Find where cura-p1s installed its definitions
cura-p1s defs --path

# Import the P1S definition and its extruder file
estampo profiles add "$(cura-p1s defs --path)/bambox_p1s.def.json"
estampo profiles add "$(cura-p1s defs --path)/bambox_p1s_extruder_0.def.json"
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
stages = ["load", "arrange", "plate", "slice", "resolve_templates", "pack", "print"]

[print]
command = "bambox print {output_dir}/plate.gcode.3mf"
```

## What it demonstrates

- CuraEngine with a native Bambu P1S definition (from cura-p1s)
- Importing printer definitions via `estampo profiles add`
- Single-filament PLA printing
- `[slicer.cura.overrides]` — infill, walls, speed, layer height
- `[resolve_templates]` command stage — `cura-p1s resolve` resolves G-code template variables
- `[pack]` command stage — `bambox pack` converts CuraEngine G-code to Bambu `.gcode.3mf`
- Pinned profiles committed to the repo for reproducibility

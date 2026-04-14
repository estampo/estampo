# Quickstart

One STL part sliced with OrcaSlicer and repacked for a Bambu Lab P1S.

## Prerequisites

- Docker running (OrcaSlicer image pulled automatically)
- bambox installed (`pipx install bambox`)

## Run

```sh
estampo run examples/quickstart/estampo.toml
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

Then `estampo run` will slice, pack, and print in one command.

## What it demonstrates

- Minimal `estampo.toml` structure
- OrcaSlicer engine with a printer + process profile
- `[pack]` command stage — `bambox repack` converts OrcaSlicer output to Bambu-compatible `.gcode.3mf`
- Pipeline stages: load → arrange → plate → slice → pack

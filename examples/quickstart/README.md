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

## What it demonstrates

- Minimal `estampo.toml` structure
- OrcaSlicer engine with a printer + process profile
- `[pack]` command stage — `bambox repack` converts OrcaSlicer output to Bambu-compatible `.gcode.3mf`
- Pipeline stages: load → arrange → plate → slice → pack

# Multi-Filament

Two-filament print using OrcaSlicer with AMS slot assignment per part.

## Run

```sh
estampo run examples/multi-filament/estampo.toml
```

## Printing

Send the output to your printer with bambox:

```sh
bambox print estampo_output/plate.gcode.3mf --serial YOUR_PRINTER_SERIAL
```

Find your printer's serial number with `bambox discover`.

To automate this as a pipeline stage, add a `[print]` section to
`estampo.toml`:

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack", "print"]

[print]
command = "bambox print {output_dir}/plate.gcode.3mf --serial YOUR_PRINTER_SERIAL"
```

## What it demonstrates

- `filaments` list — declares available AMS slots (PLA in slot 1, PETG in slot 2)
- Per-part `filament` — assigns each part to an AMS slot by index
- Mixed file formats — STL and STEP on the same multi-material plate
- `bed_type` — selects bed surface for temperature/adhesion settings
- `[slicer.orca.overrides]` — process overrides (infill, shells, seam position)
- `[slicer.orca.filament_overrides]` — override applied to all filament profiles (initial layer temp)
- `[pack]` command stage — `bambox repack` for Bambu-compatible output

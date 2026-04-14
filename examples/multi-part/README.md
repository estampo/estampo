# Multi-Part

Multiple parts arranged on a single plate with different orientations, scaling, and slicer overrides.

## Run

```sh
estampo run examples/multi-part/estampo.toml
```

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

- `copies` — three identical cubes from one STL
- STEP file support — `box_20x20x10.step` loaded alongside STLs
- `orient` — `flat`, `upright`, and `side` orientations
- `rotate` — explicit rotation in degrees `[rx, ry, rz]`
- `scale` — uniform scale factor on a part
- `padding` — spacing between parts during arrangement
- `[slicer.orca.overrides]` — infill, walls, supports, and ironing without editing slicer profiles
- `[pack]` command stage — `bambox repack` for Bambu-compatible output

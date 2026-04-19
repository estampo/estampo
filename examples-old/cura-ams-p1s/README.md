# CuraEngine multi-filament e2e example — P1S + AMS

Two-part, two-filament print sliced by CuraEngine and packed by bambox.
Used for release testing: compare the CuraEngine output against a
BambuStudio reference slice of the same models.

## Models

| File | Slot | Filament |
|------|------|----------|
| `tests/fixtures/cube_10mm.stl` | AMS 1 | PLA |
| `tests/fixtures/cylinder_5x20mm.stl` | AMS 2 | PETG |

## Prerequisites

- estampo installed (`pipx install estampo`)
- Docker running (CuraEngine image pulled automatically)
- bambox installed (`pipx install bambox` or `cargo install bambox`)

The CuraEngine printer definition (`bambox_p1s_ams`) is bundled in
`profiles/cura/definitions/` so estampo can find it without bambox
installed as a Python package.

## Running the estampo slice

```sh
estampo run examples/cura-ams-p1s/estampo.toml
```

Output: `examples/cura-ams-p1s/output/plate.gcode.3mf`

## Creating the BambuStudio reference slice

Do this once when setting up the comparison baseline, or when the models change.

1. Open BambuStudio and start a new project for **Bambu Lab P1S 0.4 nozzle**
2. Import both models:
   - `tests/fixtures/cube_10mm.stl` → assign to **AMS slot 1**, filament **Generic PLA**
   - `tests/fixtures/cylinder_5x20mm.stl` → assign to **AMS slot 2**, filament **Generic PETG**
3. Set process: **0.20mm Standard @BBL X1C** (or equivalent)
4. Bed: **Textured PEI Plate**
5. Arrange models on the plate
6. Slice and export: **File → Export → Export plate sliced file**
7. Save as `examples/cura-ams-p1s/reference/bambu-studio.gcode.3mf`

## Comparing the outputs

The two `.gcode.3mf` files will not have identical G-code (different slicers),
but the structural elements should match.

### Automated checks (run after `estampo run`)

```sh
# 1. Output file exists and is non-trivial
test -s examples/cura-ams-p1s/output/plate.gcode.3mf

# 2. Contains Bambu tool change sequences
unzip -p examples/cura-ams-p1s/output/plate.gcode.3mf Metadata/plate_1.gcode \
  | grep -c "M620"

# 3. AMS slot assignments in slice_info
unzip -p examples/cura-ams-p1s/output/plate.gcode.3mf Metadata/slice_info.config \
  | grep filament_id
```

### Manual comparison against BambuStudio reference

| Property | How to check |
|----------|-------------|
| Tool change count | `grep -c "M620" <(unzip -p <file> Metadata/plate_1.gcode)` |
| AMS slot IDs | `unzip -p <file> Metadata/slice_info.config \| grep filament` |
| Print time estimate | `unzip -p <file> Metadata/slice_info.config \| grep time` |
| Filament usage (mm) | `unzip -p <file> Metadata/slice_info.config \| grep used_m` |
| BAMBOX headers present | `unzip -p output/plate.gcode.3mf Metadata/plate_1.gcode \| head -20` |

Acceptable tolerances: print time ±20%, filament usage ±15%.
Tool change count should be identical (both use 2 filaments on separate objects).

## What this tests

- `slicer.py` multi-mesh extraction and group centering
- `cura.py` `slice_stl_multi`: per-extruder `-g -eN` groups with per-slot settings
- BAMBOX header emission (`BAMBOX_PRINTER`, `BAMBOX_ASSEMBLE`, `BAMBOX_FILAMENT_SLOT`)
- `bambox pack`: header parsing, T→M620/M621 rewriting, `.gcode.3mf` assembly
- `commands.py` command stage integration (`{sliced_dir}` variable substitution)

## Notes

- `plate.gcode` in `{sliced_dir}` is the fixed output name for CuraEngine
  slices (produced by `slice_stl_multi`).
- The `bambox_p1s_ams` printer definition must be available to CuraEngine via
  the bambox package or a local `profiles/` directory.
- To send to the printer, add a `[print]` command stage:
  ```toml
  [print]
  command = "bambox print {output_dir}/plate.gcode.3mf --serial YOUR_SERIAL"
  ```

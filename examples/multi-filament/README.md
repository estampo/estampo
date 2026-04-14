# Multi-Filament

Two-filament print using OrcaSlicer with AMS slot assignment per part.

## Run

```sh
estampo run examples/multi-filament/estampo.toml
```

## What it demonstrates

- `filaments` list — declares available AMS slots (PLA in slot 1, PETG in slot 2)
- Per-part `filament` — assigns each part to an AMS slot by index
- Mixed file formats — STL and STEP on the same multi-material plate
- `bed_type` — selects bed surface for temperature/adhesion settings

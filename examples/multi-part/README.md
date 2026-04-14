# Multi-Part

Multiple parts arranged on a single plate with different orientations, scaling, and slicer overrides.

## Run

```sh
estampo run examples/multi-part/estampo.toml
```

## What it demonstrates

- `copies` — three identical cubes from one STL
- `orient` — `flat`, `upright`, and `side` orientations
- `rotate` — explicit rotation in degrees `[rx, ry, rz]`
- `scale` — uniform scale factor on a part
- `padding` — spacing between parts during arrangement
- `[slicer.orca.overrides]` — gyroid infill at 25% without editing slicer profiles

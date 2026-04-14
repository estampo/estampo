# CuraEngine

Single-filament CuraEngine example targeting an Ultimaker 2.

## Run

```sh
estampo run examples/cura/estampo.toml
```

Output is standard G-code — no post-processing or repacking needed.

## What it demonstrates

- CuraEngine as an alternative slicer engine
- Ultimaker 2 printer definition (bundled with estampo)
- Pinned slicer version for reproducibility
- Default pipeline stages: load → arrange → plate → slice

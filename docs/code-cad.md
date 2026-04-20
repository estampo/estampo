# Code-CAD workflow

estampo works with any tool that produces STL, STEP, or 3MF files. This guide shows how to integrate it with code-CAD tools like OpenSCAD, build123d, and CadQuery for a fully reproducible, version-controlled 3D printing workflow.

## The idea

Instead of manually importing files into a slicer GUI and configuring settings by hand, you define everything in a `estampo.toml` alongside your CAD source. The entire print job — models, slicer settings, orientation, plate layout — is captured in text files you can commit to git.

```
my-project/
  widget.scad          # CAD source (OpenSCAD, build123d, etc.)
  widget.stl           # generated mesh
  estampo.toml        # print config
  profiles/            # pinned slicer profiles (optional)
  .gitignore           # ignore estampo_output/
```

## OpenSCAD

Generate STL from the command line, then slice with estampo:

```bash
# Regenerate mesh from source
openscad -o widget.stl widget.scad

# Slice and print
estampo run
```

`estampo.toml`:
```toml
name = "widget"

[slicer]
engine = "orca"
version = "2.3.1"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"

[slicer.orca.overrides]
enable_support = 1

[[parts]]
file = "widget.stl"
copies = 2
orient = "flat"
filament = "Generic PLA @base"
```

For parametric designs, pass variables on the command line:

```bash
openscad -o bracket_m4.stl -D 'bolt_dia=4' bracket.scad
openscad -o bracket_m5.stl -D 'bolt_dia=5' bracket.scad
```

## build123d (Python)

build123d outputs STEP files directly, which estampo loads via its built-in build123d integration:

```python
# widget.py
from build123d import *

with BuildPart() as widget:
    Box(50, 30, 10)
    # ...

export_step(widget.part, "widget.step")
```

```bash
python widget.py
estampo run
```

`estampo.toml`:
```toml
name = "widget"

[slicer]
engine = "orca"
version = "2.3.1"

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"

[[parts]]
file = "widget.step"
rotate = [180, 0, 0]
filament = "Generic PETG-CF @base"
```

STEP files are converted to mesh via build123d at load time. The tessellation quality matches build123d's defaults.

## CadQuery

CadQuery can export STL or STEP:

```python
import cadquery as cq

result = cq.Workplane("XY").box(50, 30, 10)
cq.exporters.export(result, "widget.step")
```

Then use the same `estampo.toml` approach as build123d above.

## Reproducible builds

Three things make an estampo build fully reproducible:

1. **Pin the OrcaSlicer version** — `version = "2.3.1"` in `[slicer]` ensures Docker uses the exact same slicer binary everywhere.

2. **Pin slicer profiles** — `estampo profiles pin` copies the referenced profiles into a `profiles/` directory. Commit this to git so builds don't depend on locally installed profiles.

3. **Use Docker for slicing** — Docker is the default when available. It isolates the slicer from the host system, ensuring identical output across macOS, Linux, and CI.

```bash
estampo profiles pin    # copies profiles into ./profiles/
git add profiles/        # commit pinned profiles
```

With all three, anyone can clone your repo and produce identical G-code with `estampo run`.

## Git workflow

Commit:
- `*.scad`, `*.py` — CAD source files
- `*.stl`, `*.step` — generated meshes (or regenerate in CI)
- `estampo.toml` — print configuration
- `profiles/` — pinned slicer profiles

Gitignore:
```
estampo_output/
```

## CI integration

Use the estampo GitHub Action to slice on every PR:

```yaml
- uses: estampo/estampo/action@v0
  with:
    config: estampo.toml
    orca-version: "2.3.1"
```

This slices the model, posts print time and filament usage as a PR comment, and uploads the G-code as an artifact. See [action/README.md](../action/README.md) for all options.

## Partial runs

During iteration, you often want to re-run just part of the pipeline:

```bash
estampo run --until plate     # stop after arrangement (check layout)
estampo run --only slice      # re-slice without re-arranging
```

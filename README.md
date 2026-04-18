<p align="center">
  <img src="https://raw.githubusercontent.com/estampo/estampo/main/docs/images/estampo-logo-color-256.png" alt="estampo logo" width="128">
</p>

# estampo

[![PyPI version](https://img.shields.io/pypi/v/estampo)](https://pypi.org/project/estampo/)
[![CI](https://github.com/estampo/estampo/actions/workflows/ci.yml/badge.svg)](https://github.com/estampo/estampo/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/pypi/pyversions/estampo)](https://pypi.org/project/estampo/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![codecov](https://codecov.io/gh/estampo/estampo/branch/main/graph/badge.svg)](https://codecov.io/gh/estampo/estampo)

**The build system for reproducible 3D prints.**

3D printing workflows are trapped in GUIs. Slicer settings get lost between
sessions, printer configs drift across machines, and there's no way to version,
diff, or review a print job. None of this is accessible to automation — or to
AI assistants.

estampo takes a different approach: define parts, slicer settings, and pipeline
stages in a single TOML file — text that's git-friendly, diffable, and
committable alongside your CAD files. Because the entire workflow is text,
it's naturally accessible to AI coding assistants, CI systems, and code review.
Same repo, same config → same G-code, locally or [in CI](#cicd-example).

> **Warning:** estampo is in active early development. We are moving fast and breaking things — config format, CLI flags, and Python APIs may change between minor versions without deprecation. Pin your version if stability matters to you.

> **Note:** This project was previously called **fabprint**. If you have an existing install,
> run `pip install estampo` to upgrade — config files and credentials are migrated automatically.

Works with STL, STEP, and 3MF files, and pairs naturally with code-CAD tools like
[build123d](https://github.com/gumyr/build123d), [OpenSCAD](https://openscad.org),
and [cadquery](https://github.com/cadquery/cadquery).

```toml
# estampo.toml — a multi-part print with slicer overrides

[[parts]]
file = "enclosure_base.step"
orient = "flat"
filament = 1                    # AMS slot 1: PETG-CF

[[parts]]
file = "enclosure_lid.step"
orient = "upright"
filament = 1

[[parts]]
file = "button_cap.stl"
copies = 4
filament = 2                    # AMS slot 2: PLA

[slicer]
engine = "orca"
version = "2.3.1"               # pinned for reproducibility

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"
filaments = ["Generic PETG-CF @base", "Generic PLA @base"]

[slicer.orca.overrides]
sparse_infill_density = "25%"
enable_support = 1
brim_type = "auto_brim"

[pipeline]
stages = ["load", "arrange", "plate", "slice", "gcode-info", "pack"]

[pack]
command = "bambox repack {sliced_3mf}"
output = "{sliced_3mf}"
```

```bash
estampo run        # arrange → slice → pack, one command
```

```
  Output → estampo_output/enclosure
✔ Loaded 3 parts
✔ Arranged 3 parts onto plate  (256×256mm)
✔ Plate exported → plate.3mf
✔ Preview exported → plate_preview.3mf
✔ Sliced with OrcaSlicer 2.3.1 in 48s
✔ Print time: 3h 42m, 24.6g filament
✔ Packed → plate_sliced.gcode.3mf
```

## What estampo does

![estampo demo](https://raw.githubusercontent.com/estampo/estampo/main/docs/recordings/demo.gif)

1. **Define** parts + settings in `estampo.toml`
2. **Arrange** — bin-packs models onto the build plate
3. **Slice** — using a pinned slicer version (via Docker) for identical G-code across machines
4. **Post-process** — run command stages (pack for Bambu, template resolution, etc.)

Everything is declared in a single TOML file. Lock the slicer version, pin the
profiles, and the output is reproducible on any machine or in CI.

![estampo pipeline](https://raw.githubusercontent.com/estampo/estampo/main/docs/images/pipeline.png)

### Why not just use OrcaSlicer CLI?

OrcaSlicer CLI is great for slicing a prepared plate. estampo builds a reproducible pipeline around it:

- **Arrangement** — bin-packs multiple STLs onto the build plate (OrcaSlicer CLI has no arrange step)
- **Multi-part filament mapping** — per-part filament slot assignment and paint color preservation, injected into the 3MF metadata
- **Reproducible builds** — pin slicer profiles into your repo + lock OrcaSlicer version in Docker = identical gcode on any machine
- **Partial execution** — `--until plate` to inspect layout, `--only slice` to re-slice, `--dry-run` to test everything
- **Command stages** — run external tools (e.g. `bambox pack`) as pipeline stages with variable substitution
- **Headless Docker slicing** — no GUI, no display server, works in CI, uses a specific OrcaSlicer version

### Why not just use CuraEngine CLI?

CuraEngine CLI (`CuraEngine slice -j definition.json -s KEY=VALUE -l model.stl -o output.gcode`) is powerful but requires assembling the full invocation yourself:

| What you need to do | CuraEngine CLI | estampo |
|---------------------|---------------|---------|
| Load printer definition | `-j printer.def.json` + `-d` search paths for inheritance | `printer = "Ultimaker 2"` in TOML |
| Set material/quality | Chain of `-j` files or `-s` overrides for every setting | `[slicer.cura.overrides]` in TOML |
| Arrange multiple parts | Not supported — manual positioning | Automatic bin-packing |
| Multi-extruder mapping | `-g -e0 -l a.stl -g -e1 -l b.stl` per mesh group | `filament = 1` per part |
| Reproducible builds | Track all definition JSONs yourself | `version = "5.12.0"` + Docker |
| Version control | Shell scripts + scattered JSON definitions | Single TOML file — git-diffable and reviewable |
| Run in CI | Install CuraEngine + definitions manually | `uses: estampo/estampo/action@v1` |
| Pack for Bambu printers | Separate manual step | `[pack]` command stage |

With CuraEngine CLI, your build config ends up spread across shell scripts, `-s` flag lists, and JSON definition files — hard to diff, review, or commit as a coherent unit. estampo replaces all of that with a single declarative TOML file: git-friendly, diffable, and accessible to AI assistants and code review.

### Works with AI assistants

GUI-based slicers require point-and-click interaction that AI assistants cannot
drive. estampo's text-based config is different — an AI assistant can read your
TOML, understand your print setup, suggest overrides, create CI workflows, and
validate the result, all without leaving the conversation.

We provide a ready-to-paste [AI setup prompt](docs/ai-setup-prompt.md) that
gives any AI assistant (Claude, ChatGPT, Copilot) enough context to add estampo
to a project from scratch — it scans the repo for model files, asks you a few
questions, and generates the config. This isn't an AI feature bolted on — it's
an architectural property of using text instead of a GUI.

## Best fit

estampo is best suited to:

- Hardware teams keeping CAD and manufacturing inputs in Git
- Engineers who want deterministic slicing in CI
- Teams using AI coding assistants to manage their build and print workflows
- Makers who want a declarative print workflow instead of slicer click-ops

If you mostly want interactive print setup in a GUI, use OrcaSlicer or Cura directly.

## Status

### Stable

- Declarative print config in `estampo.toml`
- Multi-part arrangement
- Docker-based slicing with pinned slicer versions (OrcaSlicer, CuraEngine)
- Slicing for any printer supported by OrcaSlicer or CuraEngine
- Profile pinning into your repository
- CI slicing and artifact generation
- Network print initiation via Bambu Cloud



### Experimental

- Bambu LAN printing
- Moonraker printing

## Quick start

**Prerequisites:** Python 3.11+ and [Docker](https://docs.docker.com/get-docker/). Docker is
central to estampo — it runs the slicer (OrcaSlicer or CuraEngine) in a container with a pinned
version so every machine produces identical G-code. A locally installed slicer can be used as a
fallback but is not recommended.

```bash
pip install estampo
# or, to install as an isolated CLI tool:
pipx install estampo
```

Generate a config with the interactive wizard, or dump a commented template:

```bash
estampo init                       # interactive wizard — discovers profiles and CAD files, creates TOML
estampo init --template            # dump a commented template
```

Or create `estampo.toml` by hand (see [full config reference](https://github.com/estampo/estampo/blob/main/docs/config.md)):

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[plate]
size = [256, 256]       # build plate dimensions in mm
padding = 5.0

[slicer]
engine = "orca"
version = "2.3.1"       # pin OrcaSlicer version for reproducibility

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"

[slicer.orca.overrides]  # simple way to define print settings without editing JSON
sparse_infill_density = "30%"       # stronger infill
wall_loops = 3                       # extra wall strength
enable_support = 1
brim_type = "auto_brim"             # help adhesion
curr_bed_type = "Textured PEI Plate"

[[parts]]               # define multiple parts using STEP, STL or 3MF inputs
file = "frame.step"
rotate = [180, 0, 0]    # flip so mounting plate faces down
filament = "Generic PETG-CF @base"

[[parts]]
file = "wheel.stl"
copies = 5
orient = "upright"
filament = "Generic PETG-CF @base"
```

Run it (see [full CLI reference](https://github.com/estampo/estampo/blob/main/docs/cli.md)):

```bash
estampo run                   # arrange, slice and send to printer
estampo run --until slice     # stop after slicing
estampo run --dry-run         # full pipeline without sending to printer
```

The arrangement (`plate`) stage generates a `plate_preview.3mf` — open it in any 3MF viewer to check placement:

![plate preview](https://raw.githubusercontent.com/estampo/estampo/main/docs/images/plate_preview.png)

## Reproducibility

Pin profiles into your repo so builds are identical across machines:

```bash
estampo profiles pin          # copies slicer profiles into ./profiles/
git add profiles/              # commit to lock them
```

Combined with a pinned `version` in `[slicer]` (which locks the Docker image), the same config always produces the same gcode.

### CI/CD example

Automate slicing in GitHub Actions — push a commit, get G-code as a build artifact with print metrics on your PR:

```yaml
# .github/workflows/slice.yml
name: Slice
on: [push, pull_request]
jobs:
  slice:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: estampo/estampo/action@v1
```

The action slices your model, uploads G-code as an artifact, and posts print time / filament stats as a PR comment. See [`action/README.md`](action/README.md) for all options.

## CLI overview

```bash
estampo init                        # interactive config wizard
estampo init --template             # dump commented TOML template
estampo init --workflow             # wizard + GitHub Actions workflow
estampo validate                    # check config for issues
estampo run                         # full pipeline
estampo run --until plate           # stop after plating
estampo run --only slice            # run just one stage
estampo run --dry-run               # everything except sending to printer
estampo profiles list               # list available slicer profiles
estampo profiles pin                # pin profiles for reproducible builds
```

## Printing

estampo is printer-agnostic — it produces sliced output but does not send files to printers. For Bambu Lab printers, use [bambox](https://github.com/estampo/bambox) as a command stage to pack and print. Run `bambox login` to set up credentials (`~/.config/bambox/credentials.toml`). See the [AI setup prompt](docs/ai-setup-prompt.md) for full examples.

## Documentation

- [CLI reference](https://github.com/estampo/estampo/blob/main/docs/cli.md) — all commands, flags, and pipeline stages
- [Config reference](https://github.com/estampo/estampo/blob/main/docs/config.md) — complete TOML format
- [Developing](https://github.com/estampo/estampo/blob/main/docs/developing.md) — setup, testing, architecture

## Development

estampo's codebase is authored by [Claude](https://claude.ai), Anthropic's AI
assistant, under the direction and review of a human maintainer. Architecture
decisions, priorities, and acceptance criteria are set by the maintainer; Claude
writes the code, tests, documentation, and CI workflows. Every commit is
reviewed before merge.

## License

Apache 2.0

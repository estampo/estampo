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

You can version your CAD. You can't version your slicer setup — estampo fixes that.

Define parts, slicer settings, and the full pipeline in one TOML file, commit it, and run it anywhere. Same repo, same config → same G-code, locally or [in CI](#cicd-example).

estampo is a thin orchestration layer around slicer CLIs — it wraps OrcaSlicer or CuraEngine (Docker-pinned, CI-friendly, diffable) and doesn't replace them. See [the comparison table](#why-not-just-use-the-slicer-cli-directly) for what estampo adds over the raw CLIs.

**estampo is for you if** you use code-CAD (build123d, OpenSCAD, cadquery), want to slice from CI, diff slicer settings in git, or need identical G-code across machines.

**It's not for you if** you want a GUI slicer with preview, one-click printing, or a tool that manages a single local printer from the couch — use [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer) or your vendor's app for that. estampo wraps those tools; it doesn't replace them.

> **Safety:** estampo generates G-code from your configuration but does not verify that settings are safe for your specific printer. Incorrect temperatures, speeds, or missing supports can damage your printer or create a fire hazard. Always review sliced output before sending to a printer. `estampo validate` checks config structure and setting names — it does not check print safety. **Use at your own risk.**

Works with STL, STEP, and 3MF files, and pairs naturally with code-CAD tools like
[build123d](https://github.com/gumyr/build123d), [OpenSCAD](https://openscad.org),
and [cadquery](https://github.com/cadquery/cadquery) — and with AI coding assistants, since the whole workflow is plain text.

**Requires [Docker](https://docs.docker.com/get-docker/) and Python 3.11+.** estampo runs the slicer (OrcaSlicer or CuraEngine) in a pinned Docker image so every machine produces identical G-code. A local slicer install works as a fallback but is not recommended.

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
4. **Post-process** — run command stages (pack for Bambu via bambox, upload to Klipper via Moonraker, template resolution, etc.). Works with any printer that takes G-code; vendor specifics live in command stages, not in estampo.

Everything is declared in a single TOML file. Lock the slicer version, pin the
profiles, and the output is reproducible on any machine or in CI.

![estampo pipeline](https://raw.githubusercontent.com/estampo/estampo/main/docs/images/pipeline.svg)

### Why not just use the slicer CLI directly?

OrcaSlicer and CuraEngine both ship excellent CLIs, and estampo is built on
top of them — it shells out to one or the other for the actual slicing work.
The goal isn't to replace either tool; it's to give you a reproducible
pipeline around them (arrangement, profile pinning, CI, post-processing)
without asking you to assemble the full invocation by hand each time.

| What you need to do | OrcaSlicer CLI | CuraEngine CLI | estampo |
|---------------------|----------------|----------------|---------|
| Load printer/process profiles | `--load-settings` for each JSON in the chain | `-j printer.def.json` + `-d` search paths for inheritance | `printer = "..."` / `process = "..."` in TOML |
| Set material / quality overrides | Edit JSON or pass inline overrides | Chain of `-j` files or `-s KEY=VALUE` per setting | `[slicer.orca.overrides]` / `[slicer.cura.overrides]` |
| Arrange multiple parts | Not supported — prepare the plate yourself | Not supported — manual positioning | Automatic bin-packing |
| Multi-part filament / extruder mapping | Prebuilt 3MF with per-object slot metadata | `-g -e0 -l a.stl -g -e1 -l b.stl` per mesh group | `filament = 1` per part |
| Reproducible builds | Track slicer binary + profiles yourself | Track all definition JSONs yourself | `version = "..."` in TOML + pinned Docker image |
| Partial re-runs | Re-slice the whole thing | Re-slice the whole thing | `--until plate`, `--only slice` |
| Version control | Shell scripts + scattered JSON overrides | Shell scripts + `-s` lists + JSON definitions | Single TOML file — git-diffable, reviewable |
| Run in CI | Install OrcaSlicer manually (needs display on some builds) | Install CuraEngine + definitions manually | `uses: estampo/estampo/action@v1` |
| Post-process (e.g. pack for Bambu) | Separate manual step | Separate manual step | `[pack]` command stage with variable substitution |
| Headless slicing | GUI builds can require an X server | CLI-only already | Docker container pinned to a specific slicer version |

With the slicer CLI alone, your build config ends up spread across shell
scripts, `-s` flag lists, and JSON definition files — hard to diff, review,
or commit as a coherent unit. estampo replaces that orchestration layer
with a single declarative TOML file; the slicer itself does all the actual
work.

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

- Declarative print config in `estampo.toml`
- Multi-part arrangement
- Docker-based slicing with pinned slicer versions (OrcaSlicer, CuraEngine)
- Slicing for any printer supported by OrcaSlicer or CuraEngine
- Profile pinning into your repository
- CI slicing and artifact generation
- Printing handled by external tools (e.g. [bambox](#sending-prints-to-a-printer) for Bambu Lab) wired in as command stages

> **Warning:** estampo is in active early development. We are moving fast and breaking things — config format, CLI flags, and Python APIs may change between minor versions without deprecation. Pin your version if stability matters to you.

## Quick start

**Prerequisites:** Python 3.11, 3.12, or 3.13 (3.14 is not yet supported) and [Docker](https://docs.docker.com/get-docker/).
Docker is central to estampo — it runs the slicer (OrcaSlicer or CuraEngine) in a container with a pinned
version so every machine produces identical G-code. A locally installed slicer can be used as a
fallback but is not recommended.

```bash
pip install estampo
# or, to install as an isolated CLI tool:
pipx install estampo
# or, with uv:
uv tool install estampo
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
estampo run                   # run every stage in pipeline.stages
estampo run --until slice     # stop after slicing
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

> **CuraEngine: pin non-bundled printers.** If your config uses a printer definition that isn't shipped with estampo (e.g. `bambox_p1s`), `estampo profiles pin` is **required**, not optional — the definition only exists inside the Docker image. Without it, `estampo run --local` fails and a teammate who clones the repo gets an empty `profiles/` directory. `estampo init` will remind you when you pick a non-bundled CuraEngine printer.

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
estampo --version                   # print version
estampo init                        # interactive config wizard
estampo init --template             # dump commented TOML template
estampo init --workflow             # wizard + GitHub Actions workflow
estampo validate                    # check config for issues
estampo info                        # list valid stages, engines, orient values, substitution variables
estampo run                         # full pipeline
estampo run --until plate           # stop after plating
estampo run --only slice            # run just one stage
estampo profiles list               # list available slicer profiles
estampo profiles list --printer "Bambu Lab P1S 0.4 nozzle"   # processes/filaments compatible with a printer
estampo profiles pin                # pin profiles for reproducible builds
```

### Shell completion

estampo ships with Typer's built-in completion support:

```bash
estampo --install-completion        # install completion for your current shell (bash/zsh/fish/pwsh)
estampo --show-completion           # print the completion script without installing
```

After installing, restart your shell — you'll get tab completion for commands, flags, and stage names.

## Sending prints to a printer

estampo is **printer-agnostic**: it produces a sliced `.gcode.3mf` on disk and
stops there. Packing the output into a vendor-specific format and sending it
to a printer are handled by external CLIs wired into the pipeline as
[command stages](https://github.com/estampo/estampo/blob/main/docs/config.md#command-stages).
This keeps vendor-specific code out of estampo and lets you swap printer
backends without touching the build system.

### bambox (Bambu Lab)

For Bambu Lab printers, the companion CLI is
[bambox](https://github.com/estampo/bambox). estampo never imports bambox —
you install it separately and call it from your pipeline. Typical wiring:

```bash
pip install bambox
bambox login        # one-time — credentials saved to ~/.config/bambox/credentials.toml
```

For OrcaSlicer output, `bambox repack` regenerates the Bambu settings
in-place so the printer accepts the archive:

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "pack"]

[pack]
command = "bambox repack {sliced_3mf}"
output = "{sliced_3mf}"
```

For CuraEngine output, `bambox pack` wraps the raw `.gcode` into a
`.gcode.3mf`:

```toml
[pack]
command = "bambox pack {sliced_dir}/plate.gcode -o {output_dir}/plate.gcode.3mf"
output = "{output_dir}/plate.gcode.3mf"
```

To send the packed archive to a printer, add a stage that calls
`bambox print` — this uses Bambu Cloud and requires either the
`bambox-bridge` native binary (Linux x86_64) or Docker (macOS,
Windows, Linux ARM64). See the [AI setup prompt](docs/ai-setup-prompt.md)
for full examples including GitHub Actions wiring, and the
[bambox README](https://github.com/estampo/bambox) for bridge setup.

### Other printers

Any CLI that reads a sliced file and does something with it can be a
command stage. If your printer vendor has a CLI, wire it in the same way.
If it doesn't, `estampo run` already gives you a G-code file — hand it to
your printer however you normally would.

For Klipper-based printers with Moonraker, a one-line `curl` upload is
enough — no extra tool required:

```toml
[pipeline]
stages = ["load", "arrange", "plate", "slice", "send"]

[send]
command = "curl -F 'file=@{sliced_3mf}' -F 'print=true' http://moonraker.local/server/files/upload"
```

`{sliced_3mf}` is substituted by estampo with the path to the sliced
file. Set `print=false` if you want to upload without starting the job.

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

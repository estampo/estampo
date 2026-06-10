---
name: estampo
description: Reproducible 3D print pipelines with estampo. Use when asked to print, slice, or set up printing for a project's 3D models (STL/STEP/3MF or code-CAD output) — creating or editing estampo.toml, choosing slicer engine and profiles, tuning overrides for supports/adhesion/thin walls, running the pipeline, and pinning everything for CI.
---

# Print with estampo

Use this skill when asked to print or slice parts, automate printing, or set up
a print pipeline in a project that has 3D models (STL, STEP, 3MF) or code-CAD
sources that produce them. estampo is a declarative build system: everything —
parts, slicer settings, plate layout, post-processing — lives in one
`estampo.toml`, so the whole job is reviewable text, not GUI clicks.

Reference material when you need detail beyond this skill:
- [llm.md](https://github.com/estampo/estampo/blob/main/docs/llm.md) — config
  reference with the common override keys for both engines
- [estampo.schema.json](https://github.com/estampo/estampo/blob/main/docs/estampo.schema.json)
  — full config schema; `orca-settings.json` / `cura-settings.json` for every setting

---

## Step 0 — Check the environment

```bash
estampo --version || uv tool install estampo   # or: pip install estampo
docker info --format 'docker ok' 2>/dev/null
```

Docker is how estampo pins the slicer version for identical G-code everywhere;
without it a local slicer install is used as a fallback (not reproducible —
warn the user). If the project already has an `estampo.toml`, read it first and
edit rather than regenerate.

## Step 1 — Find the parts

Locate STL/STEP/3MF files, and the code-CAD sources that generate them
(build123d/CadQuery Python, OpenSCAD). If meshes are generated, regenerate them
from source before slicing rather than trusting stale artifacts. STEP is
preferred input from code-CAD — estampo tessellates it at load time.

## Step 2 — Engine and printer (ask, don't guess)

The one rule: **`orca` for Bambu Lab printers, `cura` for everything else.**
estampo bundles 35 Orca machine profiles (all Bambu Lab) and 643 Cura profiles
(Creality, Prusa, Voron, Ultimaker, Anycubic, Elegoo, …). Picking orca for a
non-BBL printer means the user must supply their own machine profile.

[ASK: Which printer (make/model/nozzle) and which filament(s) are loaded?]
if the repo doesn't say. Then discover exact profile names — never invent them:

```bash
estampo profiles list --engine orca --category machine
estampo profiles list --engine orca --category process --printer "Bambu Lab P1S 0.4 nozzle"
estampo profiles list --engine orca --category filament --printer "Bambu Lab P1S 0.4 nozzle"
```

**Always pass `--printer` when listing process/filament profiles.** OrcaSlicer
silently fails at slice time (exit 239) if the process and printer are
incompatible; the filter only shows compatible ones.

**Filament rule:** match the profile to the filament actually loaded, not the
printer brand. Vendor profiles (e.g. "Bambu PLA Basic") assume that vendor's
filament and under-extrude with generic spools — default to `"Generic … @base"`.

## Step 3 — Write and validate the config

```toml
name = "widget"

[slicer]
engine = "orca"
version = "2.3.1"              # pin for reproducibility

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL X1C"
filaments = ["Generic PLA @base"]

[[parts]]
file = "widget.step"
orient = "upright"             # code-CAD output is usually Z-up already
copies = 1
filament = 1                   # AMS slot / extruder index
```

Per-part options: `orient = "flat"|"upright"`, `rotate = [x, y, z]` degrees,
`copies`, `filament`. Then:

```bash
estampo validate
```

`validate` checks structure and setting names — **not** print safety. Never
tell the user the settings are safe; tell them to review the sliced output.

## Step 4 — Overrides: map part concerns to settings

Put process tweaks in `[slicer.orca.overrides]` (or `[slicer.cura.overrides]`
— key names differ between engines; see llm.md for both tables). The common
mappings from part geometry to settings:

| Concern | Orca override |
|---------|---------------|
| Overhangs > ~45° | `enable_support = 1`, `support_type = "tree(auto)"`, `support_threshold_angle = 45` |
| Poor bed adhesion / tip-over risk | `brim_type = "outer_only"`, `brim_width = "5mm"` |
| Thin walls near nozzle width | `detect_thin_wall = 1`, check `line_width` |
| Strength | `wall_loops = 3`, `sparse_infill_density = "25%"` |
| Dimensional accuracy (holes tight) | `xy_hole_compensation`, `elefant_foot_compensation` |

If the geometry came from the build123d-mcp server, its
`analyze_printability()` report (overhangs, thin walls, brim/raft need,
bed-fit) tells you exactly which of these to set — apply the findings here
instead of guessing.

## Step 5 — Run

```bash
estampo run
```

Read the summary it prints (part count, plate fit, print time, filament use)
back to the user. Useful variants: `estampo run --until slice` (stop before
post-processing), `estampo run --only arrange` (re-run one stage). Output lands
in `estampo_output/` — keep it gitignored.

## Step 6 — Make it reproducible (and CI, if asked)

1. `version = "…"` pinned in `[slicer]` — exact slicer binary via Docker.
2. `estampo profiles pin` — copies referenced profiles into `./profiles/`;
   commit that directory so builds don't depend on locally installed profiles.
3. Commit `estampo.toml` + CAD sources + (optionally) generated meshes;
   gitignore `estampo_output/`.

For CI, `estampo init --workflow` scaffolds a GitHub Actions workflow, or write
one that regenerates meshes from code-CAD sources first and then runs
`estampo run` — same repo, same config, same G-code.

---

## Pitfalls

- **Exit 239 from OrcaSlicer** = incompatible printer/process/filament profile
  combination. Re-run `estampo profiles list … --printer "<printer>"` and pick
  from the filtered list.
- Vendor-branded filament profiles with generic filament cause
  under-extrusion — use `"Generic … @base"` unless the actual spool matches.
- Slicing without Docker works but is not reproducible across machines; say so
  rather than silently falling back.
- estampo generates G-code from configuration but cannot verify it is safe for
  the user's specific printer — always tell the user to review the sliced
  output before printing.

# CuraEngine Printer Definition Discovery, Selection & Pinning

## Context

CuraEngine support is currently hardcoded to the Bambu Lab P1S. Users can't
select a different printer during `estampo init`, the TOML doesn't store the
printer choice, and there's no way to pin (squash) CuraEngine definitions for
reproducible builds. OrcaSlicer already has all of this working -- this plan
extends the same patterns to CuraEngine.

The Docker image already ships ALL standard Cura printer definitions at
`/opt/cura/definitions/*.def.json` (extracted from the Cura 5.12.0 AppImage).

### CuraEngine vs OrcaSlicer profile model

OrcaSlicer has three profile categories: **machine**, **process**, and
**filament**. Each is a JSON file with an optional `inherits` key pointing to a
parent profile. `estampo profiles pin` flattens (squashes) the inheritance chain
into standalone JSON files committed to the project.

CuraEngine has a single concept: **printer definitions** (`.def.json` files).
These contain machine geometry, start/end G-code, and hundreds of default
slicer settings. Definitions form an inheritance chain:

```
bambulab_p1s.def.json
  -> inherits: bambulab_base.def.json
    -> inherits: fdmprinter.def.json  (root -- ~4000 settings)
```

CuraEngine has no separate process or filament profiles -- all tuning is done
via `-s key=value` overrides on the command line, which estampo stores in
`[slicer.cura.overrides]`.

## Design

### TOML config

The selected printer definition is stored in the TOML config:

```toml
[slicer]
engine = "cura"
version = "5.12.0"
bed_type = "Textured PEI Plate"

[slicer.cura]
printer = "BambuLab P1S"

[slicer.cura.overrides]
layer_height = 0.2
sparse_infill_density = "30%"
```

The `printer` value is the human-readable name from the `.def.json` file's
`name` field. Resolution maps this to a filename stem (e.g.
`"BambuLab P1S"` -> `bambulab_p1s.def.json`) via a bundled manifest.

### Bundled manifest

A manifest file `src/estampo/data/profiles.cura.<version>.json` lists all
available printer definitions extracted from the Docker image:

```json
{
  "engine": "cura",
  "version": "5.12.0",
  "machine": [
    {"name": "BambuLab P1S", "id": "bambulab_p1s"},
    {"name": "Ultimaker S5", "id": "ultimaker_s5"},
    ...
  ],
  "process": [],
  "filament": []
}
```

The `machine` key contains objects with `name` (display) and `id` (filename
stem). `process` and `filament` are empty lists for API consistency with the
OrcaSlicer manifest shape.

### Pinning (inheritance squashing)

`estampo profiles pin` with `engine = "cura"` extracts the full `.def.json`
inheritance chain from the Docker image and deep-merges `overrides` into a
single standalone file:

```
profiles/cura/definitions/bambulab_p1s.def.json   (squashed, no inherits)
profiles/cura/.slicer-version                      (e.g. "5.12.0")
```

Deep merging is required because CuraEngine overrides are nested:

```json
{
  "overrides": {
    "layer_height": {"value": 0.2, "default_value": 0.4},
    "speed_print": {"value": 80}
  }
}
```

Child values override parent values at the sub-dict level per setting key.

### Resolution order

At slice time, the printer definition is resolved in this order:

1. **Pinned** -- `profiles/cura/definitions/<id>.def.json` (squashed, standalone)
2. **Bundled** -- `src/estampo/data/<id>.def.json` (shipped with estampo)
3. **Docker** -- `/opt/cura/definitions/<id>.def.json` (inside the container)

If the definition is pinned (squashed), only the single file is needed. If not
pinned, the full inheritance chain must be available via CuraEngine's `-d`
search path.

## Implementation plan

### 1. Extract CuraEngine definition manifest from Docker

**File: `scripts/extract_profiles.py`**

Add `--engine cura` support:

- Run `docker find` against `/opt/cura/definitions -name "*.def.json"` to list
  all definition files in the image.
- Bulk-copy to a temp directory, read each JSON.
- Filter: only include definitions where `metadata.visible` is not `false`
  (skips intermediate definitions like `bambulab_base`, `fdmprinter`).
- Build manifest with `{name, id}` objects under the `machine` key.
- Write to `src/estampo/data/profiles.cura.5.12.0.json`.

### 2. Config: add `printer` to CuraSlicerConfig

**File: `src/estampo/config.py`**

- Add `printer: str | None = None` to `CuraSlicerConfig`.
- Update `_parse_cura_config()` to read `raw.get("printer")`.
- Update the active-engine facade: set `active_printer = cura_cfg.printer`
  instead of hardcoded `None`.

This means `cfg.slicer.printer` flows through the pipeline to
`cura_profile_from_config()` automatically -- no slicer.py changes needed.

### 3. Manifest loading and discovery

**File: `src/estampo/profiles.py`**

- Remove `"cura"` from `_INLINE_ENGINES`.
- Update `load_bundled_profiles()` to handle Cura manifest entries that are
  objects (`{name, id}`) rather than plain strings -- extract the `name` field.
- `discover_profile_names()` for `engine == "cura"`:
  - Skip system profiles (no CuraEngine system install paths).
  - Check pinned definitions at `profiles/cura/definitions/*.def.json`.
  - Fall through to bundled manifest.
- Add `load_cura_definition_map()` helper: loads the manifest and returns a
  `{name: id}` mapping for name-to-filename resolution.

### 4. Init wizard: searchable picker

**File: `src/estampo/init.py`**

Replace the current CuraEngine numbered-list picker with the same
`_prompt_choice()` -> `ui.pick()` flow used by OrcaSlicer:

- Call `discover_profile_names("cura")` to get available printer names.
- Present via `ui.pick()` with type-to-search filtering.
- After selection, load the `.def.json` to extract `machine_width` /
  `machine_depth` for plate size auto-detection.
- Update `_build_toml()` to emit `printer = "..."` under `[slicer.cura]`.

### 5. Slice-time definition resolution

**File: `src/estampo/cura.py`**

- Add `resolve_cura_definition(printer_name, project_dir, profiles_dir)` that
  returns the path to the `.def.json` and its inheritance chain.
- Update `slice_stl()`:
  - Replace hardcoded `_BBL_DEFS` with dynamic resolution using the printer
    name from the profile.
  - Copy resolved def (+ chain if not pinned) to staging.
  - Keep `-d` search paths for Docker's built-in defs as fallback.
- Update `cura_profile_from_config()`:
  - Extract `machine_width` / `machine_depth` from the resolved `.def.json`
    overrides for bed placement (centering).
- Remove `machine_width` / `machine_depth` from `CuraProfile` dataclass --
  these come from the `.def.json` at runtime.

### 6. Pinning (inheritance squashing)

**File: `src/estampo/profiles.py`**

Add `pin_cura_definitions()`:

- Extract all `.def.json` files from Docker image to a temp directory.
- Walk the inheritance chain for the selected printer definition.
- Deep-merge `overrides` dicts (child values override parent at the per-setting
  sub-dict level).
- Remove the `inherits` key from the result.
- Write the squashed `.def.json` to `profiles/cura/definitions/<id>.def.json`.
- Write `.slicer-version` marker file.

Add `_deep_merge_cura_overrides(base, child)` helper for the nested merge.

Update `pin_profiles()`: remove `_INLINE_ENGINES` early return; delegate to
`pin_cura_definitions()` when `engine == "cura"`.

### 7. `profiles add` for custom definitions

**File: `src/estampo/profiles.py`**

- Update `detect_category()` to recognize `.def.json` structure (`version`,
  `overrides`, `metadata` keys) as `"machine"`.
- Update `add_profile()` to write CuraEngine definitions to
  `profiles/cura/definitions/` with `.def.json` extension.
- The existing inheritance warning already handles unresolved `inherits`.

### 8. CI workflow

**File: `.github/workflows/release-readiness.yml`**

Add a CuraEngine profile extraction job (parallel to OrcaSlicer):

- Build/pull the `estampo/estampo:cura-5.12.0-test` image.
- Run `uv run python scripts/extract_profiles.py --engine cura 5.12.0`.
- Validate the manifest structure.
- Commit `profiles.cura.5.12.0.json` on push to main.

### 9. Tests

- **`test_profiles.py`**: `discover_profile_names("cura")`,
  `pin_cura_definitions()`, `_deep_merge_cura_overrides()`.
- **`test_cura.py`**: `resolve_cura_definition()`, updated
  `test_slice_stl_docker_command` for dynamic def resolution.
- **`test_config.py`**: `CuraSlicerConfig.printer` parsing from TOML.

## Files to modify

| File | Changes |
|------|---------|
| `scripts/extract_profiles.py` | Add `--engine cura` extraction |
| `src/estampo/config.py` | `CuraSlicerConfig.printer`, facade wiring |
| `src/estampo/profiles.py` | Remove inline engines, manifest loading, pinning, `add_profile` |
| `src/estampo/cura.py` | Dynamic def resolution, bed size from def.json |
| `src/estampo/init.py` | Searchable picker, TOML generation |
| `src/estampo/cli.py` | Remove inline engine skips in profiles commands |
| `.github/workflows/release-readiness.yml` | Cura extraction job |
| `tests/test_*.py` | New tests for discovery, pinning, config |

## Implementation order

Steps 1 and 2 have no dependencies and can be done in parallel as the first
PR. Steps 3-5 form the core feature PR. Steps 6-7 add pinning support.
Step 8 is CI integration. Tests are woven throughout.

```
1. Extract script + manifest ----+
2. Config changes ---------------+--> PR 1: foundation
3. Profile discovery + loading --+
4. Init wizard picker -----------+--> PR 2: user-facing selection
5. Slice-time resolution --------+
6. Pinning / squashing ----------+--> PR 3: reproducibility
7. profiles add updates ---------+
8. CI workflow ------------------+--> PR 4: automation
9. Tests (throughout)
```

## Verification checklist

1. `uv run python scripts/extract_profiles.py --engine cura 5.12.0` produces
   a valid manifest with all visible printer definitions.
2. `estampo init` with `engine = "cura"` shows a searchable printer list.
3. Generated TOML contains `[slicer.cura] printer = "BambuLab P1S"`.
4. `estampo slice` uses the selected printer definition (not hardcoded P1S).
5. `estampo profiles pin` squashes a Cura definition chain into a standalone
   file that works without Docker's built-in definitions.
6. `estampo profiles add custom.def.json` imports to the right location with
   correct category detection.
7. All existing tests pass + new tests cover Cura discovery/pinning.
8. `ruff check`, `ruff format --check`, `mypy`, `pytest` all clean.

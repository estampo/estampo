# Fix: `estampo profiles pin` must fully resolve the inheritance chain

## Background

`estampo profiles pin` is supposed to produce fully resolved, immutable profile
snapshots — independent of whatever OrcaSlicer version is installed. The goal is
that a pinned `profiles/` directory reproduces the exact same slice forever.

It is **not** working correctly. The pinned profiles are missing inherited values
that live in parent profiles. Any value not overridden by the leaf profile is
silently dropped, leaving the snapshot dependent on OrcaSlicer's compiled-in
defaults — which defeats the purpose entirely.

## Concrete failure

Project: `~/repos/decoy-case`
Config: `estampo.toml` uses `printer = "Bambu Lab P1S 0.4 nozzle"`,
`process = "0.20mm Standard @BBL X1C"`

Slicing fails with:

```
Relative extruder addressing requires resetting the extruder position at each
layer to prevent loss of floating point accuracy. Add "G92 E0" to layer_gcode.
```

This is a hard error in OrcaSlicer (inherited from PrusaSlicer, introduced in
2.4.1-beta1). It fires when all three are true:
- `gcode_flavor = "marlin"` ✓ (P1S machine profile)
- `use_relative_e_distances = "1"` ✓ (OrcaSlicer's compiled-in default)
- No unconditional `G92 E0` in `layer_change_gcode` ✓ (Bambu's profile has one
  but it's inside `{elsif timelapse_type == 1}`, which the validator can't see
  through)

The Bambu Lab P1S system profiles in OrcaSlicer GUI **do not** trigger this
because somewhere in their inheritance chain they explicitly set
`use_relative_e_distances = "0"`. That value is never captured in the pinned
snapshots.

## Where the bug is

**File:** `src/estampo/profiles.py`

Two functions attempt to walk the inheritance chain:

### `_resolve_profile_data_from_dir` (used for Docker fallback)

```python
parent_name = data.get("inherits")
if not parent_name:
    break
parent = current.parent / f"{parent_name}.json"
if parent.exists():
    current = parent
else:
    break   # ← silently stops if parent file not found
```

### `resolve_profile_data` (used for local/system profiles)

```python
parent_name = data.get("inherits")
if not parent_name:
    break
sibling = current.parent / f"{parent_name}.json"
system = (base / category / f"{parent_name}.json") if base else None
if sibling.exists():
    current = sibling
elif system and system.exists():
    current = system
else:
    break   # ← silently stops if parent not found in sibling or system dir
```

Both silently truncate the chain when a parent profile file is not found in the
expected location. In the OrcaSlicer BBL profile tree, not all parents are in
the same subdirectory — some are common base profiles. When running from the
Docker-extracted temp dir, if a parent isn't found, the walk stops early and
the inherited value is lost.

Additionally, `extract_docker_profiles` copies `machine/`, `process/`,
`filament/` subdirectories out of the Docker image, but OrcaSlicer may also have
shared/common profiles at the BBL root or in a separate `common/` directory
that are referenced by `"inherits"`. These are not copied and so the walk always
breaks at the first cross-directory parent.

## What the fix should do

1. **Copy all profiles from the Docker image**, not just the three category
   subdirectories. Include any `common/` or root-level JSON files at
   `/opt/orca-slicer/resources/profiles/BBL/` that may serve as base profiles.

2. **Never silently drop a parent** — if a parent named in `"inherits"` cannot
   be found, log a warning but do not silently stop the chain. Optionally raise
   an error in strict mode.

3. **Search all category dirs** when resolving a parent, not just the same
   directory. The parent of a `process` profile could be in a `common/`
   directory.

4. **Verify correctness** after pinning: re-pin the decoy-case profiles and
   confirm `use_relative_e_distances` appears (as `"0"`) in the output
   `profiles/process/0.20mm Standard @BBL X1C.json`.

## How to verify the fix

```bash
cd ~/repos/decoy-case
rm -rf profiles/
estampo profiles pin
# Should produce profiles/ with fully resolved JSON
grep use_relative_e_distances profiles/process/0.20mm\ Standard\ @BBL\ X1C.json
# Must print: "use_relative_e_distances": "0"
estampo slice   # Must succeed with no relative-extruder error
```

## Temporary workaround in place

`~/repos/decoy-case/estampo.toml` currently has:

```toml
[slicer.overrides]
use_relative_e_distances = "0"
```

This masks the symptom. **Remove it once the pin fix is confirmed working.**

## Relevant files

| File | Role |
|------|------|
| `src/estampo/profiles.py` | `pin_profiles`, `resolve_profile_data`, `_resolve_profile_data_from_dir`, `extract_docker_profiles` |
| `src/estampo/cli.py:777` | `profiles pin` CLI command |
| `scripts/extract_profiles.py` | Extracts profile **names** only (not content) — separate from pinning |
| `~/repos/decoy-case/profiles/` | Broken pinned profiles to re-generate after fix |
| `~/repos/decoy-case/estampo.toml` | Has temporary override to remove after fix |

## Docker image profile layout

Inside `estampo/estampo:orca-2.3.1`, OrcaSlicer BBL profiles live at:

```
/opt/orca-slicer/resources/profiles/BBL/
    machine/
    process/
    filament/
    (possibly common/ or root-level base profiles)
```

`extract_docker_profiles` currently copies only `machine/`, `process/`,
`filament/`. Investigate the full directory tree to see what else is there.

```bash
docker run --rm --entrypoint find estampo/estampo:orca-2.3.1 \
    /opt/orca-slicer/resources/profiles/BBL -name "*.json" | head -40
```

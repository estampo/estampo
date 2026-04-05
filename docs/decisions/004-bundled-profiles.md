# ADR-004: Bundled Profile Extraction and Versioning

**Status:** Accepted  
**Date:** 2026-01  

## Context

OrcaSlicer profiles (machine, process, filament) are distributed as JSON files inside the OrcaSlicer application bundle / Docker image. Users need profile names available during `estampo init` to select their printer and process. This must work:

1. Without Docker installed
2. Without OrcaSlicer installed locally
3. With a specific pinned OrcaSlicer version

Options considered:
1. **Always require Docker** — pull image, extract profiles on demand; fails offline, slow
2. **Require local OrcaSlicer install** — reads system profile dirs; version-locked to whatever the user has installed
3. **Bundle extracted profiles** — extract from Docker image at release time, commit to repo, ship in pip package

## Decision

Extract OrcaSlicer profiles from the Docker image and commit them to `src/estampo/data/` as `profiles.orca.<version>.json`. These are bundled in the pip package so `estampo init` works with no external dependencies.

## Rationale

- **Zero-dependency init:** A fresh `pip install estampo; estampo init` can present the full profile list without Docker or a local slicer
- **Version-matched:** Bundled profiles match the Docker image version, so profile names shown during init are valid for the pinned slicer
- **Automated:** The `release-readiness.yml` workflow extracts and commits profiles automatically on push to main. No manual step.

## Implementation

- `src/estampo/data/profiles.orca.<version>.json` — extracted profile names per version
- `load_bundled_profiles(engine, version)` in `profiles.py` — loads the matching file, falls back to highest available version if exact not found
- `test_bundled_profiles_*` tests in `test_profiles.py` — enforce that bundled files exist and are non-empty
- `release-readiness.yml` runs `scripts/extract_profiles.py` and commits the result

## Consequences

- **Release gate:** Never tag a release without confirming bundled profile files exist and are current. CI enforces this.
- **File size:** Profile files are JSON arrays of strings — small. Not a concern.
- **Stale profiles:** If a new OrcaSlicer version is released and the workflow hasn't run yet, `load_bundled_profiles()` falls back to the previous version. This is acceptable.
- **CuraEngine:** CuraEngine uses `.def.json` machine definition files, not a profile chain. The equivalent is bundled def files in `src/estampo/data/cura/`. A separate extraction workflow will be added.

## Anti-patterns to avoid

- Do not hardcode profile names in Python — always read from bundled JSON or discovered system paths
- Do not skip the bundled profile check before tagging a release
- Do not edit `src/estampo/data/profiles.orca.*.json` manually — let the workflow regenerate them

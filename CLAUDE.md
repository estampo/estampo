# Estampo - Claude Code Instructions

## Working with the maintainer
The project maintainer is technically experienced and understands the codebase deeply. When they tell you something — about how the code works, what's broken, or what needs to happen — trust their judgement. Don't second-guess their observations or explain things they already know. If they say something is failing, it is.

## Issues and PRs

Every non-trivial piece of work should have a GitHub issue. Before starting:
- Check `gh issue list` for an existing issue covering the work
- If none exists, create one with `gh issue create` before writing code
- Reference it in the PR body with `Closes #N` so it auto-closes on merge

Issues live at: https://github.com/estampo/estampo/issues  
Milestones: v0.3.0 (CuraEngine production-ready), v0.4.0 (bambox extraction)

## Pre-PR Checklist (MANDATORY)
Before pushing any PR branch, always run locally:
1. `uv run ruff check src tests` — lint must pass with zero errors
2. `uv run ruff format --check src tests` — formatting must pass (run `uv run ruff format src tests` to auto-fix)
3. `uv run mypy src/estampo` — type check must pass with zero errors
4. `uv run pytest` — all tests must pass

Do NOT push a PR until all four checks pass locally.

## Changelog (MANDATORY)
Every PR must include a **towncrier fragment file** in the `changes/` directory:
1. Create a file: `changes/<PR-number>.<type>` where type is `feature`, `bugfix`, or `misc`
2. Write a single line — concise, user-facing description of the change
3. If the PR has no number yet, use `+descriptive-name.<type>` (orphan fragment)
4. Do NOT edit CHANGELOG.md directly — towncrier compiles fragments at release time

Example: `changes/245.feature` containing:
```
Add ``prepare-release.yml`` workflow for single-command release preparation
```

At release time, `prepare-release.yml` runs `towncrier build --version X.Y.Z` which compiles all fragments into CHANGELOG.md and deletes them.

## Post-PR Checklist (MANDATORY)
After pushing a PR or merging to main:
1. Check GitHub Actions CI status with `gh run list --limit 3`
2. If any run fails, inspect with `gh run view <id> --log-failed`
3. Fix failures before moving on to other work

## Module Ownership (enforce strictly)

Each module has a defined scope. Do not add logic to the wrong module — even if it seems convenient.

| Module | Owns | Must NOT contain |
|--------|------|-----------------|
| `pipeline.py` | Hamilton DAG node definitions, stage wiring | Slicer invocation, G-code parsing, printer logic |
| `orca.py` | All OrcaSlicer-specific logic — implements slicer plugin protocol | CuraEngine logic, G-code parsing, printer dispatch |
| `cura.py` | All CuraEngine-specific logic — implements slicer plugin protocol | OrcaSlicer logic, printer dispatch |
| `slicer.py` | Pure dispatch layer — routes to `orca.py` / `cura.py` by engine key | Engine-specific invocation logic |
| `gcode.py` | All G-code parsing and metadata extraction | Slicer invocation, UI output |
| `profiles.py` | Pure dispatch — routes profile/definition calls to the active engine module | Engine-specific profile logic (that lives in `orca.py` / `cura.py`) |
| `config.py` | TOML parsing, config dataclasses | Business logic, file I/O beyond TOML |
| `cli.py` | Typer commands, user-facing flags, Hamilton driver construction | Pipeline logic, slicer invocation |
| `adapters.py` | Hamilton lifecycle hooks (progress, timing) | Pipeline logic, direct node invocation |
| `commands.py` | Command stage execution (generic subprocess runner) | Printer-specific logic, slicer logic |
| `printer.py` | **DEPRECATED — deleting in v0.4.0** (Bambu dispatch) | New code — use command stages instead |
| `credentials.py` | **DEPRECATED — deleting in v0.4.0** (Bambu credentials) | New code — credentials belong in bambox |

## Architecture: Key Decisions

Eight architecture decisions are documented in `docs/decisions/`. Read them before changing any of the following:

1. **`docs/decisions/001-hamilton-dag-pipeline.md`** — Why Hamilton; DAG invariants; what must not go in pipeline nodes
2. **`docs/decisions/002-docker-local-fallback.md`** — Docker-first + local fallback; `docker_image()` as single source of truth
3. **`docs/decisions/003-multi-engine-facade.md`** — OrcaSlicer + CuraEngine coexistence; facade pattern on SlicerConfig; engine-specific code stays in slicer.py / cura.py
4. **`docs/decisions/004-bundled-profiles.md`** — Profiles extracted from Docker, committed to repo, bundled in pip package
5. **`docs/decisions/005-vendor-agnostic-split.md`** — estampo is printer-agnostic; Bambu code is deleted (not moved); bambox is CLI-only (never imported)
6. **`docs/decisions/006-slicer-plugin-protocol.md`** — Slicer engine modules as first-class peers; dispatch layers stay pure
7. **`docs/decisions/007-command-stages.md`** — External CLI tools as pipeline stages; `str.format_map()` variable substitution
8. **`docs/decisions/008-verbatim-cura-def-pinning.md`** — Pin CuraEngine def chain verbatim; no squashing, no value-literal workarounds; trust CuraEngine's own resolution

**Before adding a new slicer engine:** read ADR-006 (the complete protocol a new engine module must implement).  
**Before adding engine `if/elif` to profiles.py, init.py, or slicer.py:** read ADR-006 — it goes in the engine module instead.  
**Before touching Docker image tag construction:** read ADR-002.  
**Before adding logic to pipeline.py:** read ADR-001.  
**Before changing profile loading:** read ADR-004.  
**Before changing how CuraEngine definitions are pinned or merged:** read ADR-008 — **do not reintroduce squashing or value-literal promotion.**  
**Before adding Bambu-specific code anywhere:** read ADR-005 — **do not add it. estampo is printer-agnostic.**  
**Before adding printer/packaging logic:** read ADR-005 + ADR-007 — it belongs in a command stage, not in estampo.  
**Before importing bambox:** read ADR-005 + ADR-007 — **do not import it. CLI integration only.**

## What estampo is NOT

To prevent scope creep and re-invention:

- **Not a slicer.** estampo wraps slicers (OrcaSlicer, CuraEngine). Do not reimplement slicing algorithms in Python.
- **Not a profile editor.** estampo pins and references profiles. Do not build profile editing UI or deep profile merging logic.
- **Not a printer tool.** estampo does not send files to printers, package G-code for specific printer vendors, or handle printer authentication. Printing and packaging are handled by external tools (e.g. `bambox` for Bambu Lab) configured as command stages in TOML. See ADR-005.
- **Not a CAD tool.** estampo loads meshes. The `build123d` integration is for code-CAD users who want to go straight from model to print — it is not a CAD kernel.
- **Not a standalone G-code generator.** G-code comes from the slicer. estampo parses G-code metadata (print time, filament weight) but does not generate toolpaths.
- **Not a Bambu tool (or any vendor's tool).** estampo is printer-agnostic. All Bambu-specific code is being deleted (v0.4.0) — not moved, not wrapped. The `bambox` package is a separate CLI tool for Bambu Lab printers. estampo never imports bambox; integration is via command stages (ADR-005, ADR-007). Do not add printer-vendor logic to any estampo module.

## Architecture: Slicer Execution

The user installs estampo via pip/pipx on their local machine. When slicing:
1. The Python CLI calls `docker run --entrypoint orca-slicer estampo/estampo:orca-<version> ...`
2. Docker runs OrcaSlicer inside the container; volumes mount input/output
3. If Docker is unavailable, falls back to a locally installed OrcaSlicer with a warning

In the GitHub Action context, estampo runs *inside* the Docker container. Docker-in-Docker is not available, so it automatically falls back to the local OrcaSlicer binary baked into the image.

**Key rule**: Never force slicer settings (like `use_relative_e_distances`) — let the OrcaSlicer profile chain decide. Forcing values can conflict with machine profiles.

## Docker Image Tags

All Docker image tags use the format `estampo/estampo:orca-<version>`. The `docker_image()` function in `slicer.py` is the single source of truth — always import it rather than constructing the tag string manually.

## Bundled Profiles

OrcaSlicer profiles are extracted from the Docker image and committed to `src/estampo/data/`. This happens automatically via the `release-readiness` workflow on push to main. The profiles are bundled in the pip package so `estampo init` works without Docker.

**Key rule**: Never tag a release without confirming `src/estampo/data/profiles.orca.*.json` files exist and are up-to-date. The `test_bundled_profiles_*` tests in `test_profiles.py` enforce this.

## Release Process

### Automated flow (preferred)

1. Run: `gh workflow run prepare-release.yml -f version=X.Y.Z`
2. The workflow creates a `release/vX.Y.Z` branch with version bump + changelog (towncrier compiles fragment files from `changes/`)
3. Review the PR, adjust changelog if needed, merge
4. On merge, `release.yml` detects the merged PR came from a `release/vX.Y.Z` branch, then: builds all artifacts → validates on TestPyPI → creates git tag → publishes to PyPI + Docker Hub + GHCR → creates GitHub Release

### Re-running prepare-release

If issues arise between prepare and merge (e.g. a hotfix lands), re-run `prepare-release.yml` with the same version. It will force-update the release branch and refresh the existing PR with the new changelog.

### Manual fallback

If the automatic pipeline fails after tagging: `gh workflow run release.yml -f tag=vX.Y.Z`

Both TestPyPI and PyPI have `skip-existing` enabled, so re-runs resume from where they left off.

**Critical**: PyPI versions are immutable. A failed release burns the version number. The TestPyPI dry-run gate catches most issues before the real publish. The tag is only created after TestPyPI succeeds.

## CI Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | PR / push to main | Lint, type check, test (3 OS × 3 Python), coverage, towncrier fragment check |
| `test-pypi.yml` | PR / push to main | Publish `.dev` package to TestPyPI (skips release PR merges) |
| `publish-docker.yml` | Push to main | Build Docker images when relevant files change (skips release PR merges) |
| `release.yml` | Push to main (release PR merge) / manual | Full release: detect release branch → build → TestPyPI gate → tag → publish all → GitHub Release |
| `prepare-release.yml` | Manual | Create release PR with version bump + towncrier changelog |
| `release-readiness.yml` | Push to main / nightly / manual | E2e: Docker build, smoke test, profile extraction + commit, real slice |
| `slice.yml` | Manual | Run a slice with custom config |

# Developing estampo

## Setup

Requires Python 3.11+.

```bash
git clone https://github.com/estampo/estampo.git
cd estampo
uv sync --extra dev
```

## Running tests

```bash
uv run pytest              # run all tests
uv run pytest -x -q        # stop on first failure, quiet output
uv run ruff check src tests     # lint
uv run ruff format src tests    # auto-format
```

## Pre-PR checklist

Before pushing a PR branch:

1. `uv run ruff check src tests` — lint must pass with zero errors
2. `uv run ruff format --check src tests` — formatting must pass
3. `uv run mypy src/estampo` — type check must pass with zero errors
4. `uv run pytest` — all tests must pass

## Publishing

Two automated pipelines handle publishing:

### Push to main (automatic)

Every merge to main triggers:
- **TestPyPI** — publishes a `.dev` package (e.g. `0.1.140.dev42`)
- **Docker** — rebuilds images with mutable tags (`orca-2.3.1`) when relevant files change
- **Release readiness** — builds Docker images, runs smoke tests, profile extraction, and a real slice (only when relevant files change)

No version bump needed for day-to-day work.

### Release (automated)

To publish a release:

1. Run: `gh workflow run prepare-release.yml -f version=X.Y.Z`
2. The workflow creates a `release/vX.Y.Z` branch with version bump + changelog (towncrier compiles fragment files from `changes/`)
3. Review the PR, adjust changelog if needed, merge
4. On merge, `release.yml` automatically: builds all artifacts → validates on TestPyPI → creates git tag → publishes to PyPI + Docker Hub + GHCR → creates GitHub Release

If issues arise between prepare and merge (e.g. a hotfix lands), re-run `prepare-release.yml` with the same version — it force-updates the release branch and refreshes the existing PR.

**Manual fallback:** If the automatic pipeline fails after tagging: `gh workflow run release.yml -f tag=vX.Y.Z`

### Release readiness

The `release-readiness.yml` workflow exercises the full release pipeline without publishing:

| Job | What it tests |
|-----|---------------|
| `build-estampo-image` | Docker image builds successfully |
| `build-cloud-bridge` | Cloud bridge image builds and binary works |
| `smoke-test` | `estampo --help` and `estampo run --help` work inside the container |
| `profile-extraction` | `extract_profiles.py` runs and produces valid JSON with profiles |
| `slice-test` | Real end-to-end slice using `examples/estampo.toml` |

Run it manually before tagging: `gh workflow run release-readiness.yml -f orca_version=2.3.1`

## Docker images

Pre-built OrcaSlicer images are on [Docker Hub](https://hub.docker.com/r/estampo/estampo). To build your own:

```bash
./scripts/build-docker.sh 2.3.1          # build only
./scripts/build-docker.sh 2.3.1 --push   # build and push
```

estampo auto-detects Docker and uses it for slicing when available, falling back to a local OrcaSlicer install with a warning. This fallback works even when a slicer version is pinned in config — so running inside a Docker container (e.g. the GitHub Action) works without `--local`. Force local with `--local` if you want to skip the Docker check entirely.

## Platform support

estampo auto-detects slicer paths per platform:

| Platform | OrcaSlicer |
|----------|------------|
| macOS    | `/Applications/OrcaSlicer.app/...` |
| Linux    | `/usr/bin/orca-slicer` |
| Windows  | `C:\Program Files\OrcaSlicer\...` |

Slicers on PATH are also detected (Flatpak, Snap, custom installs). Profile directories follow platform conventions (`~/Library/Application Support/` on macOS, `~/.config/` on Linux, `%APPDATA%` on Windows).

## Architecture

The pipeline is built on [Hamilton](https://github.com/DAGWorks-Inc/hamilton), a lightweight DAG framework. Each stage is a Python function in `src/estampo/pipeline.py` — Hamilton auto-wires dependencies by matching parameter names to function names.

```
load → arrange → plate → slice → gcode-info → print
```

The `TimingAdapter` in `src/estampo/adapters.py` hooks into Hamilton's lifecycle to log per-stage timing when `--verbose` is used.

### Key files

| File | Purpose |
|------|---------|
| `src/estampo/pipeline.py` | Hamilton DAG nodes and stage registry |
| `src/estampo/adapters.py` | TimingAdapter for observability |
| `src/estampo/cli.py` | CLI entry point (`run`, `setup`, `status`, `profiles`) |
| `src/estampo/config.py` | TOML parsing and validation |
| `src/estampo/arrange.py` | 2D bin-packing |
| `src/estampo/plate.py` | 3MF export with extruder metadata |
| `src/estampo/slicer.py` | OrcaSlicer CLI integration (local + Docker) |
| `src/estampo/printer.py` | Print dispatch (LAN, cloud, Bambu Connect) |
| `src/estampo/credentials.py` | Credential loading from `~/.config/estampo/credentials.toml` |

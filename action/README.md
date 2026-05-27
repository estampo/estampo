# Estampo GitHub Action

Slice 3D models with OrcaSlicer or CuraEngine on every push or PR — get build metrics (print time, filament usage) posted as a PR comment automatically.

The action reads `slicer.engine` and `slicer.version` from your `estampo.toml` and pulls the correct Docker image automatically. No engine-specific configuration needed.

## Usage

```yaml
name: Slice

on:
  push:
    branches: [main]
  pull_request:

jobs:
  slice:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@v6
      - uses: estampo/estampo/action@v0
        with:
          config: estampo.toml
```

This works for both OrcaSlicer and CuraEngine projects — the action detects which engine to use from your config.

## Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `config` | `estampo.toml` | Path to your estampo config file |
| `slicer-version` | *(from config)* | Override slicer version (reads `slicer.version` from TOML by default) |
| `until` | *(all stages)* | Pipeline stage to stop at (e.g. `plate`, `slice`) |
| `output-dir` | `estampo_output` | Output directory for sliced files (relative to repo root) |
| `comment` | `"true"` | Post/update a PR comment with build metrics. Set to `"false"` to disable (e.g. in release workflows where there is no PR to comment on). |

## Outputs

| Output | Description |
|--------|-------------|
| `print-time` | Estimated print time (e.g., "1h 7m 32s") |
| `filament-grams` | Total filament in grams |
| `gcode-path` | Path to output directory |

## What it does

1. Reads `slicer.engine` and `slicer.version` from your `estampo.toml`
2. Pulls the matching pre-built Docker image (e.g. `estampo:orca-2.3.1` or `estampo:cura-5.12.0`)
3. Runs `estampo run` against your config inside the container
4. Uploads sliced output as workflow artifacts
5. Posts a PR comment with print time and filament usage

## Requirements

- An `estampo.toml` in your repo with `slicer.engine` and `slicer.version` set
- STL/3MF/STEP model files referenced in your config
- The GHCR package must be public, or you must authenticate with `docker login ghcr.io` before this action runs
- If using the `comment` feature, your job needs `permissions: pull-requests: write`
- PR comments work with both `pull_request` and `workflow_run` triggers (the action looks up the PR from the commit SHA)
- To disable PR comments (e.g. in a release workflow that runs on `push` to main with no associated PR), pass `comment: "false"`:

  ```yaml
  - uses: estampo/estampo/action@v0
    with:
      comment: "false"   # no PR to comment on in release workflows
  ```

## Supported engines and versions

The action supports any engine with a published `ghcr.io/estampo/estampo:{engine}-{version}` image:

- **OrcaSlicer:** `2.3.1`
- **CuraEngine:** `5.12.0`

## Migration from `orca-version`

The `orca-version` input is deprecated. Remove it — the action now reads the engine and version from your config automatically. If you need to override the version, use `slicer-version` instead.

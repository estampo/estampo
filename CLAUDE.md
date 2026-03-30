# Estampo - Claude Code Instructions

## Pre-PR Checklist (MANDATORY)
Before pushing any PR branch, always run locally:
1. `uv run ruff check src tests` — lint must pass with zero errors
2. `uv run ruff format --check src tests` — formatting must pass (run `uv run ruff format src tests` to auto-fix)
3. `uv run mypy src/estampo` — type check must pass with zero errors
4. `uv run pytest` — all tests must pass

Do NOT push a PR until all four checks pass locally.

## Changelog (MANDATORY)
Every PR must include a CHANGELOG.md update:
1. Add bullet points under the `## Unreleased` section at the top of CHANGELOG.md
2. If `## Unreleased` doesn't exist, create it above the latest version heading
3. List changes as bullet points — concise, user-facing descriptions
4. Do NOT assign a version number — that happens at release time

At release time (not during normal PRs):
1. Rename `## Unreleased` to `## <version> — YYYY-MM-DD`
2. Bump `version` in `pyproject.toml` to match
3. Tag with `v<version>` to trigger the Release workflow (publishes to PyPI)

## Post-PR Checklist (MANDATORY)
After pushing a PR or merging to main:
1. Check GitHub Actions CI status with `gh run list --limit 3`
2. If any run fails, inspect with `gh run view <id> --log-failed`
3. Fix failures before moving on to other work

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

1. Ensure profiles are up-to-date in `src/estampo/data/` (release-readiness does this automatically on push to main)
2. Run `release-readiness` workflow manually to verify everything passes end-to-end
3. Update `CHANGELOG.md` — rename `## Unreleased` to `## <version> — YYYY-MM-DD`
4. Bump `version` in `pyproject.toml`
5. Commit, tag `v<version>`, push tag
6. The release workflow: runs readiness gate → builds all artifacts → publishes PyPI + Docker + cloud-bridge (nothing publishes until everything builds successfully)

**Critical**: PyPI versions are immutable. A failed release burns the version number. Always use TestPyPI first and ensure the release-readiness workflow passes before tagging.

## CI Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | PR / push to main | Lint, test (3 OS × 3 Python), coverage |
| `test-pypi.yml` | PR / push to main | Publish dev package to TestPyPI |
| `publish-docker.yml` | Push to main | Build Docker images when relevant files change |
| `publish-cloud-bridge.yml` | Tag push (`v*`) | Full release: readiness gate → build all → publish all |
| `release-readiness.yml` | Push to main / nightly / manual / workflow_call | E2e: Docker build, smoke test, profile extraction + commit, real slice |
| `slice.yml` | Manual | Run a slice with custom config |

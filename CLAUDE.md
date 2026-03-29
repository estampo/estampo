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

## Release Process

1. Run `release-readiness` workflow manually before tagging — it builds Docker images, runs smoke tests, extracts profiles, and does a real slice end-to-end
2. Update `CHANGELOG.md` — rename `## Unreleased` to `## <version> — YYYY-MM-DD`
3. Bump `version` in `pyproject.toml`
4. Commit, tag `v<version>`, push tag
5. The release workflow publishes to PyPI, builds Docker images, and opens a PR for bundled profiles

## CI Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | PR / push to main | Lint, test (3 OS × 3 Python), coverage |
| `test-pypi.yml` | PR / push to main | Publish dev package to TestPyPI |
| `publish-docker.yml` | Push to main | Build Docker images when relevant files change |
| `publish-cloud-bridge.yml` | Tag push (`v*`) | Full release: PyPI, Docker images, profile extraction |
| `release-readiness.yml` | Manual / push to main | Pre-release e2e: Docker build, smoke test, profiles, real slice |
| `slice.yml` | Manual | Run a slice with custom config |

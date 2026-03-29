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

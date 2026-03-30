# Release Process

## Changelog fragments

Every PR must include a **towncrier fragment file** in the `changes/` directory.
CI enforces this — PRs without a fragment will fail the changelog check.

Create a file named `changes/<PR-number>.<type>` where type is one of:

| Type | When to use |
|------|-------------|
| `feature` | New functionality |
| `bugfix` | Bug fix |
| `misc` | Maintenance, refactoring, CI changes |

Write a single line — concise, user-facing description:

```
changes/245.feature
```
```
Add single-command release workflow with automatic changelog generation
```

If the PR number isn't known yet, use an orphan fragment:

```
changes/+descriptive-name.bugfix
```

Do **not** edit `CHANGELOG.md` directly. Towncrier compiles fragments at release time.

## Cutting a release

### 1. Prepare

```bash
gh workflow run prepare-release.yml -f version=0.3.0
```

This creates a `release/v0.3.0` branch with:
- Version bump in `pyproject.toml`
- `CHANGELOG.md` updated by towncrier (fragments compiled and deleted)
- A PR titled "Release v0.3.0"

### 2. Review

Open the PR, review the changelog, edit if needed, then merge.

### 3. Automatic pipeline

On merge, `release.yml` detects that the merged PR came from a `release/v*`
branch and runs:

```
detect release branch (via GitHub API)
  → verify version matches pyproject.toml
  → build PyPI package (+ twine check)
  → build Docker images (estampo + cloud-bridge)
  → publish to TestPyPI (dry-run gate)
  → create git tag v0.3.0
  → publish to PyPI
  → push Docker images to Docker Hub + GHCR
  → create GitHub Release with changelog + wheel
```

The tag is only created **after** TestPyPI succeeds. If the dry-run fails,
no tag exists and no artifacts are published.

## Re-running prepare-release

If issues emerge after preparing but before merging the release PR:

1. Fix the issues via normal PRs to main (each with a changelog fragment)
2. Re-run with the same version:
   ```bash
   gh workflow run prepare-release.yml -f version=0.3.0
   ```
3. The release branch is force-updated, the existing PR is refreshed with
   the new changelog, and a comment is added

## Recovery

### TestPyPI fails

No tag was created. Fix the issue, then re-run `prepare-release` with the
same version. Merge the new PR and the pipeline runs again.

### PyPI succeeds but Docker/GitHub Release fails

Re-run manually:
```bash
gh workflow run release.yml -f tag=v0.3.0
```

PyPI publish has `skip-existing` so it won't fail on the already-published version.
The pipeline resumes from where it left off.

### Everything fails after tag creation

Same manual re-run:
```bash
gh workflow run release.yml -f tag=v0.3.0
```

Both TestPyPI and PyPI have `skip-existing` enabled.

## Setup requirements

The release workflow uses [trusted publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC). The following must be configured:

**TestPyPI** — add trusted publisher:
- Repository: `estampo/estampo`
- Workflow: `release.yml`
- Environment: `testpypi`

**PyPI** — add trusted publisher:
- Repository: `estampo/estampo`
- Workflow: `release.yml`

**GitHub** — repository secrets:
- `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` for Docker Hub publishing
- `testpypi` environment must exist (used by dry-run gate)

## CI workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | PR / push to main | Lint, type check, test (3 OS x 3 Python), coverage, towncrier check |
| `test-pypi.yml` | PR / push to main | Publish `.dev` package to TestPyPI (skips release PR merges) |
| `publish-docker.yml` | Push to main | Build Docker images when relevant files change (skips release PR merges) |
| `release.yml` | Push to main (release PR merge) / manual | Full release pipeline (see above) |
| `prepare-release.yml` | Manual | Create release PR with version bump + changelog |
| `release-readiness.yml` | Push to main / nightly / manual | E2e: Docker build, smoke test, profile extraction, real slice |
| `slice.yml` | Manual | Run a slice with custom config |

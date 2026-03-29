# Migration Plan: fabprint → estampo

**Date:** 2026-03-29
**Status:** Draft

## Overview

Rename the project from `fabprint` to `estampo` (Spanish/Portuguese for stamp/print/mold).
New users should see no trace of the old name. Existing users get a smooth transition
with deprecation warnings and a compatibility wrapper package.

### Assets already secured

| Asset | Handle |
|-------|--------|
| GitHub org | `estampo` |
| Docker Hub | `estampo` |
| Domain | `estampo.dev` (Cloudflare) |
| PyPI | **not yet registered** — claim `estampo` before starting |

---

## Phase 0: Pre-work (before any code changes)

### 0.1 Register names
- [ ] `pip install twine && twine upload` a placeholder `estampo` 0.0.1 to PyPI to claim the name
- [ ] Register `estampo` on TestPyPI
- [ ] Create `estampo/estampo` repo on GitHub (can be empty initially)
- [ ] Create Docker Hub repos: `estampo/orca-slicer`, `estampo/cloud-bridge`

### 0.2 Set up estampo.dev
- [ ] Configure Cloudflare Workers for estampo.dev
- [ ] Plan subdomain structure:
  - `estampo.dev` — landing page / docs
  - `docs.estampo.dev` — full documentation (or just `estampo.dev/docs`)
  - `api.estampo.dev` — future API if needed

### 0.3 Notify users
- [ ] GitHub Discussion / Issue announcing the rename with timeline
- [ ] Add deprecation notice to current fabprint README

---

## Phase 1: Rename the Python package

This is the core change. Everything else depends on it.

### 1.1 Directory and module rename

| Before | After |
|--------|-------|
| `src/fabprint/` | `src/estampo/` |
| `src/fabprint/__init__.py` | `src/estampo/__init__.py` |
| `src/fabprint/cli.py` | `src/estampo/cli.py` |
| `src/fabprint/config.py` | `src/estampo/config.py` |
| `src/fabprint/cloud/` | `src/estampo/cloud/` |
| ... (19 modules total) | ... |
| `tests/test_cli.py` | `tests/test_cli.py` (imports change) |
| ... (18 test files) | ... |

### 1.2 Internal references (~580 import/reference sites)

**Python source (19 files, ~163 references):**
- All `from fabprint import ...` → `from estampo import ...`
- All `import fabprint` → `import estampo`
- String references: `"fabprint"` in error messages, logger names, etc.
- Class names: `FabprintError` → `EstampoError` (with `FabprintError` kept as alias)

**Tests (18 files, ~414 references):**
- All `from fabprint ...` → `from estampo ...`
- Mock paths: `"fabprint.cli.load_config"` → `"estampo.cli.load_config"`

**Key renames:**
| Before | After | Notes |
|--------|-------|-------|
| `FabprintError` | `EstampoError` | Keep alias for one major version |
| `fabprint.toml` | `estampo.toml` | Support both, prefer new |
| `fabprint_output/` | `estampo_output/` | Support both, prefer new |
| `~/.fabprint/` | `~/.estampo/` | Auto-migrate on first run |
| `FABPRINT_*` env vars | `ESTAMPO_*` env vars | Support both, prefer new |

### 1.3 pyproject.toml

```toml
[project]
name = "estampo"
version = "0.2.0"  # continuation of the fabprint version series
description = "Reproducible 3D print builds. Define parts, slicer settings, and printer targets in code."
keywords = ["3d-printing", "bambu", "orcaslicer", "gcode", "3mf", "slicer", "pipeline", "estampo"]

[project.urls]
Homepage = "https://estampo.dev"
Repository = "https://github.com/estampo/estampo"
Issues = "https://github.com/estampo/estampo/issues"

[project.scripts]
estampo = "estampo.cli:main"
```

### 1.4 Config file compatibility

In `config.py`, add fallback loading order:
1. Look for `estampo.toml`
2. If not found, look for `fabprint.toml` (emit deprecation warning)
3. Support `ESTAMPO_*` env vars, fall back to `FABPRINT_*` with warning

### 1.5 User data migration

On first run, if `~/.fabprint/` exists but `~/.estampo/` does not:
- Copy `~/.fabprint/` → `~/.estampo/` (full copy, not symlink)
- Print one-time migration notice suggesting user delete `~/.fabprint/` once satisfied

---

## Phase 2: Publish the `fabprint` wrapper package

After `estampo` is published to PyPI, publish a final `fabprint` version that:

### 2.1 Wrapper package structure

```
fabprint-wrapper/
├── pyproject.toml
└── src/
    └── fabprint/
        ├── __init__.py    # re-exports everything from estampo
        └── cli.py         # entry point that warns and delegates
```

**`pyproject.toml`:**
```toml
[project]
name = "fabprint"
version = "0.2.0"  # bump minor to signal change
description = "DEPRECATED: fabprint has been renamed to estampo. This package is a compatibility wrapper."
dependencies = ["estampo>=0.2.0"]

[project.scripts]
fabprint = "fabprint.cli:main"
```

**`__init__.py`:**
```python
"""fabprint has been renamed to estampo. Please update your imports."""
import warnings
warnings.warn(
    "fabprint has been renamed to estampo. "
    "Please run: pip install estampo && pip uninstall fabprint. "
    "This wrapper will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)
from estampo import *  # noqa: F401,F403
from estampo import __version__  # noqa: F401
```

**`cli.py`:**
```python
"""Wrapper CLI that delegates to estampo with a deprecation warning."""
import sys
import warnings
warnings.warn(
    "The 'fabprint' command has been renamed to 'estampo'. "
    "Please update your scripts.",
    DeprecationWarning,
)
from estampo.cli import main
main()
```

### 2.2 PyPI metadata

- Set `Classifier: Development Status :: 7 - Inactive`
- Set project URL pointing to estampo
- README should explain the rename and link to estampo

---

## Phase 3: GitHub repository migration

### 3.1 Transfer repository

1. Transfer `pzfreo/fabprint` → `estampo/fabprint` (keeps all issues, PRs, stars)
2. Rename `estampo/fabprint` → `estampo/estampo`
3. GitHub auto-creates redirects for both old URLs
4. Update branch protection rules on the new repo

### 3.2 Update all GitHub URLs

~12 files with `pzfreo/fabprint` references:

| File | References |
|------|-----------|
| `pyproject.toml` | 3 URLs (Homepage, Repository, Issues) |
| `README.md` | ~8 URLs (badges, images, links) |
| `CONTRIBUTING.md` | 1 clone URL |
| `docs/developing.md` | 1 clone URL |
| `docs/code-cad.md` | 1 action reference |
| `action/action.yml` | 2 GHCR image refs |
| `action/README.md` | 2 refs (action usage, GHCR) |
| `Dockerfile.cloud-bridge` | 3 refs to `pzfreo/bnl` |
| `scripts/cache-bnl.sh` | 5 refs to `pzfreo/bnl` |

### 3.3 The `bnl` repository

`pzfreo/bnl` (Bambu networking library) is referenced in:
- `Dockerfile.cloud-bridge` (GitHub API download URLs)
- `scripts/cache-bnl.sh`

**Decision needed:** Transfer `bnl` to the `estampo` org too, or leave it under `pzfreo`?

---

## Phase 4: Docker images

### 4.1 New image names

Same structure as fabprint, just replacing the name:

| Before | After |
|--------|-------|
| `fabprint/orca-base:*` | `estampo/orca-base:*` |
| `fabprint/fabprint:orca-*` | `estampo/estampo:orca-*` |
| `fabprint/cloud-bridge:*` | `estampo/cloud-bridge:*` |
| `ghcr.io/pzfreo/fabprint:orca-*` | `ghcr.io/estampo/estampo:orca-*` |
| `ghcr.io/pzfreo/fabprint/cloud-bridge:*` | `ghcr.io/estampo/estampo/cloud-bridge:*` |
| `ghcr.io/pzfreo/fabprint/orca-base:*` | `ghcr.io/estampo/estampo/orca-base:*` |

### 4.2 Files to update (4 Dockerfiles, 3 workflows, 2 scripts)

| File | Changes |
|------|---------|
| `Dockerfile` | Image name in FROM, labels, comments, ENTRYPOINT |
| `Dockerfile.orca-base` | Labels, user/home paths (`/home/fabprint` → `/home/estampo`) |
| `Dockerfile.cloud-bridge` | Labels, comments |
| `docker-compose.yml` | Service name, image reference |
| `.github/workflows/publish-docker.yml` | Image tags, push targets |
| `.github/workflows/publish-cloud-bridge.yml` | Image tags, push targets |
| `.github/workflows/slice.yml` | Image reference |
| `scripts/build-docker.sh` | All image name/tag references (~14 sites) |

### 4.3 Transition period

- Push images to BOTH old and new names for 3 months
- Add deprecation label to old images
- After 3 months, stop publishing to old names

---

## Phase 5: GitHub Action

### 5.1 Action rename

| Before | After |
|--------|-------|
| `pzfreo/fabprint/action@main` | `estampo/estampo/action@main` |
| Action name: "Fabprint Slice" | Action name: "Estampo Slice" |

### 5.2 Files to update

**`action/action.yml` (~22 references):**
- `name: "Fabprint Slice"` → `name: "Estampo Slice"`
- Input names: `fabprint_output` → `estampo_output` (keep old as alias)
- Default config: `fabprint.toml` → `estampo.toml` (support both)
- GHCR image refs: `ghcr.io/pzfreo/fabprint:*` → `ghcr.io/estampo/estampo:*`
- PR comment markers: `<!-- fabprint-metrics -->` → `<!-- estampo-metrics -->`

**`action/README.md` (~13 references):**
- Usage examples, config references, image references

### 5.3 Backwards compatibility

- GitHub redirects `pzfreo/fabprint/action@main` → `estampo/estampo/action@main` automatically after repo transfer
- Support both `fabprint.toml` and `estampo.toml` input names for one major version

---

## Phase 6: Documentation

### 6.1 In-repo docs (~168 references across 9 files)

| File | Refs | Notes |
|------|------|-------|
| `README.md` | ~51 | Complete rewrite: new name, new URLs, new badges |
| `docs/cli.md` | ~51 | All command examples: `fabprint` → `estampo` |
| `docs/code-cad.md` | ~23 | Config examples, action references |
| `docs/init-command-plan.md` | ~24 | Module references |
| `docs/docker-optimization-plan.md` | ~22 | Docker image names |
| `docs/printers.md` | ~10 | Config and command examples |
| `docs/developing.md` | ~19 | Clone URLs, dev commands |
| `docs/config.md` | ~8 | Config file references |
| `CONTRIBUTING.md` | ~4 | Clone URL, dev commands |
| `CHANGELOG.md` | varies | Historical entries stay as-is, add rename entry |
| `CLAUDE.md` | ~5 | Update project instructions |
| `SECURITY.md` | TBD | Update if present |

### 6.2 estampo.dev website

- Landing page with logo, description, install instructions
- Redirect `estampo.dev/docs` → GitHub docs or hosted docs
- Cloudflare Workers for:
  - Landing page
  - PyPI badge proxy (optional)
  - Documentation hosting

### 6.3 Asciinema recordings

The `docs/recordings/*.cast` files contain terminal output with `fabprint` commands.
- Re-record all demos with `estampo` commands
- Files: `demo.cast`, `init.cast`, `run.cast`, `validate.cast`, `status.cast`, `status-w.cast`, `profiles-pin.cast`, `init-template.cast`

---

## Phase 7: CI/CD workflows

### 7.1 Workflow updates (5 files, ~38 references)

| Workflow | Changes |
|----------|---------|
| `ci.yml` | `mypy src/fabprint` → `mypy src/estampo` |
| `publish-docker.yml` | Image names, GHCR targets, output variable names |
| `publish-cloud-bridge.yml` | Image names, GHCR targets, data directory path |
| `test-pypi.yml` | Package name (if referenced) |
| `slice.yml` | Config input default, Docker image ref |

### 7.2 GHCR authentication

After repo transfer, GHCR pushes use `ghcr.io/${{ github.repository }}` which
auto-resolves to the new org. Verify GHCR token permissions on the `estampo` org.

### 7.3 Secrets and tokens

- [ ] Copy/recreate PyPI publish token for `estampo` org
- [ ] Copy/recreate Docker Hub token for `estampo` org
- [ ] Copy/recreate Codecov token
- [ ] Verify GITHUB_TOKEN permissions on new org

---

## Phase 8: Miscellaneous files

### 8.1 Config and ignore files

| File | Change |
|------|--------|
| `.gitignore` | `fabprint_output/` → `estampo_output/` (keep both) |
| `examples/fabprint.toml` | Rename to `estampo.toml` |
| `examples/*/fabprint.toml` | Rename to `estampo.toml` |

### 8.2 Logos

- `docs/estampo-logo.svg` — already done (B&W)
- `docs/estampo-logo-color.svg` — already done (colour)
- Remove or redirect any old logo files
- Add logo to README, PyPI, estampo.dev

### 8.3 License

- Update copyright holder if moving to org
- No change to license type (Apache 2.0)

---

## Execution order

The phases should be executed in this order to minimise breakage:

```
Phase 0  Secure names, set up infrastructure
   ↓
Phase 1  Rename Python package (src/fabprint → src/estampo)
   ↓
Phase 3  Transfer GitHub repo (pzfreo/fabprint → estampo/estampo)
   ↓
Phase 7  Update CI/CD workflows (they need new paths)
   ↓
Phase 4  Docker image migration (publish to new names)
   ↓
Phase 5  GitHub Action rename
   ↓
Phase 6  Documentation rewrite
   ↓
Phase 2  Publish fabprint wrapper (LAST — depends on estampo being live)
   ↓
Phase 8  Clean up miscellaneous files
```

### Version numbering

| Package | Version | Notes |
|---------|---------|-------|
| `estampo` | `0.2.0` | Continues the fabprint version series |
| `fabprint` (wrapper) | `0.2.0` | Minor bump, depends on `estampo>=0.2.0` |

---

## Deprecation timeline

| Date | Action |
|------|--------|
| T+0 | Publish `estampo` 0.2.0 to PyPI |
| T+0 | Publish `fabprint` 0.2.0 wrapper to PyPI |
| T+0 | Push Docker images to both old and new names |
| T+0 | GitHub repo transfer + rename |
| T+1 week | Announce on GitHub Discussions, social media |
| T+3 months | Stop publishing Docker images to old names |
| T+6 months | Publish final `fabprint` 0.3.0 that hard-errors with install instructions |
| T+12 months | Yank/abandon `fabprint` on PyPI |

---

## Risk checklist

- [ ] **PyPI name squatting**: Register `estampo` on PyPI ASAP (Phase 0)
- [ ] **Broken CI**: Transfer repo before updating workflow image refs
- [ ] **User config loss**: `~/.fabprint/` migration must be non-destructive (copy to `~/.estampo/`, suggest deletion of old dir)
- [ ] **Docker cache invalidation**: Users with `fabprint/*` in their Dockerfiles will break after old images are removed — give 3+ months notice
- [ ] **GitHub Action users**: Automatic redirect works, but users should update their workflows
- [ ] **Codecov**: May need re-linking after org transfer
- [ ] **Search engines**: Old URLs redirect via GitHub, but update sitemap on estampo.dev
- [ ] **CHANGELOG**: Add prominent entry explaining the rename at the top

---

## Total scope estimate

| Category | Files | Reference sites |
|----------|-------|----------------|
| Python source | 19 | ~163 |
| Tests | 18 | ~414 |
| Documentation | 9+ | ~168 |
| CI/Workflows | 5 | ~38 |
| Docker | 4 | ~28 |
| Scripts | 3 | ~25 |
| Action | 2 | ~35 |
| Config (pyproject, etc) | 2 | ~27 |
| **Total** | **62+** | **~900** |

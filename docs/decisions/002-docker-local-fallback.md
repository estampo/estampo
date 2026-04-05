# ADR-002: Docker-First Slicer with Local Fallback

**Status:** Accepted  
**Date:** 2026-01  

## Context

estampo users need reproducible slicing results across machines and over time. OrcaSlicer and CuraEngine versions produce different G-code; a pin-on-version-1.2.3 sliced file today should produce identical output next year. The slicer must also work inside GitHub Actions (for automated builds) and on developer machines that may or may not have Docker.

Options considered:
1. **Require Docker** — clean, reproducible, but blocks users without Docker
2. **Require local slicer install** — simplest, but not reproducible across machines/versions
3. **Docker first, fall back to local** — reproducible by default, degrades gracefully

## Decision

Use Docker as the primary slicer execution environment. Fall back to a locally installed slicer when Docker is unavailable, with a warning to the user.

## Rationale

- **Reproducibility:** Docker image tags pin the exact slicer binary. `estampo.toml` stores `version = "2.3.1"` → always uses that image → same G-code.
- **CI compatibility:** The GitHub Actions `release-readiness.yml` workflow runs *inside* a Docker container that has the slicer binary baked in. Docker-in-Docker is not available. The local fallback handles this case transparently — no special CI logic needed.
- **User experience:** Users who don't have or want Docker can still use estampo with a local slicer install. The warning makes the degradation visible.

## Implementation

- `docker_image(version)` in `slicer.py` is the **single source of truth** for image tag construction. Always use it — never construct tags manually.
- `slice_plate()` checks for Docker availability, falls back if absent or if `--local` flag set.
- `cura_docker_image(version)` in `cura.py` is the equivalent for CuraEngine.

## Consequences

- Docker images must be kept up to date when new slicer versions are released
- Image tag format is `estampo/estampo:orca-<version>` and `estampo/estampo:cura-<version>` — this format is contractual
- The local fallback means we cannot guarantee G-code reproducibility for users without Docker — this is a known trade-off
- The CI pipeline tests with the local binary (no Docker-in-Docker) — ensure tests don't depend on Docker being present

## Anti-patterns to avoid

- Do not construct Docker image tag strings by hand — always call `docker_image()` or `cura_docker_image()`
- Do not add Docker-specific logic to pipeline.py — it belongs in slicer.py / cura.py
- Do not force Docker if the slicer binary is available locally and `--local` is passed

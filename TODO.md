# Fabprint TODO

## Docker Hardening (follow-up from `harden-release-pipeline`)
- [ ] Remove mutable `orca-2.3.1` Docker tags — use only version-based immutable tags in `publish-cloud-bridge.yml`
- [ ] Review and harden Dockerfiles (`Dockerfile`, `Dockerfile.cloud-bridge`, `Dockerfile.orca-base`)
- [ ] Ensure `docker-compose.yml` references immutable image tags

## Examples
- [ ] Add pin to every example

## GIF Script
- [ ] Add pin to GIF script
- [x] Make GIF script modular with splice of cast files

## CLI Output
- [ ] Add user-facing output for every file written by the CLI

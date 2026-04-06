# estampo Roadmap

This is a living document updated at each release. It captures what's done, what's in scope for the next milestone, and what's explicitly deferred. Its purpose is to give Claude and the maintainer a shared, current understanding of project direction.

---

## v0.2.x — Done

OrcaSlicer-first foundation with full automation pipeline.

- Hamilton DAG pipeline (load → arrange → plate → slice → package → print)
- Docker-first slicer execution with local fallback
- OrcaSlicer profile system (discovery, pinning, bundled profiles)
- Multi-part 3MF assembly with bin-packing
- Multi-color support (paint color extraction from 3MF)
- Bambu printer dispatch (LAN, Cloud, Bambu Connect)
- `estampo init` wizard
- Release automation (TestPyPI gate → tag → PyPI + Docker + GHCR)

---

## v0.3.0 — In Progress (target: 2026-04)

**Theme: CuraEngine as a production-ready alternative backend.**

The goal is for a user to be able to replace `engine = "orca"` with `engine = "cura"` in their `estampo.toml` and get a comparable end-to-end experience: init wizard picks printer, slicing works, G-code stats are accurate, output is sent to printer.

### In scope

- [x] CuraEngine Docker image (built from source, v5.12.0)
- [x] CuraEngine backend in `cura.py` — invokes engine, parses output
- [x] Engine-namespaced config (`[slicer.orca]` / `[slicer.cura]`) and profile dirs
- [x] Machine definition files (`.def.json`) for Bambu P1S with proper start/end G-code
- [x] Bundled machine profiles (JSON) for nozzle/material overrides
- [x] `estampo init` wizard for CuraEngine (engine picker, machine profile picker)
- [x] CuraEngine printer definition discovery via def file manifest (PR #313)
- [x] Accurate filament weight and layer count in post-slice summary
- [ ] Printer definition pinning (squash inheritance chain for reproducible builds)
- [ ] Full CuraEngine def manifest extracted from Docker image (currently only P1S bundled)
- [ ] CI workflow for automated CuraEngine manifest extraction

### Out of scope for 0.3.0

- PrusaSlicer backend
- CuraEngine multi-extruder / AMS support
- Cloud print via CuraEngine (Bambu Connect packaging for Cura output)
- Profile editing UI

---

## v0.4.0 — Planned

**Theme: Printer-vendor agnostic pipeline. Phase 1 of the split.**

See `docs/decisions/005-vendor-agnostic-split.md` for the full rationale.  
See `docs/architecture-roadmap.md` for slicer comparison research and template details.

- Extract `bambox` as standalone library: BBL `.gcode.3mf` packaging, G-code templates, Bambu LAN/Cloud/Connect dispatch, AMS mapping, auth, credentials; `cloud/`, `auth.py`, `credentials.py`, `thumbnails.py` move here
- estampo depends on `bambox` as a package; no user-visible change
- CuraEngine → Bambu printer workflow unblocked: Cura plain G-code → `bambox` → printer
- estampo core (pipeline.py, slicer.py, cura.py, gcode.py) has zero Bambu-specific imports after this milestone

---

## v0.5.0 — Sketch

**Theme: Non-Bambu printer support and `pip install estampo[bambu]`.**

- `bambox` becomes an optional extra, not a hard dependency
- Plain G-code send path for non-Bambu printers (Prusa, Voron, etc.)
- OrcaSlicer 2.3.x stability improvements

---

## Deferred / Backlog

Ideas that have come up and are not ruled out but have no active milestone:

- PrusaSlicer backend
- Non-Bambu printer support (Prusa, Voron, etc.) via plain G-code send
- Profile merging / editing UI
- Web dashboard for build status
- Build matrix (slice the same model with multiple profiles, compare)
- STEP assembly support (multi-body assemblies as single part)

---

## Architecture North Star

Two projects, each owning one concern (see `docs/architecture-roadmap.md` for detail):

```
estampo          → pipeline orchestrator, slicer-agnostic
bambox           → BBL packaging + G-code templates + printer communication
```

Every feature decision should move toward this split, not away from it.

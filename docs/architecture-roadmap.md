# Architecture Roadmap: Slicer-Agnostic, Printer-Agnostic Pipeline

This document captures the long-term vision for estampo's architecture,
motivated by ongoing instability in OrcaSlicer's CLI mode (undocumented
behavior changes, settings ignored from `--load-settings`, segfaults in
headless mode, broken validation checks in 2.3.2+).

## North Star

**estampo is a printer-agnostic, slicer-agnostic pipeline orchestrator.**
It loads parts, arranges them onto a plate, invokes a slicer, and
extracts G-code metadata. It has no knowledge of printer vendors,
packaging formats, or print protocols.

Printer-vendor concerns (packaging, printing, auth) live in separate
external tools invoked via **command stages** — CLI commands declared in
the user's TOML config (see ADR-007).

## Current State (April 2026, v0.3.0)

estampo supports two slicer backends (OrcaSlicer and CuraEngine) and
has a working command stages framework. However, legacy Bambu-specific
code remains in several modules, pending extraction (v0.4.0).

```
estampo (pipeline + slicer backends)
    ├── OrcaSlicer (via Docker)
    ├── CuraEngine (via Docker)
    ↓ plain G-code
    ↓ command stages (user-configured CLI calls)
bambox pack                             ← external CLI tool
    ↓ .gcode.3mf
Bambu printer
```

Legacy code still in estampo (to be deleted in v0.4.0):
- `printer.py` — Bambu LAN/Cloud dispatch, `.gcode.3mf` packaging
- `auth.py`, `credentials.py`, `cloud/` — Bambu auth and bridge
- AMS flags and Bambu stage IDs in `cli.py`
- Bambu-specific defaults in `init.py` and `cura.py`

## Target Architecture (v0.4.0)

```
estampo (pipeline + slicer backends)
    ├── OrcaSlicer (via Docker)
    ├── CuraEngine (via Docker)
    ├── [future: PrusaSlicer, others]
    ↓ plain G-code + metadata
    ↓ command stages (TOML-configured CLI calls)
Any printer tool                        ← user's choice
```

estampo's modules after v0.4.0:

| Module | Responsibility |
|--------|---------------|
| `pipeline.py` | Hamilton DAG orchestration |
| `slicer.py` | Slicer dispatch (routes to engine modules) |
| `orca.py` | OrcaSlicer-specific logic |
| `cura.py` | CuraEngine-specific logic |
| `gcode.py` | G-code metadata parsing |
| `commands.py` | Command stage execution |
| `arrange.py`, `plate.py`, `loader.py`, `orient.py` | Geometry pipeline |
| `config.py`, `cli.py`, `profiles.py`, `adapters.py` | Config, CLI, profiles |

**Deleted:** `printer.py`, `auth.py`, `credentials.py`, `cloud/`,
`thumbnails.py` (BBL-specific). No Bambu Python dependencies remain.

## bambox — Standalone Bambu Lab Tool

bambox is a separate project (`estampo/bambox`) that handles all
Bambu Lab concerns. estampo integrates with it exclusively via CLI
command stages — never as a Python import.

**bambox provides:**

1. **`.gcode.3mf` packager** — takes plain G-code and produces a
   printer-ready BBL archive (ZIP structure, MD5 checksums, metadata)
2. **G-code compatibility** — translates generic slicer G-code to BBL
   firmware format (progress markers, layer notifications, header block)
3. **CuraEngine printer definitions** — `bambox_p1s.def.json` with native
   start/end G-code for Bambu printers (no post-processing required)

**Integration point:**
```toml
[pack]
command = "bambox pack {sliced_dir}/plate.gcode -o {output_dir}/plate.gcode.3mf"
output = "{output_dir}/plate.gcode.3mf"
```

## Slicer Comparison

Research conducted April 2026 on PrusaSlicer, CuraEngine, and KiriMoto
as potential OrcaSlicer alternatives:

| | OrcaSlicer | CuraEngine | PrusaSlicer | KiriMoto |
|---|---|---|---|---|
| BBL 3MF output | Yes | No | No | Yes |
| BBL profiles | Full | None | None | Partial (P1S, A1) |
| CLI stability | Poor | Excellent | Poor | Fragile |
| Headless | Hacky (needs X11 shims) | Native | Yes | Node.js CLI |
| Slice quality | High | High | High | Medium |
| License | AGPL-3.0 | AGPL-3.0 | AGPL-3.0 | MIT |
| Active dev | Yes | Yes (UltiMaker) | Yes (Prusa) | Solo maintainer |

**CuraEngine** is the strongest second backend — purpose-built headless
CLI, stable, actively maintained. The missing pieces (BBL profiles, 3MF
packaging) are handled by `bambox`.

## Migration Phases

### Phase 1: Multi-engine support (DONE — v0.3.0)
- CuraEngine added as second slicer backend
- Slicer plugin protocol (ADR-006) established
- Command stages framework (ADR-007) implemented
- bambox extracted as standalone package

### Phase 2: Vendor-agnostic estampo (IN PROGRESS — v0.4.0)
- Delete all Bambu-specific code from estampo (see ADR-005)
- Remove Bambu Python dependencies
- Printing/packaging becomes command stages only
- Tracked by issues #370, #373, #374, #375, #377, #378, #387

### Phase 3: Ecosystem expansion (FUTURE)
- PrusaSlicer as third engine (#351)
- BambuStudio headless spike (#352)
- Additional printer vendor tools (community-driven)
- Each new printer vendor = a new external CLI tool, not estampo code

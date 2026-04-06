# Architecture Roadmap: Slicer-Agnostic Printing

This document captures the long-term vision for estampo's architecture,
motivated by ongoing instability in OrcaSlicer's CLI mode (undocumented
behavior changes, settings ignored from `--load-settings`, segfaults in
headless mode, broken validation checks in 2.3.2+).

## Current State

Estampo is tightly coupled to OrcaSlicer:

```
estampo (pipeline) → OrcaSlicer CLI (slicing + 3MF packaging) → Bambu Connect → Printer
```

OrcaSlicer handles three distinct responsibilities:
1. **Slicing** — toolpath generation from 3D models
2. **BBL G-code** — printer-specific start/end/toolchange macros
3. **Packaging** — `.gcode.3mf` archive format for BBL printers

This coupling means every OrcaSlicer CLI bug blocks the entire pipeline.

## Target Architecture

Two projects, each owning one concern:

```
estampo (pipeline + slicer backends)
    ↓ G-code
bambox (packaging + G-code templates + printer communication)
    ↓ .gcode.3mf → MQTT/FTP
Bambu printer
```

### estampo — Pipeline Orchestrator

What it does today, minus the OrcaSlicer lock-in:
- Plate arrangement, profile management, build automation
- Slicer-agnostic: pluggable backends (OrcaSlicer, CuraEngine, others)
- Delegates all BBL-specific concerns to `bambox`
- Could target non-BBL printers (Prusa, Voron, etc.) in the future

### bambox — BBL Packaging, Templates & Printing

Three responsibilities:

**1. `.gcode.3mf` packager** — takes plain G-code and produces a
printer-ready BBL archive:
- ZIP structure with required metadata files
- MD5 checksums (validated by firmware)
- `model_settings.config`, `slice_info.config`, `project_settings.config`
- Thumbnail placeholders
- Pure Python, no dependencies beyond stdlib (`zipfile`, `hashlib`)
- ~200-300 lines for the core packager

See [gcode-3mf-format.md](gcode-3mf-format.md) for the full format
specification we've already documented.

**2. BBL G-code template library** — Jinja2-based rendering of
printer-specific G-code macros:
- Start G-code (bed leveling, nozzle wipe, AMS init, vibration cal)
- End G-code (cooldown, retract, park)
- Tool change G-code (AMS filament swap, purge, wipe)
- Layer change G-code (timelapse support)
- Per-printer-model templates (P1S, X1C, A1, etc.)

Source material for templates:
- **KiriMoto** (`Bambu.P1S.json`, `Bambu.A1.json`) — MIT licensed,
  complete start/end/toolchange with AMS support, JSON format
- **BambuStudio** (`resources/profiles/BBL/machine/`) — Apache-2.0,
  canonical templates with OrcaSlicer variable syntax
- **OpenBambuAPI** (`gcode.md`) — reverse-engineered M-code reference
  for proprietary commands (M620/M621, M975, M1002, etc.)

Template engine: **Jinja2** — proven for G-code templating by both Klipper
and OctoPrint. OrcaSlicer's custom template syntax maps almost 1:1:

| OrcaSlicer | Jinja2 |
|---|---|
| `{bed_temperature}` | `{{ bed_temperature }}` |
| `{filament_type[0]}` | `{{ filament_type[0] }}` |
| `{if cond}...{endif}` | `{% if cond %}...{% endif %}` |

A thin translator (~50 lines of regex) can convert existing OrcaSlicer
templates to Jinja2 format.

**3. Printer communication** — wraps the Docker-based Bambu Network
Library (BNL) bridge:
- Estampo already uses Docker for slicing; same pattern for printing
- BNL `.so` is preserved in the Docker image (insurance against Bambu
  pulling it)
- Handles LAN and cloud printing workflows
- Printer discovery, status monitoring, job management
- AMS filament slot mapping
- Bambu Cloud authentication

**Why not replace BNL?** Repeated attempts to reverse-engineer the Bambu
cloud protocol have failed. The BNL `.so` is the only reliable path for
cloud printing. LAN printing via raw MQTT/FTP is possible (and KiriMoto
demonstrates it) but cloud printing requires BNL.

## What This Unlocks

**For estampo users:**
- Slicer choice: CuraEngine for stability, OrcaSlicer for BBL profiles
- No more fighting OrcaSlicer CLI bugs for non-slicing concerns
- Faster iteration — slicer upgrades don't break packaging/printing

**For the broader community:**
- `bambox` is useful standalone (anyone using CuraEngine + BBL printer, Home Assistant, custom dashboards)
- Each project is small, focused, and independently testable

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

**CuraEngine** is the strongest candidate for a second backend:
- Purpose-built headless CLI, stable, actively maintained
- JSON-based settings with ~1200 parameters
- The missing pieces (BBL profiles, 3MF packaging) are exactly what
  `bambox` would provide

**PrusaSlicer** is not viable — cannot produce `.gcode.3mf` and has no
BBL profile ecosystem.

**KiriMoto** is interesting for reference (MIT-licensed BBL templates,
Bambu MQTT integration) but the slicer itself lacks features and the CLI
is not production-grade.

## Migration Path

This is not a rewrite — it's a gradual decoupling:

1. **Now**: Keep OrcaSlicer as the only backend. Pin stable versions,
   work around CLI bugs with overrides and retries.
2. **Phase 1**: Extract `bambox` as a library. Estampo already
   post-processes OrcaSlicer's 3MF output — formalize packaging,
   printing, and auth into a standalone package.
3. **Phase 2**: Add CuraEngine as a second slicer backend. Use
   `bambox` for packaging and G-code template injection.

Each phase is independently useful and shippable. No big bang migration
required.

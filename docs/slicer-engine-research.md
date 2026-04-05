# Slicer Engine Research: Bambu P1S Multi-Material Support

**Date:** 2026-04-05
**Status:** Research / RFC
**Related:** ADR-003 (multi-engine facade), ADR-006 (slicer plugin protocol)

## Problem Statement

estampo needs reliable, headless slicing for Bambu Lab P1S printers with AMS
(Automatic Material System) multi-filament support. No current engine delivers
this cleanly:

| Engine | Headless | P1S native | AMS / multi-filament | Status in estampo |
|--------|----------|------------|---------------------|-------------------|
| OrcaSlicer | Fragile (GUI app, CLI bolted on) | Yes | Yes | Primary engine, unreliable in 2.3.2+ |
| BambuStudio | Fragile (same codebase) | Yes | Yes | Attempted, abandoned |
| CuraEngine | Solid (CLI-native) | Hacked | No | Second engine, single-filament only |
| PrusaSlicer | Good (documented CLI) | Community profiles | Partial (MMU2 model) | Not integrated |
| Kiri:Moto | Excellent (Node.js, no GUI deps) | None | No | Not integrated |

The core tension: slicers that understand Bambu printers (OrcaSlicer,
BambuStudio) are unreliable headless. Slicers that are reliable headless
(CuraEngine, Kiri:Moto) don't understand Bambu printers.

## Current State

### OrcaSlicer (engine = "orca")

- Works under 2.3.1 in Docker; fails or behaves unpredictably under 2.3.2+
- Produces print-ready `.gcode.3mf` with full AMS support, correct start/end
  G-code, wipe tower, purge sequences
- Only slicer that natively generates Bambu-proprietary M-codes (M620/M621
  for AMS, M975 vibration suppression, M960 LEDs, etc.)
- Headless reliability is the blocker, not capability

### CuraEngine (engine = "cura")

- Rock-solid headless: proper CLI, no GUI dependencies, well-tested
- estampo maintains custom `bambulab_p1s.def.json` and `bambulab_base.def.json`
  (inheriting from `fdmprinter`)
- **Single-filament only** — `machine_extruder_count: 1`, no AMS awareness
- Start/end G-code is a ~150-line blob embedded in `.def.json` with template
  variables (`{material_bed_temperature_layer_0}`, etc.) that CuraEngine passes
  through unresolved
- estampo post-processes with `_substitute_gcode_templates()` using Python
  `eval()` — only handles 4 temperature variables and 1 conditional
- Many template variables in the start G-code go unsubstituted (filament type
  conditionals, volumetric speed, AMS slot selection)

### bambox (packaging library)

- Has richer P1S start/end G-code as Jinja2 templates (270 lines, full AMS
  handling, nozzle wash, bed leveling, vibration suppression)
- Has `build_project_settings()` for 544-key `project_settings.config`
- Has `gcode_compat.py` for translating slicer G-code to BBL firmware format
  (layer markers, progress commands)
- **Not used by estampo** — zero imports, zero dependency
- The CLI only does bare-bones packing; the rich template/settings path is
  API-only and was used in an ad-hoc session to produce a successful print

## Analysis of CuraEngine Multi-Material Support

### How CuraEngine handles multi-filament natively

CuraEngine's multi-material model assumes **IDEX** (Independent Dual Extrusion) —
two or more physical nozzles with XY offsets. Each extruder is a separate
`.def.json` with `machine_nozzle_offset_x/y`. CuraEngine natively generates:

- `Tn` tool change commands
- Prime tower geometry
- Retraction/priming at tool changes
- Travel avoidance between extruders

**Example: Ultimaker 3** (native dual-extruder, CuraEngine's "happy place")

- `machine_start_gcode: ""` — empty, firmware handles init
- `machine_end_gcode`: 3 lines
- `machine_gcode_flavor: "Griffin"` — Ultimaker's own protocol
- Two extruder definitions with physical offsets (18mm X offset)
- `switch_extruder_retraction_amount`, `prime_tower_enable`, etc.
- No template variables, no post-processing needed

### The Anycubic ACE PRO pattern

The **Anycubic Kobra 3 v2 ACE PRO** is a single-nozzle printer with a
multi-filament unit (conceptually identical to Bambu AMS). CuraEngine supports
it by:

1. Declaring **4 fake extruders** with identical nozzle size, zero XY offset
2. `machine_extruder_count: 4`
3. CuraEngine generates `T0`/`T1`/`T2`/`T3` commands and prime towers
4. The **printer firmware** intercepts T-commands and handles filament switching
5. Start/end G-code is minimal — firmware does the heavy lifting

This is the closest precedent for how we'd add AMS support to CuraEngine.

### Why the P1S is harder than the ACE PRO

- Anycubic firmware natively understands CuraEngine T-commands. Bambu firmware
  expects proprietary `M620`/`M621` sequences.
- Bambu's start G-code requires dozens of proprietary M-codes: `M710` (board
  fan), `M960` (LEDs), `M975` (vibration suppression), `M1002` (claim actions),
  `M620`/`M621` (AMS), `G380` (bed movements), `G29.1`/`G29.2` (ABL control).
- Material-dependent behavior: PLA enables part cooling fan in start sequence,
  non-PLA doesn't. Textured PEI plate adds a Z-offset. These conditionals
  are in the start G-code template.
- CuraEngine's start/end G-code is a static string in `.def.json` — it has no
  awareness of which filament is loaded, which AMS slot is active, or what
  material transitions are happening.

## Candidate Engines

### PrusaSlicer

**Strengths:**
- Proper, documented CLI: `prusa-slicer --export-gcode --load config.ini model.stl`
- Built-in **Single Extruder Multi Material** mode for MMU2 — single-nozzle
  multi-filament, conceptually identical to AMS
- Generates T-commands, wipe tower, filament ramming, purge sequences natively
- Large community, actively maintained by Prusa (a hardware company with
  reliability incentives)
- ADR-006 already anticipates `prusa.py` as a third engine module

**Weaknesses:**
- Recent versions depend on WebKit; moving to Flatpak distribution. Headless
  Docker packaging is getting harder, not easier.
- No official Bambu P1S profile — community profiles exist but are reported as
  unreliable ("spaghetti prints")
- Known bug: custom tool change G-code is ignored when wipe tower is enabled
  ([prusa3d/PrusaSlicer#1245](https://github.com/prusa3d/PrusaSlicer/issues/1245)) —
  this is exactly the configuration needed for AMS
- No one in the community appears to be running PrusaSlicer + Bambu AMS
  successfully

**Verdict:** Promising for multi-material due to MMU2 support, but the tool
change G-code bug and containerisation difficulty are serious blockers.

### Kiri:Moto

**Strengths:**
- Written in JavaScript/Node.js — truly headless by design, no GUI dependencies
- CLI: `node src/kiri-run/cli --model part.stl --device printer.json --output out.gcode`
- Custom printer definitions via JSON
- Trivial to containerise
- Actively maintained since 2013
- MIT license

**Weaknesses:**
- **No multi-material support** for FDM printing (tool changes exist for CNC only)
- Much smaller community — fewer profiles, less battle-tested print quality
- Missing advanced features: no adaptive layer height, no organic supports,
  limited infill patterns compared to PrusaSlicer/CuraEngine
- No Bambu printer definitions exist

**Verdict:** Best headless ergonomics of any slicer, but the lack of
multi-material support is a dealbreaker for AMS. Could be a viable engine for
simple single-filament jobs where reliability is paramount.

## The Post-Processing Question

All roads lead to post-processing. No open-source slicer except
OrcaSlicer/BambuStudio natively speaks Bambu's AMS protocol. Every alternative
requires a translation layer:

1. **T-command to M620/M621 translation** — map generic tool changes to AMS
   filament switching sequences
2. **Start/end G-code injection** — replace slicer-generated init/shutdown with
   P1S-specific sequences (motor current, AMS, nozzle wash, bed leveling,
   vibration suppression)
3. **Wipe tower / purge handling** — this is the hard part

### Wipe tower complexity

The wipe tower is where slicer and post-processing boundaries get blurry:

- **Geometry generation** must happen during slicing — the tower is a physical
  object that the toolpath must navigate around
- **Purge volumes** are material-pair-dependent (e.g., dark-to-light needs more
  purging than light-to-dark) — the slicer must plan these during toolpath
  generation
- **Flush sequences** (ramming, tip-shaping) are tuned per material — the
  slicer generates specific extrusion patterns

PrusaSlicer and CuraEngine both generate wipe towers natively — the geometry
and purge volumes come from the slicer. What post-processing would need to
replace is only the T-command itself (the actual filament swap), not the
surrounding tower geometry.

This makes the post-processing layer thinner than initially feared:
- Keep the slicer's wipe tower geometry and purge extrusions
- Replace `Tn` commands with M620/M621 AMS sequences
- Inject Bambu-specific temperature management around tool changes

## Decision: CuraEngine + bambox Post-Processing

After evaluating the options, the chosen path is:

**CuraEngine as the primary slicer, with bambox handling Bambu-specific
post-processing and packaging.**

Other users of estampo can use CuraEngine natively with their own printers —
no post-processing needed. The Bambu-specific path only activates when
targeting a Bambu printer.

### Architecture

```
estampo → CuraEngine → raw G-code (print-ready for native Cura printers)
                            ↓ (Bambu printers only)
                        bambox post-process (T→AMS, start/end injection)
                            ↓
                        bambox pack (.gcode.3mf)
                            ↓
                        bambox print (cloud bridge)
```

### Separation of concerns

- **estampo** produces G-code from models via CuraEngine. The CuraEngine
  `.def.json` definitions use minimal start/end G-code — just enough for
  CuraEngine to produce valid output. For non-Bambu printers, CuraEngine
  definitions contain the real start/end G-code as usual and output is
  print-ready with no post-processing.

- **bambox** owns all Bambu-specific logic:
  - Post-processes CuraEngine G-code: replaces `Tn` tool changes with
    `M620`/`M621` AMS sequences, injects temperature management
  - Injects real P1S start/end G-code (from Jinja2 templates, replacing
    the minimal stubs from CuraEngine)
  - Translates slicer layer markers to BBL firmware format (existing
    `gcode_compat.py`)
  - Packages into `.gcode.3mf` with settings, thumbnails, checksums
  - Sends to printer via cloud bridge

- **Neither project depends on the other at the Python level.** estampo
  invokes bambox as a CLI tool or subprocess, not as an imported library.

### Implementation plan

#### Phase 1: CuraEngine multi-filament (estampo)

1. Add 4 fake extruder definitions to `bambulab_p1s.def.json` following the
   Anycubic ACE PRO pattern (4 extruders, identical nozzle, zero XY offset)
2. Set `machine_extruder_count: 4` in the P1S definition
3. Use minimal start/end G-code in the `.def.json` — basic homing, temp
   setting, and a marker comment that bambox can recognise
4. CuraEngine now generates T-commands and prime towers natively
5. Validate: single-filament prints should still work (T0 only, bambox
   post-processes as before)

#### Phase 2: T-command post-processor (bambox)

1. Add a `bbl_postprocess` module to bambox that:
   - Detects `Tn` tool change commands in G-code
   - Replaces each with the appropriate M620/M621 AMS sequence
   - Injects nozzle temperature management around tool changes
     (heat new filament, cool old)
   - Handles the initial tool load (T0 at start)
2. Extend `gcode_compat.py` or create a new entry point that chains:
   slicer detection → layer marker injection → T-command rewriting →
   start/end injection
3. Wire into bambox CLI: `bambox pack` gains a `--bbl-postprocess` flag
   (or auto-detects when targeting a Bambu printer)

#### Phase 3: Start/end G-code injection (bambox)

1. bambox already has P1S start/end Jinja2 templates (270-line start,
   55-line end, 189-line toolchange) — these are the real sequences with
   AMS handling, nozzle wash, vibration suppression, bed leveling
2. The post-processor strips CuraEngine's minimal start/end stubs and
   replaces with rendered Jinja2 templates
3. Template context (bed temp, nozzle temp, filament type, bed plate type)
   comes from the `.gcode.3mf` packaging metadata or CLI flags

#### Phase 4: estampo integration

1. estampo's slicer dispatch calls CuraEngine as today
2. For Bambu printer targets, estampo invokes bambox CLI to post-process
   and package: `bambox pack --bbl-postprocess input.gcode -o output.gcode.3mf`
3. For non-Bambu targets, CuraEngine output is used directly — no bambox
   involvement

### What this does NOT change

- **OrcaSlicer remains available** as a fallback engine in estampo for users
  who prefer it. Its output is already print-ready and bypasses bambox
  post-processing.
- **CuraEngine definitions for non-Bambu printers** are unaffected. They
  continue to contain full start/end G-code and produce print-ready output.
- **bambox's existing gcode_compat.py** continues to work for G-code from
  any slicer — the T-command rewriting is an additional step, not a
  replacement.

### PrusaSlicer and Kiri:Moto

PrusaSlicer remains a candidate for future evaluation per ADR-006. Its MMU2
mode may produce cleaner multi-material output than CuraEngine's fake-IDEX
approach, but the tool change G-code bug
([#1245](https://github.com/prusa3d/PrusaSlicer/issues/1245)) and
containerisation difficulty need to be resolved first.

Kiri:Moto is a candidate for simple single-filament jobs where headless
reliability is paramount, but its lack of multi-material support rules it
out for AMS workflows.

## Open Questions

1. **Does Bambu firmware handle T-commands at all?** If the firmware intercepts
   `T0`/`T1` like the Anycubic does, the post-processing layer becomes trivial.
   This needs testing on a real P1S with AMS.

2. **What should the minimal start/end G-code in the `.def.json` look like?**
   It needs to be enough for CuraEngine to produce valid G-code, but
   recognisable by bambox so it can be stripped and replaced. A marker comment
   like `; ESTAMPO_MINIMAL_START` / `; ESTAMPO_MINIMAL_END` would work.

3. **How does estampo invoke bambox?** Options: CLI subprocess
   (`bambox pack ...`), Python API import, or writing G-code to a known
   location and letting a separate step handle it. CLI subprocess maintains
   the cleanest boundary.

4. **Is the eval() hack in cura.py a security concern?** It runs `eval()` on
   strings derived from `.def.json` files. These are trusted files today, but
   if estampo ever accepts user-provided definitions, this becomes an injection
   vector. With bambox handling template substitution via Jinja2, estampo's
   `_substitute_gcode_templates()` can be simplified or removed for Bambu
   targets.

5. **Purge volume tuning.** CuraEngine's prime tower handles purge geometry,
   but the purge volumes per material pair may need tuning. OrcaSlicer has
   a flushing volume matrix per filament pair — CuraEngine's model is simpler.
   This may affect print quality for multi-colour prints and needs testing.

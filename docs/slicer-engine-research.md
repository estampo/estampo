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

## Recommended Path Forward

### Short term: stabilise OrcaSlicer 2.3.1

- Pin to OrcaSlicer 2.3.1 in Docker, do not upgrade
- Add crash detection and retry logic in estampo's slicer dispatch
- This is the only path that works for AMS multi-filament today

### Medium term: CuraEngine multi-filament via Anycubic pattern

1. Add 4 fake extruder definitions to `bambulab_p1s.def.json` (following the
   Anycubic ACE PRO pattern)
2. CuraEngine generates T-commands and prime towers natively
3. Build a post-processor (in bambox or estampo) that translates:
   - `Tn` → `M620 S{n}A` / `M621 S{n}A` AMS sequences
   - Inject temperature management around tool changes
4. Fix the start/end G-code template substitution — either:
   - Use Jinja2 properly (bambox already has this), or
   - Expand `_substitute_gcode_templates()` to handle all variables

### Medium term: evaluate PrusaSlicer

- Investigate whether the tool change G-code bug (#1245) is fixed in recent
  versions
- Test headless Docker packaging with current PrusaSlicer releases
- If viable, implement `prusa.py` per ADR-006 protocol
- PrusaSlicer's MMU2 mode may produce cleaner multi-material output than
  CuraEngine's fake-IDEX approach

### Long term: slicer-agnostic post-processing in bambox

- bambox already has `gcode_compat.py` for translating layer markers
- Extend this to handle T-command → AMS translation
- bambox becomes the single place that understands "generic slicer G-code →
  Bambu-ready G-code"
- estampo remains slicer-agnostic; bambox remains slicer-agnostic but
  printer-aware

### Principle: clean separation

- **estampo** produces G-code from models (slicer-agnostic, printer-agnostic)
- **bambox** translates G-code for Bambu printers (slicer-agnostic, Bambu-specific)
- Post-processing for Bambu lives in bambox, not estampo
- Slicer invocation lives in estampo, not bambox

## Open Questions

1. **Does Bambu firmware handle T-commands at all?** If the firmware intercepts
   `T0`/`T1` like the Anycubic does, the post-processing layer becomes trivial.
   This needs testing on a real P1S with AMS.

2. **Can we strip start/end G-code from CuraEngine output?** If estampo tells
   CuraEngine to use minimal start/end G-code and bambox injects the real
   sequences, we avoid the template substitution problem entirely. But this
   means estampo's CuraEngine output is not print-ready for non-Bambu printers.

3. **Should bambox depend on estampo or vice versa?** Currently neither depends
   on the other. The post-processing layer needs to live somewhere — probably
   bambox, since it's Bambu-specific.

4. **Is the eval() hack in cura.py a security concern?** It runs `eval()` on
   strings derived from `.def.json` files. These are trusted files today, but
   if estampo ever accepts user-provided definitions, this becomes an injection
   vector. Replacing with Jinja2 would fix this.

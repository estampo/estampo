# ADR-005: Vendor-Agnostic estampo via bambox Extraction

**Status:** Accepted — migration in progress  
**Date:** 2026-04 (revised 2026-04-11)  

## Context

estampo is currently coupled to Bambu Lab printers at two points:

1. **Packaging** — `printer.py` and `slicer.py` produce `.gcode.3mf` archives in the BBL format (specific ZIP structure, MD5 checksums, proprietary metadata files)
2. **Printer communication** — `printer.py` dispatches print jobs via Bambu LAN API, Bambu Cloud API, and the Bambu Connect bridge (which wraps the proprietary BNL `.so` library)

This means a user with a Prusa, Voron, or any non-Bambu printer cannot use estampo. It also means OrcaSlicer CLI bugs (which are common and severe) block the entire pipeline, because OrcaSlicer is doing packaging and G-code injection as well as slicing.

The slicer comparison research (in `docs/architecture-roadmap.md`) confirmed that CuraEngine has excellent CLI stability but no BBL output. To use CuraEngine with a Bambu printer, estampo must own the packaging step itself.

## Decision

**estampo is printer-agnostic.** It has no knowledge of printer vendors, protocols, or packaging formats. Its job ends at G-code output.

All printer-vendor concerns live in separate, external tools:

- **`bambox`** — Bambu Lab packaging, G-code templates, cloud/LAN printing, AMS mapping, and authentication

estampo integrates with bambox (and any other printer tool) exclusively through **command stages** (ADR-007) — external CLI commands declared in the user's TOML config. estampo never imports bambox as a Python library.

```
estampo (pipeline + slicer backends)
    ↓ plain G-code
    ↓ command stages (TOML-configured CLI calls)
bambox pack / bambox print            ← external CLI, user-configured
    ↓ .gcode.3mf → MQTT/FTP
Bambu printer
```

Example user TOML:
```toml
[pack]
command = "bambox pack {sliced_dir}/plate.gcode -o {output_dir}/plate.gcode.3mf"
output = "{output_dir}/plate.gcode.3mf"

[print]
command = "bambox print {output_dir}/plate.gcode.3mf --serial YOUR_SERIAL"
```

For non-Bambu printers, users configure different command stages (or none — just take the G-code).

## Rationale

**Decoupling slicer from packaging:** OrcaSlicer currently handles slicing, BBL G-code injection, and `.gcode.3mf` packaging in one binary. Any CLI bug in OrcaSlicer blocks all three. With bambox as a separate CLI, estampo can swap slicers (OrcaSlicer → CuraEngine) without losing BBL printer support.

**CLI-only integration:** bambox is a Rust+Python tool with its own release cadence, FFI dependencies (BNL bridge), and build toolchain. A Python import would couple estampo's version constraints to bambox's internals. CLI integration via command stages (ADR-007) keeps both projects independently versioned and deployable.

**Community value:** `bambox` is useful to anyone with a Bambu printer, regardless of which slicer or pipeline they use. It is independently installable (`pip install bambox` / `pipx install bambox`).

**Scope clarity for estampo:** estampo's job is clear and finite: load parts, arrange, plate, invoke slicer, extract G-code metadata. It has no knowledge of printer vendors, packaging formats, or print protocols.

## What stays in estampo

- `pipeline.py` — DAG orchestration
- `slicer.py` — slicer dispatch (OrcaSlicer / CuraEngine)
- `orca.py` — OrcaSlicer-specific logic (including OrcaSlicer 3MF painting metadata)
- `cura.py` — CuraEngine-specific logic (printer-agnostic)
- `gcode.py` — G-code metadata parsing (print time, filament weight — engine-agnostic)
- `commands.py` — command stage execution (generic, not printer-aware)
- `arrange.py`, `plate.py`, `loader.py`, `orient.py` — geometry pipeline
- `config.py`, `cli.py`, `profiles.py`, `adapters.py`

## What gets deleted from estampo

These modules and functions are **deleted entirely** — not moved, not wrapped, not shimmed. bambox already provides all replacements as CLI commands.

| Delete from estampo | bambox replacement | Tracking issue |
|---|---|---|
| `printer.py` (entire module) | `bambox pack`, `bambox print` | #370 |
| `auth.py` (entire module) | `bambox` handles its own auth | #370 |
| `credentials.py` (entire module) | `bambox` handles its own credentials | #370 |
| `cloud/` directory (bridge, ams) | `bambox bridge`, `bambox print` | #370 |
| `cli.py`: `_PRINT_STAGES`, AMS flags, printer status rendering | `bambox status`, `bambox print` | #375 |
| `cli.py`: `--no-ams-mapping`, bambu-cloud serial discovery | `bambox print` flags | #375 |
| `cura.py`: `_substitute_gcode_templates()`, `_patch_gcode_header()` | `bambox pack` (auto-configures from BAMBOX headers) | #387 |
| `cura.py`: bundled `bambulab_p1s.def.json`, `bambulab_base.def.json` | bambox ships its own CuraEngine definitions | #387 |
| `cura.py`: default to `"bambulab_p1s"` when no printer specified | Error if no printer specified | #374 |
| `init.py`: Bambu P1S defaults in prompts and template | Generic prompts, profile picker | #373 |
| `plate.py`: `BambuStudio:MmPaintingVersion`, `_encode_paint_color()` | Moves to `orca.py` (OrcaSlicer-specific, not printer-specific) | #378 |
| `constants.py`: Bambu-specific comments | Generic wording | #377 |
| `pyproject.toml`: `bambulabs-api`, `bambu-lab-cloud-api` dependencies | Not needed — bambox is a CLI tool, not a Python dependency | #370 |

## Migration path

Gradual decoupling — no big bang rewrite. Each phase is independently shippable.

**Phase 1 — Quick wins (no bambox changes needed):**
- #377: Reword Bambu-specific comments in `constants.py`
- #373: Remove Bambu defaults from `init.py` prompts
- #374: Remove Bambu defaults from `cura.py`, error on missing printer

**Phase 2 — Delete Bambu code from estampo:**
- #378: Move BambuStudio 3MF painting metadata from `plate.py` to `orca.py`
- #387: Delete bundled Bambu CuraEngine definitions and post-processing functions
- #375: Delete AMS CLI flags, Bambu stage IDs, printer status rendering from `cli.py`
- #370: Delete `printer.py`, `auth.py`, `credentials.py`, `cloud/` — remove Bambu dependencies from `pyproject.toml`

**v0.4.0 gate:** After all phases complete, estampo has zero Bambu-specific code, zero Bambu Python dependencies, and zero knowledge of printer vendors. Users configure packaging and printing via command stages in TOML.

## Consequences

- `printer.py`, `auth.py`, `credentials.py`, `cloud/` are deleted
- `bambulabs-api` and `bambu-lab-cloud-api` are removed from dependencies
- estampo's `print` and `status` CLI subcommands are removed (users use `bambox print` / `bambox status`)
- `plate.py` becomes a pure geometry assembler; OrcaSlicer-specific 3MF metadata moves to `orca.py`
- Adding support for a new printer vendor requires zero changes to estampo — users just configure a different command stage

## Anti-patterns to avoid

- **Do not import bambox** as a Python library. Integration is CLI-only via command stages (ADR-007).
- Do not add new Bambu-specific logic to any estampo module.
- Do not create "thin dispatch shims" or "wrapper functions" for bambox — that's still coupling.
- Do not add printer-vendor modules (`prusa.py`, `voron.py`) to estampo — printer-vendor code belongs in vendor-specific packages.
- Do not add OrcaSlicer-specific packaging logic assuming it will always be the slicer — CuraEngine output must go through the same packaging path (command stages).

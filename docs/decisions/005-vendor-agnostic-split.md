# ADR-005: Vendor-Agnostic estampo via bambu-3mf and bambu-cloud Split

**Status:** Accepted — migration in progress  
**Date:** 2026-04  

## Context

estampo is currently coupled to Bambu Lab printers at two points:

1. **Packaging** — `printer.py` and `slicer.py` produce `.gcode.3mf` archives in the BBL format (specific ZIP structure, MD5 checksums, proprietary metadata files)
2. **Printer communication** — `printer.py` dispatches print jobs via Bambu LAN API, Bambu Cloud API, and the Bambu Connect bridge (which wraps the proprietary BNL `.so` library)

This means a user with a Prusa, Voron, or any non-Bambu printer cannot use estampo. It also means OrcaSlicer CLI bugs (which are common and severe) block the entire pipeline, because OrcaSlicer is doing packaging and G-code injection as well as slicing.

The slicer comparison research (in `docs/architecture-roadmap.md`) confirmed that CuraEngine has excellent CLI stability but no BBL output. To use CuraEngine with a Bambu printer, estampo must own the packaging step itself.

## Decision

Split Bambu-specific concerns into two separate packages:

- **`bambu-3mf`** — standalone Python library for BBL packaging and G-code templates
- **`bambu-cloud`** — standalone Python library for Bambu printer communication

estampo becomes a **printer-vendor-agnostic pipeline orchestrator**. It produces plain G-code and delegates packaging and dispatch to pluggable backends.

```
estampo (pipeline + slicer backends)
    ↓ plain G-code
bambu-3mf (packaging + G-code templates)   ← optional, Bambu-specific
    ↓ .gcode.3mf
bambu-cloud (printer communication)        ← optional, Bambu-specific
    ↓ MQTT/FTP
Bambu printer
```

For non-Bambu printers, estampo sends plain G-code directly — no BBL packaging needed.

## Rationale

**Decoupling slicer from packaging:** OrcaSlicer currently handles slicing, BBL G-code injection, and `.gcode.3mf` packaging in one binary. Any CLI bug in OrcaSlicer blocks all three. If estampo owns packaging independently, it can swap slicers (OrcaSlicer → CuraEngine) without losing BBL printer support.

**Community value:** `bambu-3mf` and `bambu-cloud` are useful to anyone with a Bambu printer, regardless of which slicer or pipeline they use. Splitting them out makes them independently installable and testable.

**Scope clarity for estampo:** Once the split is done, estampo's job is clear and finite: load parts, arrange, plate, invoke slicer, hand off G-code. It has no knowledge of printer vendors.

## What moves where

### Stays in estampo

- `pipeline.py` — DAG orchestration
- `slicer.py` — OrcaSlicer invocation
- `cura.py` — CuraEngine invocation
- `gcode.py` — G-code metadata parsing (print time, filament weight — engine-agnostic)
- `arrange.py`, `plate.py`, `loader.py`, `orient.py` — geometry pipeline
- `config.py`, `cli.py`, `profiles.py`, `adapters.py`
- `credentials.py` — printer credential loading (stays for now; `bambu-cloud` will eventually own its own credential format)

### Moves to `bambu-3mf`

- `.gcode.3mf` packaging (currently in `printer.py` → `wrap_gcode_3mf()`)
- BBL G-code template library (start/end/toolchange/layer-change macros)
- The format specification at `docs/gcode-3mf-format.md`
- Thumbnail generation (`thumbnails.py`) — BBL-specific metadata

### Moves to `bambu-cloud`

- Bambu LAN printing (`bambulabs-api`)
- Bambu Cloud printing (`bambu-lab-cloud-api`)
- Bambu Connect bridge (`cloud/bridge.py`)
- AMS filament slot mapping (`cloud/ams.py`)

## Migration path

Gradual decoupling — no big bang rewrite. Each phase is independently shippable.

**v0.4.0:** Extract both `bambu-3mf` and `bambu-cloud` as standalone libraries. estampo depends on both. No user-visible change, but all Bambu-specific code is out of estampo core.

**Future:** estampo has zero Bambu-specific imports. `bambu-3mf` and `bambu-cloud` are optional extras: `pip install estampo[bambu]`.

## Consequences

- `printer.py` will shrink to a thin dispatch layer, then eventually move to `bambu-cloud`
- `thumbnails.py` will move to `bambu-3mf`
- `cloud/` directory will move to `bambu-cloud`
- The `packaged_output` pipeline node will call `bambu-3mf` APIs instead of local functions
- Adding Prusa/Voron/etc. printer support becomes a matter of adding a new dispatch plugin, not forking estampo

## Anti-patterns to avoid

- Do not add new Bambu-specific logic to `pipeline.py`, `gcode.py`, or `arrange.py`
- Do not add new Bambu-specific logic to `slicer.py` or `cura.py` — the slicers produce generic G-code; packaging is `bambu-3mf`'s job
- Do not add OrcaSlicer-specific packaging logic assuming it will always be the slicer — CuraEngine output must go through the same packaging path
- Do not create a `prusa.py` or `voron.py` in estampo — printer-vendor code belongs in vendor-specific packages, not estampo core

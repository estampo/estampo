# ADR-003: Multi-Engine Slicer Support via Config Facade

**Status:** Accepted  
**Date:** 2026-02  

## Context

estampo originally targeted OrcaSlicer only. CuraEngine was added as a second backend due to OrcaSlicer's CLI instability (undocumented behavior changes, settings ignored, segfaults in headless mode). The two slicers have fundamentally different configuration models:

- **OrcaSlicer:** Three-level profile chain (machine → process → filament), each a named JSON profile; overrides layered on top
- **CuraEngine:** Flat key-value settings, no profile chain; machine geometry from `.def.json` definition files

We need both to coexist without forcing callers (pipeline.py, cli.py) to be aware of which engine is active.

Options considered:
1. **Separate code paths throughout** — engine-specific branches in every node and command
2. **Shared interface via abc/Protocol** — formal abstract base class for slicer backends
3. **Facade on SlicerConfig** — single config object populated from the active engine's sub-config; engine-specific code only in slicer.py and cura.py

## Decision

Use a **facade pattern** on `SlicerConfig`. Both `[slicer.orca]` and `[slicer.cura]` sub-configs can coexist in `estampo.toml`. At load time, `load_config()` populates top-level facade fields (`printer`, `process`, `overrides`, `filaments`, etc.) from whichever engine is active. Pipeline nodes read only the facade fields and remain engine-agnostic.

## Rationale

- **Minimal blast radius:** Engine-specific logic stays in `slicer.py` (OrcaSlicer) and `cura.py` (CuraEngine). pipeline.py, cli.py, and adapters.py need no engine awareness.
- **Backward compatibility:** TOML configs using the old flat `[slicer]` format (no engine sub-sections) still work — `load_config()` detects and migrates them.
- **Coexistence:** A single `estampo.toml` can have both `[slicer.orca]` and `[slicer.cura]` sections. The active engine is selected by `engine = "orca"` or `engine = "cura"` in `[slicer]`.

## Structure

```toml
[slicer]
engine = "cura"          # Selects active engine
version = "5.12.0"       # Engine version to pin

[slicer.orca]
printer = "Bambu Lab P1S 0.4 nozzle"
process = "0.20mm Standard @BBL P1S"
filaments = ["Generic PLA @base"]

[slicer.cura]
printer = "BambuLab P1S"
```

At runtime: `config.slicer.engine == "cura"`, `config.slicer.printer == "BambuLab P1S"` (populated from cura sub-config).

## Consequences

- `SlicerConfig` has some redundancy — facade fields duplicate sub-config fields at runtime
- Engine-specific features (e.g. OrcaSlicer process profiles, CuraEngine def chains) are only accessible via `config.slicer.orca.*` or `config.slicer.cura.*`
- `profiles.py` must handle engine-namespaced profile directories: `profiles/orca/` and `profiles/cura/`
- New engines should follow the same pattern: add a sub-config dataclass, add facade population in `load_config()`, add an engine module (e.g. `prusaslicer.py`)

## Anti-patterns to avoid

- Do not add engine `if/elif` branches in pipeline.py — the facade exists precisely to avoid this
- Do not read `config.slicer.orca.*` from pipeline nodes — use the facade fields
- Do not put CuraEngine logic in slicer.py or OrcaSlicer logic in cura.py
- Do not create a new `SlicerConfig` subclass per engine — the facade pattern handles this without inheritance

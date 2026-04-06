# ADR-003: Multi-Engine Slicer Support via Engine Config Hierarchy

**Status:** Accepted (revised 2026-04)  
**Date:** 2026-02 (original), 2026-04 (revised)

## Context

estampo originally targeted OrcaSlicer only. CuraEngine was added as a second backend due to OrcaSlicer's CLI instability (undocumented behavior changes, settings ignored, segfaults in headless mode). The two slicers have fundamentally different configuration models:

- **OrcaSlicer:** Three-level profile chain (machine → process → filament), each a named JSON profile; overrides layered on top
- **CuraEngine:** Flat key-value settings, no profile chain; machine geometry from `.def.json` definition files

We need both to coexist without forcing callers (pipeline.py, cli.py) to be aware of which engine is active.

## Decision

Use an **engine config hierarchy** with `EngineConfig` as a base class. Both `OrcaSlicerConfig` and `CuraSlicerConfig` inherit shared fields (`printer`, `overrides`) from `EngineConfig`. Engine-specific fields (`process`, `filaments`, `machine_overrides`, `filament_overrides`) live only on `OrcaSlicerConfig`.

`SlicerConfig` holds both sub-configs and exposes an `active` property that returns the sub-config for the selected engine. Callers use `config.slicer.active.printer` for shared fields and access engine-specific fields via `config.slicer.orca.process` where needed.

### Supersedes

The original design used facade fields on `SlicerConfig` — duplicating the active engine's fields at the top level. This was removed because:
- Callers couldn't tell whether to use `config.slicer.printer` (facade) or `config.slicer.orca.printer` (sub-config)
- Engine-specific fields (`machine_overrides`, `filament_overrides`) existed on the shared facade despite being OrcaSlicer-only
- The duplication made it unclear what the source of truth was

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

At runtime: `config.slicer.engine == "cura"`, `config.slicer.active.printer == "BambuLab P1S"`.

```python
class EngineConfig:          # shared fields
    printer: str | None
    overrides: dict[str, object]

class OrcaSlicerConfig(EngineConfig):   # orca-only fields
    process: str | None
    filaments: list[str]
    machine_overrides: dict[str, object]
    filament_overrides: dict[str, object]

class CuraSlicerConfig(EngineConfig):   # inherits shared fields only
    pass

class SlicerConfig:
    engine: str
    orca: OrcaSlicerConfig
    cura: CuraSlicerConfig

    @property
    def active(self) -> EngineConfig:
        return self.orca if self.engine == "orca" else self.cura
```

## Consequences

- Pipeline nodes use `config.slicer.active.*` for shared fields — no engine `if/elif` needed
- Engine-specific fields are accessed via the typed sub-config (e.g. `config.slicer.orca.process`)
- `profiles.py` must handle engine-namespaced profile directories: `profiles/orca/` and `profiles/cura/`
- New engines subclass `EngineConfig`, add a sub-config field to `SlicerConfig`, and extend the `active` property

## Anti-patterns to avoid

- Do not add engine `if/elif` branches in pipeline.py — use `active` or dispatch via slicer.py
- Do not put CuraEngine logic in orca.py or OrcaSlicer logic in cura.py
- Do not add OrcaSlicer-only fields to `EngineConfig` — they belong on `OrcaSlicerConfig`
